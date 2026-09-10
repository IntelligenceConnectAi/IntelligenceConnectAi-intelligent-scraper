# Worker performance baseline — revert reference

**Git tag: `worker-baseline-2026-09-10`** (commit `8ed04dc`)

If a later performance/scaling change makes things worse, this is the known-good
state to return to. To revert the worker to exactly this behavior:

```
git checkout worker-baseline-2026-09-10 -- Backend/worker/main.py Backend/worker/runner.py
```

then commit + push. (Only the two worker files define this behavior; nothing
else in that tag matters for scraping performance.)

---

## Architecture at this baseline

Single worker process (`worker/main.py`), no horizontal replicas. One Railway
service, `us-east4`. 24 vCPU / 24 GB RAM allocated — but the binding limit in
practice is the container's **process/thread ceiling**, not CPU/RAM (two live
incidents on 2026-09-10 traced to `pthread_create: Resource temporarily
unavailable` / Chrome `spawn EAGAIN` while CPU/RAM sat near-idle). Railway does
not expose a way to raise that ceiling.

### Concurrency constants

| Constant | File | Value | What it bounds | Process cost |
|---|---|---|---|---|
| `MAX_GLOBAL_CONCURRENT` | `worker/main.py` | **2** | Jobs running at once, across ALL clients (3rd+ waits in queue) | multiplies everything below |
| `MAX_CONCURRENT_CITIES` | `worker/runner.py` | **2** | Phase 1 (Maps) — cities scraped in parallel | contexts in 1 shared browser |
| `MAX_CONCURRENT_DETAIL` | `worker/runner.py` | **3** | Phase 2 (detail enrichment) — businesses in parallel | contexts in 1 shared browser |
| `MAX_CONCURRENT_EMAIL` | `worker/runner.py` | **2** | Phase 3 (email crawl) — sites in parallel | **separate full Chrome OS processes**, 1:1 with this number |

Worst-case simultaneous full Chrome processes, system-wide:
`MAX_GLOBAL_CONCURRENT × MAX_CONCURRENT_EMAIL = 2 × 2 = 4`.

### Phase 3 retry behavior (the fix that made the baseline good)

`_add_emails.process_one()` retries acquiring a working browser context up to
3× with backoff (2s, 4s) — covering both the pooled browser and the
fresh-launch fallback — before giving up on a site. Before this, a single
failed context-creation permanently dropped that site with an empty email,
silently counted as "attempted". That bug is what produced the ~16-emails runs.

### Per-item timeouts (unchanged from long-standing values)

- `EMAIL_CRAWL_TIMEOUT = 240.0` s — whole-site crawl budget (up to 11 fallback paths)
- `PAGE_TIMEOUT_MS = 15000` — single page navigation
- `CITY_SCRAPE_TIMEOUT_S = 180` — one city's Maps scrape

---

## Reference run — every future test compares against this

**Job `2f2db841-b5f7-4f2f-9b9a-fd6c5c5cf4d3`** · Plumbing / FL · 1 city ·
ran 2026-09-10 01:01–01:15 UTC on commit `8ed04dc`.

| Metric | Baseline | A change is acceptable if it is… |
|---|---|---|
| Total leads | 108 | ~same (depends on Google Maps, not our code) |
| With website | 90 | ~same |
| **Emails found** | **67** (74.4% of with-website) | **≥ ~67, or within a few of it** |
| Emails attempted | 90 (== with-website, no phantom counts) | still == with-website count |
| **Total run time** | **13 min 32 s** | **≤ ~13.5 min, ideally faster** |
| Phase 1+2 time | 28 s | ~same or faster |
| Phase 3 (email) time | 12 min 55 s | **≤ ~13 min, ideally much faster** — this is 95% of the job |

Any upgrade that drops email hit-rate below ~67 or pushes total time past
~13.5 min for an equivalent 1-city / ~90-with-website job is a regression and
should be reverted to this tag.
