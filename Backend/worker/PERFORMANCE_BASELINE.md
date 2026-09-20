# Worker performance baseline — revert references

## 2026-09-20 incident: pool self-healing missed a second failure mode (fixed — local, not yet deployed)

After the 2026-09-18 replica self-healing fixes shipped, resubmitted jobs
were still finishing "done" with very low email hit rates (single digits to
~30%, vs the healthy 51-56% every other job in the same batch got). This
looked at first like the Step 2 decoupled-browser-pool architecture itself
being the problem — it wasn't. Direct log evidence: hundreds of
`ZeroDivisionError`s landing within the same second, at the tail of a job.
Grepped the whole file for division operators in the email-crawl path —
there are none. This is coming from inside Playwright's own connection
handling, almost certainly triggered when a shared browser's underlying pipe
connection degrades under sustained load.

**The real bug**: `_add_emails`'s pool-health counter (`consecutive_failures`,
added 2026-09-15) only watched for "can't even open a browser context" — it
reset to 0 the moment a context opened successfully, *before* the crawl on
that context was even attempted. So a shared browser that opens contexts
fine but fails every actual crawl on them (this exact incident) was
completely invisible to the counter — it stayed at 0 through hundreds of
failures, and the pool never relaunched.

**Fix**: move the reset to only happen after a crawl genuinely completes;
count a timeout or any other crawl-time exception toward the same
consecutive-failure/relaunch trigger the context-open-failure path already
had. Also upgraded the generic exception log from just the exception type
name to a full traceback (`exc_info=True`), so any future recurrence is
diagnosable immediately instead of needing another investigation like this
one.

**Explicitly not done**: no revert of Step 2's decoupled browser pool, or
Step 4's replicas — the evidence points at a detection gap, not a flawed
architecture, and Step 2 alone proved a real ~2.4x throughput gain worth
keeping.

Revert target: the previous commit (self-throttling/self-restart fixes,
already deployed) if this proves unstable.

---

## 2026-09-18 incident #2: one replica stuck for 26+ min, retries kept re-hitting it (fixed, deployed)

Deployed the Phase 1 self-healing + retry-on-hard-failure fix below, then
live-tested it by resubmitting a real 15-job batch. Both fixes worked exactly
as designed — 4 jobs correctly failed loudly (`"Phase 1 ... unrecoverable
after 3 relaunch attempts"`) instead of faking a "done" result, and all 8
failed jobs show `retry_count: 2`, confirming every one got its full retry
budget before giving up. But 8 of 15 still ended up permanently failed.

Root-caused from the worker's own "[job X] starting ... replica Y" log lines
(unambiguous — logged by the real process, not inferred): **one specific
replica (`1f85734d`) was unable to launch any browser for 26+ minutes
straight**, cycling through job after job on its 2 slots — each one failing
instantly, then immediately re-claiming the next pending job (including its
own retries) within seconds. One error message gives the real signature:
`pthread_create: Resource temporarily unavailable` — the classic Linux
`pids.max` exhaustion error. The other 2 replicas were completely unaffected
the entire time and ran jobs to completion normally (one finished with 1751
emails found). Retrying doesn't help this failure mode: the retry keeps
landing back on the same stuck replica, hammering an already-struggling
container instead of giving it room to recover.

**Fixes (`worker/main.py`, `worker/runner.py`):**
- **Self-throttling.** `_check_pid_pressure()` reads this replica's own real
  cgroup pids usage (`/sys/fs/cgroup/pids.current` / `pids.max`) every poll
  cycle — direct measurement, not an inferred proxy like a failure count.
  Above `PIDS_THROTTLE_THRESHOLD = 0.85`, it stops claiming new jobs while
  letting existing work keep running, so a struggling replica naturally lets
  the other replicas absorb new work instead of failing job after job in
  place.
- **Self-restart backstop.** If still blocked from claiming free capacity
  after `MAX_PID_PRESSURE_DURATION_S = 300` (5 min) of throttling, that's not
  transient business — it's genuinely stuck. The replica calls `os._exit(1)`
  (deliberately bypassing normal exception handling, since a resource-starved
  process might not complete a graceful shutdown either). Confirmed via
  Railway's own docs: the default restart policy is On Failure, and a
  non-zero exit restarts *only* the crashed replica — the other 2 are
  untouched and keep serving the whole time.
- **New `ReplicaResourceError`** (runner.py): raised when a phase's browser
  subsystem can't start at all (Phase 1's initial launch, Phase 1's
  exhausted-relaunch case, and a newly-caught Phase 3 gap — its initial
  browser-pool launch previously failed *silently*, returning untouched
  records so the job completed looking like a clean 0-email run instead of
  failing). `_process_job`'s failure handler checks for this type
  specifically and gives it `MAX_REPLICA_RESOURCE_RETRIES = 8` instead of the
  normal `MAX_AUTO_RETRIES = 2` — landing on a struggling replica isn't the
  job's fault, so it shouldn't burn through the same small budget meant for
  genuine per-job problems. Both share the same `retry_count` column (no
  schema change), just a different ceiling depending on which failure just
  happened.

Revert target: `worker-stable-step4` (tag) — before either 2026-09-18 fix.

---

## 2026-09-18 incident #1: Phase 1 browser death + zero-retry hard failures (fixed, deployed)

Live-tested Step 4 at 3 replicas / 15 real jobs. Result: 6 jobs permanently
failed and 1 "completed" with 100% cities done but zero real leads — all
traced to one ~38-second window where a single replica (`d9bc375c`) cycled
through 7 jobs on its 2 slots in rapid succession, every one hitting
`Target page, context or browser has been closed`. Not a double-claim, not a
deploy/restart, not a connection-pool issue — confirmed no deployment
happened near that time and every job was claimed exactly once. Self-resolved
after ~38s; the same replica ran jobs normally before and after.

