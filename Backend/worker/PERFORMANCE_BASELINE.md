# Worker performance baseline — revert references

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
