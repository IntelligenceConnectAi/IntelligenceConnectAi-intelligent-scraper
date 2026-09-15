# Worker performance baseline — revert references

## 2026-09-15 incident: dead email browser pool never recovered (fixed — read this first)

Two large jobs (Electrical/CA, 12534 with-website leads; Electrical/GA, 8658)
each ran ~14 hours and finished "done" with a tiny fraction of the emails a
healthy run should find (1008 and 250 — normal hit rate is ~65-76%, so these
should have found roughly 8000-9500 and 5600-6600 respectively). Both also
showed `emails_attempted` noticeably *higher* than `with_website`, which
looked at first like duplicate job runs.

**Root causes (two separate bugs, both in `_add_emails`'s Phase 3):**

1. **No whole-pool self-healing.** `EMAIL_BROWSER_POOL_SIZE=2` browsers are
   shared across the whole job. If both die at once (observed live:
   `Browser.new_context: Target page, context or browser has been closed` on
   literally every subsequent attempt, for hours), the per-item retry loop
   only ever launches one-off replacement browsers on individual failures —
   it never confirms the *pool* is healthy again. Once truly dead, it stayed
   dead for the rest of the run: thousands of remaining sites each burned a
   full 3-attempt/2s+4s-backoff retry against a permanently-broken pool,
   finding nothing, for hours.
2. **Double-counted failures.** The `ctx is None` (pool exhausted) branch did
   `done[0] += 1` explicitly, but the surrounding `finally` block *also*
   unconditionally does `done[0] += 1` on every exit path including that
   return — every dead-pool failure was counted twice toward
   `emails_attempted`. This, not a duplicate job execution, is what produced
   `emails_attempted > with_website` (confirmed: the CA job's overshoot of
   9870 matched almost exactly the count of "browser recovery failed" log
   lines for that run).

Contributing factor: both jobs got interrupted mid-run at least once by a
worker redeploy — Railway rebuilds *all* connected services (api + worker)
on every push to the branch, including frontend-only commits, so any code
push during a long job's run risks orphaning it. Each interruption forced a
full Phase 3 restart from the enrichment checkpoint (which only covers
Phase 1+2 — Phase 3 has no per-site checkpoint), discarding whatever emails
had already been found in that pass.

**Fixes (`worker/runner.py`, `_add_emails`):**
- Track consecutive total failures across all concurrent items; past
  `CONSECUTIVE_FAILURE_THRESHOLD = 12`, tear down and relaunch the whole
  pool (not just one browser) once. Cap at `MAX_POOL_RELAUNCHES = 3` — after
  that, mark the pool `pool_dead` and skip remaining sites instantly instead
  of burning ~18s of guaranteed-to-fail retry per site for the rest of a
  multi-hour job. Skipped-due-to-dead-pool sites are *not* counted toward
  `emails_attempted`, so a future incident shows up as an honest low
  attempted count instead of a misleadingly "complete" 100%.
- Removed the double `done[0] += 1`.

**Not fixed here, flagged for follow-up:** Railway's lack of path-based
deploy filtering means any push can orphan a long-running job. Worth
configuring separate deploy triggers (or splitting repos) so frontend-only
changes don't rebuild the worker.

---

## 2026-09-14 incident: zombie process leak (fixed — read this first)

Three jobs failed instantly with `BrowserType.launch: Target page, context or
browser has been closed` after the worker had been running fine for 4 days
(since the 09-10 deploy). Checked the live container:

```
pids.current = 989 / 1000        (should idle around ~50-90)
pids.events "max" = 8523         (fork attempts denied, cumulative)
941 total processes, 937 of them zombies
PID 1 = `python -m worker.main` directly — no init system
```

**Root cause:** the Dockerfile ran the worker as PID 1 with no init process.
Chrome spawns many subprocesses per browser launch (crashpad handler, zygote,
renderer, GPU); whenever a browser/context gets force-closed — which this
worker's per-item timeouts and watchdog cancellations do constantly — some of
those subprocesses get orphaned and reparented to PID 1. A bare Python
process never reaps unknown reparented children, so they sit forever as
zombies, and **a zombie still counts against `pids.max`**. This is separate
from the concurrency tuning below: it accumulates regardless of concurrency,
just slower at lower concurrency, and eventually saturates the container no
matter what the settings are.

**Fix:** `Backend/Dockerfile.worker` now installs `tini` and runs it as
`ENTRYPOINT` (PID 1), which reaps zombies regardless of what the Python code
does — the standard fix for this well-known Docker pattern. Immediate
mitigation was a plain restart (`railway restart` — resets pids.current to
~50 instantly, but doesn't fix the underlying leak; it would have
re-accumulated over the following days without the Dockerfile change).

**If jobs ever start instantly-failing with the same browser-launch error
again:** check `pids.current` / zombie count first (see commands below)
before assuming it's a concurrency-tuning problem — this specific failure
mode is diagnosed with `pids.current` near `pids.max` while
`worker_heartbeats.running_jobs = 0`, i.e. saturated pids with a worker that
thinks it's idle.

```
railway ssh ... "cat /sys/fs/cgroup/pids.current /sys/fs/cgroup/pids.max /sys/fs/cgroup/pids.events"
railway ssh ... "ls -d /proc/[0-9]* | wc -l"                          # total processes
railway ssh ... "grep -l 'State:.*Z' /proc/[0-9]*/status | wc -l"     # zombie count
railway ssh ... "cat /proc/1/cmdline"                                  # confirm tini, not python, is PID 1
```

---

Two tagged known-good states:

| Tag | Commit | What it is |
|---|---|---|
| **`worker-stable-step2`** | (this commit) | **Current production config.** Step 2 decoupled browser pool, validated live under 2 concurrent jobs with direct cgroup pid measurement. Use this as the revert target. |
| `worker-baseline-2026-09-10` | `8ed04dc` | Pre-Step-2 fallback. Conservative (email crawl effectively 2-way, 1 browser per crawl). Slower but rock-solid. Fall back here only if `worker-stable-step2` ever proves unstable. |

To revert the worker to either:

```
git checkout <tag> -- Backend/worker/main.py Backend/worker/runner.py
```

then commit + push. Only those two files define scraping performance.

---

## The binding constraint

Single worker process (`worker/main.py`), no horizontal replicas. One Railway
service, `us-east4`, 24 vCPU / 24 GB RAM.

**CPU/RAM are not the limit.** The limit is the container's cgroup
process/thread ceiling: `/sys/fs/cgroup/pids.max = 1000` (processes + threads
combined). Three live incidents on 2026-09-10 were all `pthread_create:
Resource temporarily unavailable` / Chrome `spawn EAGAIN` while CPU sat at
~5/24 and RAM under 3 GB. Railway exposes no way to raise `pids.max`.

Measured pid costs on the actual container:

| Item | Cost |
|---|---|
| Idle worker | ~55–75 pids |
| One full headless Chrome process | ~100 pids |
| Each extra context+page on that browser | ~30 pids |
| A whole separate browser + 1 page | ~132 pids |

The design lever: **share a small pool of browser processes across many
contexts**, rather than one process per concurrent crawl.

---

## Current production config (`worker-stable-step2`)

| Constant | File | Value | Bounds | Cost model |
|---|---|---|---|---|
| `MAX_GLOBAL_CONCURRENT` | `main.py` | **2** | Jobs running at once, across ALL clients (3rd+ queues) | multiplies everything below |
| `MAX_CONCURRENT_CITIES` | `runner.py` | **2** | Phase 1 (Maps) — cities in parallel | contexts on 1 shared browser |
| `MAX_CONCURRENT_DETAIL` | `runner.py` | **3** | Phase 2 (enrichment) — businesses in parallel | contexts on 1 shared browser |
| `EMAIL_BROWSER_POOL_SIZE` | `runner.py` | **2** | Phase 3 — actual Chrome processes in the pool | ~100 pids each |
| `MAX_CONCURRENT_EMAIL` | `runner.py` | **3** | Phase 3 (email crawl) — sites in parallel | contexts round-robin across the pool, ~30 pids each |

### Measured `pids.peak` under 2 concurrent jobs (the decisive number)

| Config (EMAIL / DETAIL / CITIES) | `pids.peak` / 1000 | Margin | Verdict |
|---|---|---|---|
| 4 / 4 / 3 (first Step 2 pass) | 982 | 18 | too tight — rejected |
| **3 / 3 / 2 (current)** | **877** | **123** | **safe — locked in** |

`pids.events` "max" (count of denied forks) stayed **0** at both configs, and
the peak is a transient spike when both jobs launch their Phase 3 browser
pools within ~3 s of each other, not steady state.

**Rule for any future increase:** re-measure `pids.peak` via
`railway ssh ... "cat /sys/fs/cgroup/pids.peak"` under **2 jobs running at
once** (a single job in isolation never reproduces the ceiling). Keep peak
≤ ~900. "It didn't error once" is not sufficient evidence.

### Phase 3 retry behavior (keep this — it's load-bearing)

`_add_emails.process_one()` retries acquiring a working browser context up to
3× with backoff (2 s, 4 s), covering both the pooled browser and a
fresh-launch fallback, before giving up on a site. Without it, a single
transient context-creation failure permanently dropped that site with an
empty email, silently counted as "attempted" — that bug produced runs with
~16 emails where ~70 were findable.

### Per-item timeouts (long-standing, unchanged)

- `EMAIL_CRAWL_TIMEOUT = 240.0` s — whole-site crawl budget (up to 11 fallback paths)
- `PAGE_TIMEOUT_MS = 15000` — single page navigation
- `CITY_SCRAPE_TIMEOUT_S = 180` — one city's Maps scrape

---

## Reference runs — compare every future test against these

All are Plumbing / FL / Miami, 1 city, ~90–96 with-website leads.

| Run | Config | Emails found | Total time | Phase 3 time | `pids.peak` |
|---|---|---|---|---|---|
| **pre-Step-2** (`2f2db841`) | 2/2/3/2 baseline | 67 / 90 (74%) | 13 m 32 s | 12 m 55 s | — |
| **Step 2 solo** (`47366145`) | 2/2/3/4/3 | 73 / 96 (76%) | **5 m 36 s** | 5 m 01 s | (not the stress case) |
| **Step 2 concurrent, job A** (`f4bce49c`) | 2/2/3/3/2, 2 jobs at once | 68 / 94 (72%) | 9 m 06 s | 8 m 28 s | 877 (shared w/ job B) |
| **Step 2 concurrent, job B** (`e0e5eb7d`) | 2/2/3/3/2, Roofing/Tampa | 74 / 112 (66%) | 9 m 22 s | 8 m 51 s | 877 |

### What "good" looks like now

- **Solo 1-city job:** ~5–6 min total, email hit-rate ~72–76 %.
- **Two concurrent 1-city jobs:** ~9 min each (they share the box), hit-rate
  ~66–75 %, `pids.peak` ≤ ~900.
- `emails_attempted` must equal `with_website` (no phantom failed-launch
  counts — that's the retry fix working).

A change is a **regression** (revert to `worker-stable-step2`, or to
`worker-baseline-2026-09-10` if the regression is in Step 2 itself) if:
solo job > ~7 min, or hit-rate drops below ~65 % on an equivalent market, or
`pids.peak` > 920 under 2 jobs, or any `pthread_create` / `EAGAIN` /
`browser recovery failed after retries` lines appear.

---

## Throughput gain from Step 2, in plain terms

- A single client's 1-city job: **~13.5 min → ~5.5 min** (~2.4× faster).
- Two clients' jobs at once: each ~9 min, but two run in parallel → roughly
  **2× the clients served per hour** vs pre-Step-2 (where 2 concurrent jobs
  ran near the pid ceiling and were the source of the incidents).
- Bigger multi-city jobs scale the same way — Phase 3 (email crawl, ~95 % of
  wall-clock) is now 3-way concurrent per job instead of effectively 2-way,
  on a 2-process pool instead of N separate processes.

## What's left for more speed (Step 4, a real project — not tuning)

The 1000-pid ceiling is per-container. The only way past it is **horizontal
replicas**: multiple worker containers, each with its own ceiling. Needs
`SELECT ... FOR UPDATE SKIP LOCKED` job claiming, per-replica heartbeat
identity, and a multi-replica-safe watchdog. Deferred until demand justifies
the engineering.