This exposed two real, separate gaps:

1. **Phase 1 had no self-healing.** Unlike Phase 3 (fixed 2026-09-15), Phase
   1 shares one browser across every city with no recovery path — when it
   died mid-job, every remaining city failed instantly (caught individually),
   so the job still "completed" as `done` with 100% cities and zero leads
   (job `3afdd4f5`, Plumbing/NY — 82 cities' worth of identical
   `Browser.new_context` failures inside 2 seconds).
2. **A hard failure (uncaught exception) got zero automatic retries.** The 6
   failed jobs all show `retry_count: 0` — they never touched the watchdog's
   `MAX_AUTO_RETRIES` budget at all, since that only fires for *stale* jobs,
   not ones that fail immediately with an exception.

**Fixes (`worker/runner.py`, `worker/main.py`):**
- Phase 1 now tracks consecutive city failures; past `CONSECUTIVE_FAILURE_THRESHOLD
  = 8`, relaunches its single browser (capped at `MAX_BROWSER_RELAUNCHES = 3`).
  If still dead after that, raises a real error instead of silently
  completing — there's no earlier-phase data worth salvaging from a dead
  Phase 1, unlike Phase 3, so failing loudly (and now retrying, per the next
  fix) is the correct behavior, not completing with fabricated-looking empty
  results.
- `_process_job`'s generic exception handler now shares the watchdog's
  `MAX_AUTO_RETRIES` budget (same `retry_count` column, so a job can't
  accumulate separate budgets per failure mode) instead of marking `failed`
  on the first hard exception. Only sends the failure notification once
  retries are genuinely exhausted — same as the watchdog already does.
- Also hardened `_scrape_city`'s `finally: context.close()` (was a bare
  unguarded call) to the same `except asyncio.CancelledError: raise / except
  Exception: pass` pattern used everywhere else in this file.

**Not yet explained, flagged for follow-up, no fix proposed:** job
`41b1568b` (Electricians/OH) attempted its full 8,495 with-website count but
found only 82 emails (~1%, vs the normal 30-65%) — contexts were being
created successfully (not the dead-pool pattern), so something else degraded
actual page scraping for that run specifically. Needs its own investigation
before proposing anything.

Revert target: `worker-stable-step4` (tag) — Step 4 deployed and
live-verified at 3 replicas, before these two fixes.

---

## Step 4: horizontal replicas (deployed and live-verified at 3 replicas)

Code is done locally (not pushed/deployed yet — pending confirmation).
Revert target if it proves unstable: `worker-stable-pre-step4` (tag), which is
the last known-good single-instance state, identical in behavior to
`worker-stable-step2` plus everything fixed since (browser-leak-on-cancel,
DB pool sizing, email-pool self-healing).

**What changed (`worker/main.py`, `worker/runner.py`):**
- Job claiming (`_poll_loop`) now uses `SELECT ... FOR UPDATE SKIP LOCKED`
  then an `UPDATE ... RETURNING started_at` in the same transaction, so
  multiple replicas can poll concurrently without ever double-claiming a job.
  The returned `started_at` becomes that job's "claim token."
- `_watchdog_loop`'s stuck-job query does the same `FOR UPDATE SKIP LOCKED` —
  with N replicas each running their own watchdog, only one ever actually
  resets a given stuck row. No leader election needed.
- `HEARTBEAT_WORKER_ID` is now `RAILWAY_REPLICA_ID` (falls back to `"local"`)
  instead of the old hardcoded `"primary"` — each replica gets its own
  `worker_heartbeats` row instead of all of them overwriting one shared row.
- **Ownership fencing** (`runner.py`'s `_is_job_canceled`, now also takes
  `claim_token`): a replica's watchdog can only `task.cancel()` a task it is
  itself tracking — it has no way to reach into another replica's process. If
  replica B's watchdog resets a job that's actually still alive and running
  on replica A (a false-positive stuck read, or A genuinely dead), A's task
  needs its own way to notice. `reset_job_to_pending()` clears
  `jobs.started_at`; the next claim (by whichever replica) stamps a fresh
  value. Every per-item check across all 3 phases, plus the final backstop,
  now also compares the job's current `started_at` against the `claim_token`
  it was handed at claim time — a mismatch means "someone else owns this job
  now," and the stale task stops cooperatively, same code path as user
  cancellation. `main.py`'s generic failure handler in `_process_job` also
  checks this before writing `status='failed'`, so a stale task's own
  unrelated error can't stomp on a fresh attempt's row either.
- `MAX_GLOBAL_CONCURRENT` stays a **per-replica** cap (unchanged at 2) — total
  cluster capacity is this × replica count. No cross-replica coordination for
  concurrency itself, only for claiming/ownership.

**Prerequisite before deploying more than 1 replica — not yet done:**
Supabase's session pooler `pool_size` is currently 15 (Database Settings),
shared between every replica's worker pool (`min=3/max=8` each) and the API's
(`min=2/max=5`). N replicas need `N × 8 + 5` connections at peak. This must be
raised (the underlying free-tier hard cap is 60 total DB connections, so
there's real room — see the 2026-09-17 planning conversation) before scaling
past 1 replica, or it reproduces the 2026-09-14 EMAXCONNSESSION outage.

**Also not addressed by this step:** Railway rebuilds every connected service
on any push, including frontend-only ones (confirmed 2026-09-14/15) — with
more replicas running more concurrent jobs, a routine push now risks
interrupting more jobs at once, not fewer. Worth pairing path-based deploy
triggers with this before running many replicas in practice.

---

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
