"""
Intelligent Scraper — Job Runner
Uses full Chrome (channel="chrome").
3 separate phases: Maps → Enrich → Email
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
import csv
import io
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import asyncpg
import pandas as pd
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════
# ── Concurrency, sized against a MEASURED ceiling ──
# The binding limit on this Railway container is the cgroup process/thread
# ceiling: /sys/fs/cgroup/pids.max = 1000 (processes + threads combined).
# NOT CPU/RAM — 24 vCPU/24GB sat near-idle during two separate incidents on
# 2026-09-10 that were really pthread_create/Chrome-spawn EAGAIN failures.
# Railway exposes no way to raise pids.max.
#
# So the lever is: share a SMALL pool of browser processes across MANY
# contexts, instead of one process per concurrent crawl. Phase 1 and Phase 2
# already do this. Phase 3 now does too (EMAIL_BROWSER_POOL_SIZE decoupled
# from MAX_CONCURRENT_EMAIL, 2026-09-10 Step 2).
#
# Step 2 was validated live with a 2-concurrent-job stress test and DIRECT
# cgroup readings (/sys/fs/cgroup/pids.peak). The naive steady-state math
# badly underestimated the real peak — Chrome's launch-time transient fork
# spike plus Phase 1/2 browsers briefly overlapping Phase 3 startup add a
# lot. Measured peaks, 2 concurrent jobs:
#   4 / 4 / 3  (EMAIL / DETAIL / CITIES) -> pids.peak 982 / 1000  (18 margin — too tight)
#   3 / 3 / 2                            -> pids.peak ~??? (this config; target <=880)
# pids.events "max" stayed 0 throughout (no fork was ever actually denied),
# jobs completed clean — but 18 pids of headroom is not a margin to run
# production on, hence this pullback. Still ~1.6-2x the pre-Step-2 Phase 3
# throughput. Re-measure pids.peak (not just "did it error") before any
# future increase, always with 2+ jobs running at once.
EMAIL_BROWSER_POOL_SIZE = 2   # actual Chrome processes in Phase 3's pool (~100 pids each)
MAX_CONCURRENT_EMAIL    = 3   # concurrent site crawls in Phase 3 — contexts spread
                              # round-robin across the pool above (~30 pids each)
MAX_CONCURRENT_DETAIL   = 3   # Phase 2 — contexts on 1 shared browser
MAX_CONCURRENT_CITIES   = 2   # Phase 1 (Maps) — contexts on 1 shared browser
PAGE_TIMEOUT_MS       = 15000
FOOTER_WAIT_MS        = 3000
# _crawl_site_for_email() tries up to 11 fallback paths per site (PRIORITY_PATHS
# below), stopping early only once it finds an email at the site's own domain.
# Worst case — no early match, every one of the 11 pages needs its full
# PAGE_TIMEOUT_MS (15s) — that's 11*15s ~= 165s of page loads alone, plus
# ~10-15s of per-page wait/sleep overhead: ~178s total. 240s leaves a real ~60s
# margin over that worst case, deliberately — don't shrink this without
# re-doing the math, a shorter cap cuts off legitimate slow-loading sites
# before they ever reach page 3+ where the email often actually is.
EMAIL_CRAWL_TIMEOUT   = 240.0
MAPS_DETAIL_TIMEOUT   = 10.0
# Phase 1 (Maps) has no other bound — _scroll_to_end only exits on a stabilized
# card count or Google's "end of list" marker. Without this, a dense query on a
# large metro could legitimately run past the worker's stuck-job threshold
# (worker/main.py's STUCK_THRESHOLD_MIN) with zero DB writes and get
# incorrectly killed by the watchdog. Applies per-city even under Phase 1's
# concurrent scraping (MAX_CONCURRENT_CITIES) — each concurrent slot still
# gets its own independent 180s cap.
CITY_SCRAPE_TIMEOUT_S = 180

PRIORITY_PATHS = [
    "",
    "/contact-us", "/contact", "/about-us", "/about",
    "/privacy-policy", "/terms-and-conditions", "/terms",
    "/contact.html", "/about.html", "/privacy.html",
]

ALWAYS_JUNK_DOMAINS = {
    "google.com", "example.com", "test.com",
    "mailservice.com", "sentry.io", "wixpress.com",
    "squarespace.com", "wpengine.com",
}
LEGIT_TLDS = {
    "com","org","net","edu","gov","biz","info","co","us","ca",
    "uk","de","io","ai","app","dev","tech","store","online","site",
    "blog","me","tv","cc","ch","se","no","au","nz"
}
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b")

_EXTRACT_JS = r"""
() => {
    const phoneRegex = /(\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4})/;
    const addressKeywords = [' St',' St,',' Ave',' Ave,',' Rd',' Rd,',' Blvd',' Dr',' Dr,',' Ln',' Ln,',' Way',' Ct',' Ct,',' Pl',' Pl,',' Hwy',' Pkwy',' Suite',' #',' Ste'];

    function looksLikeAddress(txt) {
        if (!txt || txt.length < 5) return false;
        return /\d/.test(txt) && addressKeywords.some(kw => txt.includes(kw));
    }
    function looksLikePhone(txt) {
        if (!txt) return false;
        const m = txt.match(phoneRegex);
        return m ? m[0] : null;
    }
    function isJunk(txt) {
        if (!txt) return true;
        const lower = txt.toLowerCase();
        return /open|closed|hours/.test(lower) || txt.length < 5;
    }

    const results = [];
    document.querySelectorAll('div[role="feed"] > div > div[jsaction]').forEach(card => {
        const row = { name:'', category:'', rating:'', reviews:'', address:'', phone:'', website:'', maps_url:'' };

        const nameEl = card.querySelector('.qBF1Pd');
        if (nameEl) row.name = nameEl.innerText.trim();
        if (!row.name) {
            const mainLink = card.querySelector('a.hfpxzc');
            if (mainLink) {
                const label = mainLink.getAttribute('aria-label') || '';
                if (label) row.name = label.trim();
            }
        }
        if (!row.name) return;

        const mapsEl = card.querySelector('a.hfpxzc');
        if (mapsEl) row.maps_url = mapsEl.href || '';

        const webSelectors = [
            'a[data-value="Website"]',
            'a[data-value="website"]',
            'a[data-item-id="authority"]',
        ];
        for (const sel of webSelectors) {
            const el = card.querySelector(sel);
            if (el && el.href) { row.website = el.href; break; }
        }

        const catEl = card.querySelector('.W4Efsd .W4Efsd span');
        if (catEl) row.category = catEl.innerText.trim();

        const ratingEl = card.querySelector('.MW4etd');
        if (ratingEl) row.rating = ratingEl.innerText.trim();

        const revEl = card.querySelector('.UY7F9');
        if (revEl) row.reviews = revEl.innerText.replace(/[()]/g,'').trim();

        const allText = card.innerText || '';

        if (!row.rating) {
            const m = allText.match(/\b([1-4]\.[0-9]|5\.0)\b/);
            if (m) row.rating = m[1];
        }
        if (!row.reviews) {
            const m = allText.match(/\(([0-9,]+)\)/);
            if (m) row.reviews = m[1].replace(/,/g,'');
        }

        card.querySelectorAll('[aria-label]').forEach(el => {
            const label = (el.getAttribute('aria-label') || '').trim();
            if (/^Address[\s:]/i.test(label) && !row.address) {
                const addr = label.replace(/^Address[\s:]*/i,'').trim();
                if (!isJunk(addr)) row.address = addr;
            }
            if (/^Phone[\s:]/i.test(label) && !row.phone) {
                row.phone = label.replace(/^Phone[\s:]*/i,'').trim();
            }
        });

        if (!row.address) {
            const addrEl = card.querySelector('[data-item-id="address"]');
            if (addrEl) {
                const txt = (addrEl.getAttribute('aria-label') || addrEl.innerText || '').replace(/^Address[\s:]*/i,'').trim();
                if (looksLikeAddress(txt)) row.address = txt;
            }
        }

        if (!row.phone) {
            const telEl = card.querySelector('a[href^="tel:"]');
            if (telEl) row.phone = telEl.href.replace('tel:','').trim();
        }

        if (!row.address) {
            const spans = card.querySelectorAll('.W4Efsd > span, .W4Efsd > div');
            for (const span of spans) {
                const txt = (span.innerText || '').split('\n')[0].trim();
                if (looksLikeAddress(txt) && !isJunk(txt)) { row.address = txt; break; }
            }
        }

        if (!row.phone) {
            const spans = card.querySelectorAll('.W4Efsd span, .W4Efsd div');
            for (const span of spans) {
                const txt = (span.innerText || '').split('\n')[0].trim();
                const ph = looksLikePhone(txt);
                if (ph && txt.replace(/[\d\s\-\(\)\+]/g,'').length < 3) { row.phone = ph; break; }
            }
        }

        if (!row.phone) {
            const m = allText.match(phoneRegex);
            if (m) row.phone = m[0];
        }

        results.push(row);
    });
    return results;
}
"""

_DETAIL_JS = r"""
() => {
    const phoneRegex = /(\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4})/;
    const result = { website: '', phone: '' };

    const webSelectors = [
        'a[data-item-id="authority"]',
        'a[data-tooltip="Open website"]',
        'a[aria-label*="website" i]',
    ];
    for (const sel of webSelectors) {
        const el = document.querySelector(sel);
        if (el && el.href && !el.href.includes('google.com')) {
            result.website = el.href;
            break;
        }
    }

    document.querySelectorAll('[aria-label]').forEach(el => {
        const label = (el.getAttribute('aria-label') || '').trim();
        if (/^Phone[\s:]/i.test(label) && !result.phone) {
            result.phone = label.replace(/^Phone[\s:]*/i,'').trim();
        }
    });

    if (!result.phone) {
        const telEl = document.querySelector('a[href^="tel:"]');
        if (telEl) result.phone = telEl.href.replace('tel:','').trim();
    }

    if (!result.phone) {
        document.querySelectorAll('button, span').forEach(el => {
            if (result.phone) return;
            const txt = (el.innerText || '').trim();
            const m = txt.match(phoneRegex);
            if (m && txt.replace(/[\d\s\-\(\)\+]/g,'').length < 3) {
                result.phone = m[0];
            }
        });
    }

    return result;
}
"""


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def sanitize(name):
    return name.replace(" ", "_").replace("/", "-")

def format_phone(raw):
    if not raw: return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"+1 {digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return raw.strip()

def normalize_website(raw):
    """For COMPARISON only -- the original, unmodified Website string is still
    what gets stored/shown. Strips protocol/www/trailing-slash/query/fragment so
    'https://Acme.com/' and 'http://www.acme.com' compare equal. Deliberately
    keeps the path (never collapses to domain-only) -- two different location
    pages on one franchise's root domain are still different businesses."""
    if not raw: return ""
    url = raw.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    url = url.split("?")[0].split("#")[0].rstrip("/")
    return url

def clean_address(raw):
    if not raw: return ""
    text = raw.replace("Â·", "·").replace("Â", "").replace("\u00b7", "|")
    parts = re.split(r"[·|\n]", text)
    address_keywords = [
        r"\d+\s+\w", "St", "Ave", "Rd", "Blvd", "Dr", "Ln",
        "Way", "Ct", "Pl", "Hwy", "Pkwy", "Suite", "#", "Ste"
    ]
    junk_patterns = [
        r"open\s*\d", r"closed", r"24\s*hours",
        r"^\+?1?\s*[\(\d][\d\s\-\(\)]{8,}$",
        r"^(hvac|plumb|electr|roof|landscap|contractor|service)"
    ]
    best = ""
    for part in parts:
        part = part.strip()
        if not part or len(part) < 5: continue
        if any(re.search(p, part, re.IGNORECASE) for p in junk_patterns): continue
        if bool(re.search(r"\d", part)) and any(kw.lower() in part.lower() for kw in address_keywords):
            best = part; break
    return best.strip()

def is_real_tld(domain):
    parts = domain.rsplit(".", 1)
    return len(parts) >= 2 and parts[1].lower() in LEGIT_TLDS

def clean_email(email):
    email = email.strip().rstrip(".,;:'\"")
    return email if "@" in email and "." in email else ""

def is_valid_email(email):
    if re.search(r"\.(png|jpg|jpeg|gif|css|js|woff|svg|ico|webp|pdf|xml)$", email, re.IGNORECASE): return False
    if re.search(r"@\d+x", email): return False
    if re.search(r"(logo|img|banner|icon|avatar)", email, re.IGNORECASE): return False
    parts = email.split("@")
    if len(parts) != 2: return False
    local, domain = parts
    if domain.lower() in ALWAYS_JUNK_DOMAINS: return False
    if any(w in domain.lower() for w in ["thenumberprovided","example","test","fake","noreply"]): return False
    if not is_real_tld(domain): return False
    if " " in email: return False
    junk_locals = ["noreply","no-reply","donotreply","do-not-reply",
                   "webmaster","postmaster","mailer-daemon","press"]
    if local.lower() in junk_locals: return False
    return True

def score_email(email, website_domain):
    score = 0
    try: local, domain = email.split("@")
    except: return 0
    if domain.lower() == website_domain.lower(): score += 20
    elif website_domain.endswith("." + domain) or domain.endswith("." + website_domain): score += 10
    for pref in ["info","sales","contact","service","support","admin","hello","office","mail","accounts","help"]:
        if local.lower().startswith(pref): score += 8; break
    if any(w in local.lower() for w in ["dev","test","noreply","no-reply","spam","fake","example","press"]): score -= 15
    if len(local) > 30: score -= 5
    if domain.lower() in {"gmail.com","yahoo.com","hotmail.com","outlook.com"}: score -= 3
    return score

def select_best_email(emails, website_url):
    if not emails: return ""
    domain = urlparse(website_url).netloc.replace("www.", "")
    scored = [(score_email(e, domain), e) for e in emails]
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return scored[0][1]


# ═══════════════════════════════════════════════════════════════
#  DB PROGRESS HELPER
# ═══════════════════════════════════════════════════════════════
async def _update_job(pool: asyncpg.Pool, job_id: str, **kwargs):
    if not kwargs: return
    now = datetime.now(timezone.utc)
    resolved = {k: now if v == "NOW()" else v for k, v in kwargs.items()}
    keys = list(resolved.keys())
    set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(keys))
    values = [resolved[k] for k in keys]
    sql = f"UPDATE jobs SET {set_clauses}, updated_at = $1 WHERE id = ${len(keys)+2}"
    async with pool.acquire() as conn:
        await conn.execute(sql, now, *values, job_id)

async def _update_city(pool: asyncpg.Pool, job_id: str, city: str, **kwargs):
    if not kwargs: return
    now = datetime.now(timezone.utc)
    resolved = {k: now if v == "NOW()" else v for k, v in kwargs.items()}
    keys = list(resolved.keys())
    set_clauses = ", ".join(f"{k} = ${i+3}" for i, k in enumerate(keys))
    values = [resolved[k] for k in keys]
    sql = f"UPDATE job_cities SET {set_clauses} WHERE job_id = $1 AND city = $2"
    async with pool.acquire() as conn:
        await conn.execute(sql, job_id, city, *values)


class ReplicaResourceError(Exception):
    """Raised when a phase's browser subsystem can't get going at all — a
    resource/environment problem with THIS replica right now (e.g. it's out
    of pids and can't spawn Chrome), not a problem with the job itself.
    worker/main.py's failure handler treats this differently from a generic
    exception: it doesn't spend the job's retry budget, since landing on a
    replica that happens to be struggling isn't the job's fault (2026-09-18
    incident: retries kept landing back on the same stuck replica and
    burned through their whole budget on an infrastructure problem)."""
    pass


async def _is_job_canceled(pool: asyncpg.Pool, job_id: str, claim_token=None) -> bool:
    """Cooperative stop-check, polled before starting each new unit of work in
    every phase, for two independent reasons to abandon this run:

    1. User-initiated cancellation. POST /jobs/{id}/cancel runs in the API
       process, not this worker process — Railway gives them no shared memory —
       so it can only flip the DB row, never signal a running task directly.
       Without this, a 'canceled' job just kept scraping to completion
       regardless (a real incident: cancel requested, emails_attempted kept
       climbing for another 250+ sites).

    2. Reclaimed by another worker replica (Step 4 — only checked when
       claim_token is given). With multiple replicas, the watchdog on a
       DIFFERENT replica can decide this job looks stuck and reset + re-claim
       it — it has no way to reach into THIS replica's process to cancel the
       original task directly, unlike the single-instance case where the
       watchdog and the task always share one process. reset_job_to_pending()
       clears jobs.started_at, and the next claim stamps a fresh value, so
       comparing the job's current started_at against the value we were
       handed at claim time detects "someone else now owns this job" even
       across processes. claim_token=None (a non-replica-aware caller, or a
       job started before Step 4 shipped) skips this half of the check —
       cancellation is still honored either way.
    """
    try:
        if claim_token is None:
            return bool(await pool.fetchval("SELECT status = 'canceled' FROM jobs WHERE id = $1", job_id))
        return bool(await pool.fetchval(
            "SELECT status = 'canceled' OR started_at IS DISTINCT FROM $2 FROM jobs WHERE id = $1",
            job_id, claim_token,
        ))
    except Exception:
        return False  # a DB hiccup here must never halt a legitimate job


# ═══════════════════════════════════════════════════════════════
#  PHASE 1 — GOOGLE MAPS SCRAPING
# ═══════════════════════════════════════════════════════════════
async def _scroll_to_end(page):
    """Improved scroll — waits longer and checks for end more reliably."""
    prev = 0
    stable_count = 0
    max_stable = 8  # more attempts before giving up

    while True:
        # Scroll feed
        await page.evaluate("""
            () => {
                const f = document.querySelector('div[role="feed"]');
                if (f) { f.scrollTop = f.scrollHeight; f.scrollBy(0, 5000); }
            }
        """)
        await asyncio.sleep(1.5)  # more wait time

        cur = await page.locator('div[role="feed"] > div > div[jsaction]').count()
        html = await page.content()

        if "You've reached the end" in html or "end of the list" in html:
            # Extra scroll to load any final items
            for _ in range(3):
                await page.evaluate('() => { const f = document.querySelector(\'div[role="feed"]\'); if (f) f.scrollTop = f.scrollHeight; }')
                await asyncio.sleep(1.0)
            return

        if cur == prev:
            stable_count += 1
            if stable_count >= max_stable:
                # Final push
                for _ in range(4):
                    await page.evaluate('() => { const f = document.querySelector(\'div[role="feed"]\'); if (f) f.scrollTop = f.scrollHeight; }')
                    await asyncio.sleep(2.0)
                return
        else:
            stable_count = 0
        prev = cur


async def _scrape_city(city, state, industry, browser, out_dir, pool, job_id):
    query    = f"{industry} in {city}, {state}"
    out_file = out_dir / f"{sanitize(city)}_{state}.csv"

    await _update_city(pool, job_id, city, maps_status="running", maps_started_at="NOW()")

    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    )
    page = await context.new_page()
    await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,ico,mp4,mp3}", lambda r: r.abort())

    results = []
    try:
        url = "https://www.google.com/maps/search/" + query.replace(" ", "+")
        await page.goto(url, timeout=45000, wait_until="domcontentloaded")
        await asyncio.sleep(3)  # more initial wait

        try:
            btn = page.locator('button:has-text("Accept all")').first
            if await btn.is_visible(timeout=2000):
                await btn.click(); await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        try:
            await page.wait_for_selector('div[role="feed"]', timeout=20000)
            await asyncio.sleep(2)  # wait for feed to fully render
        except Exception:
            title = await page.title()
            log.warning(f"[job {job_id[:8]}] feed not found for {city}, title={title}")
            await context.close()
            await _update_city(pool, job_id, city, maps_status="done", maps_leads=0)
            return []

        title     = await page.title()
        card_count = await page.locator('div[role="feed"] > div > div[jsaction]').count()
        log.info(f"[job {job_id[:8]}] {city}: title={title}, cards_before_scroll={card_count}")

        await _scroll_to_end(page)

        # Extra wait after scroll to ensure all cards loaded
        await asyncio.sleep(2)
        data = await page.evaluate(_EXTRACT_JS)

        for r in (data or []):
            if not r.get("name"): continue
            results.append({
                "Name":     r["name"],
                "Category": r.get("category", ""),
                "Rating":   r.get("rating", ""),
                "Reviews":  r.get("reviews", ""),
                "Address":  clean_address(r.get("address", "")),
                "Phone":    format_phone(r.get("phone", "")),
                "Email":    "",
                "Website":  r.get("website", ""),
                "Maps_URL": r.get("maps_url", ""),
            })

        log.info(f"[job {job_id[:8]}] {city}: found {len(results)} results")

        if results:
            fields = ["Name","Category","Rating","Reviews","Address","Phone","Email","Website","Maps_URL"]
            with open(out_file, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader(); w.writerows(results)

    except Exception as e:
        log.error(f"[job {job_id[:8]}] error scraping {city}: {e}")
        await _update_city(pool, job_id, city, maps_status="failed", error=str(e)[:200])
        return []
    finally:
        try: await context.close()
        except asyncio.CancelledError: raise
        except Exception: pass

    await _update_city(pool, job_id, city, maps_status="done",
                       maps_leads=len(results), maps_done_at="NOW()")
    return results


# ═══════════════════════════════════════════════════════════════
#  PREPROCESS
# ═══════════════════════════════════════════════════════════════
FINAL_BUSINESS_COLS = [
    "Name", "Category", "City", "Rating", "Reviews", "Address",
    "Phone", "Phone 2", "Email", "Website", "Website 2", "Maps_URL",
    "Times_Found", "Found_In_Cities",
]


def _merge_duplicate_businesses(df: pd.DataFrame) -> pd.DataFrame:
    """Collapses rows that are the same real-world business into one, using
    Phone and/or Website as identity (NOT Name -- the same business re-listed
    under a different name must still merge). Two rows are connected if they
    share any non-empty, normalized Phone or Website value; connections are
    transitive (union-find), so a 3-row chain merges into one business even if
    no two of the three rows directly share a value with each other.

    Checks BOTH the primary and the " 2" column (if present) when building
    connections -- this makes the function safe to call a second time on data
    that's already been through one merge pass (see run_scrape_job's Phase 2
    call site), correctly catching matches that only became visible after
    enrichment filled in a previously-blank Phone/Website.

    The merged row keeps the first-found row's other fields (Name/Category/
    City/Rating/Reviews/Address/Maps_URL/Email) and aggregates Times_Found/
    Found_In_Cities across every row in the group. Up to 2 distinct phones and
    2 distinct websites survive (Phone/Phone 2, Website/Website 2); a 3rd+
    distinct value is dropped. Rows with neither a phone nor a website can't
    be matched to anything and pass through unmerged."""
    if df.empty:
        return df

    df = df.reset_index(drop=True)
    n = len(df)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    def _row_pairs(idx, primary_col, secondary_col, normalize):
        """(raw, normalized) for every non-empty value in idx's primary/secondary
        column -- checking BOTH is what makes this function safe to call again on
        data that already carries a " 2" value from an earlier merge pass."""
        pairs = []
        for col in (primary_col, secondary_col):
            if col in df.columns:
                raw = str(df.at[idx, col] or "").strip()
                if raw:
                    pairs.append((raw, normalize(raw)))
        return pairs

    groups: dict[tuple[str, str], list[int]] = {}
    for idx in range(n):
        for _, norm in _row_pairs(idx, "Phone", "Phone 2", lambda p: p):
            groups.setdefault(("phone", norm), []).append(idx)
        for _, norm in _row_pairs(idx, "Website", "Website 2", normalize_website):
            groups.setdefault(("website", norm), []).append(idx)

    for members in groups.values():
        for idx in members[1:]:
            union(members[0], idx)

    components: dict[int, list[int]] = {}
    for idx in range(n):
        components.setdefault(find(idx), []).append(idx)

    def _distinct_values(indices, primary_col, secondary_col, normalize):
        """Up to all distinct values (by normalized form) across every member
        row's primary AND secondary column, first-seen order, original text kept."""
        out, seen = [], set()
        for i in indices:
            for raw, norm in _row_pairs(i, primary_col, secondary_col, normalize):
                if norm not in seen:
                    seen.add(norm)
                    out.append(raw)
        return out

    merged_rows = []
    for indices in components.values():
        base = df.loc[indices[0]].to_dict()

        # Aggregate from BOTH a plain City value and any pre-existing
        # Found_In_Cities list -- a member row may itself already be the
        # output of an earlier merge pass, in which case its real city history
        # lives in Found_In_Cities, not its (single, first-found) City field.
        if "City" in df.columns or "Found_In_Cities" in df.columns:
            cities = set()
            for i in indices:
                if "Found_In_Cities" in df.columns:
                    existing = str(df.at[i, "Found_In_Cities"] or "").strip()
                    if existing:
                        cities.update(c.strip() for c in existing.split(",") if c.strip())
                if "City" in df.columns:
                    c = str(df.at[i, "City"] or "").strip()
                    if c:
                        cities.add(c)
            base["Found_In_Cities"] = ", ".join(sorted(cities))

        # Sum rather than count indices -- a member row may already represent
        # several original rows merged in an earlier pass (its own Times_Found).
        if "Times_Found" in df.columns:
            base["Times_Found"] = sum(
                int(df.at[i, "Times_Found"]) if str(df.at[i, "Times_Found"]).strip() else 1
                for i in indices
            )
        else:
            base["Times_Found"] = len(indices)

        phones = _distinct_values(indices, "Phone", "Phone 2", lambda p: p)
        base["Phone"]   = phones[0] if len(phones) > 0 else ""
        base["Phone 2"] = phones[1] if len(phones) > 1 else ""

        websites = _distinct_values(indices, "Website", "Website 2", normalize_website)
        base["Website"]   = websites[0] if len(websites) > 0 else ""
        base["Website 2"] = websites[1] if len(websites) > 1 else ""

        merged_rows.append(base)

    result = pd.DataFrame(merged_rows)
    result = result[[c for c in FINAL_BUSINESS_COLS if c in result.columns]]
    sort_cols = [c for c in ["City", "Name"] if c in result.columns]
    if sort_cols:
        result = result.sort_values(sort_cols).reset_index(drop=True)
    return result


def _preprocess(folder_path: Path, state: str, industry: str):
    import glob
    all_files = glob.glob(str(folder_path / "*.csv"))
    if not all_files:
        return pd.DataFrame(), pd.DataFrame()

    df_list = []
    for f in all_files:
        try:
            df = pd.read_csv(f, encoding="latin1")
            if "City" not in df.columns:
                df["City"] = Path(f).stem.replace(f"_{state}", "").replace("_", " ")
            df_list.append(df)
        except Exception:
            continue

    if not df_list:
        return pd.DataFrame(), pd.DataFrame()

    merged = pd.concat(df_list, ignore_index=True)
    cols = ["Name","Category","City","Rating","Reviews","Address","Phone","Email","Website","Maps_URL"]
    merged = merged[[c for c in cols if c in merged.columns]]
    merged = merged.loc[:, ~merged.columns.str.contains("^Unnamed")].dropna(how="all")
    for col in merged.columns:
        merged[col] = merged[col].fillna("").astype(str).str.strip()
    if "Phone"   in merged.columns: merged["Phone"]   = merged["Phone"].apply(format_phone)
    if "Address" in merged.columns: merged["Address"] = merged["Address"].apply(clean_address)

    merged = _merge_duplicate_businesses(merged)

    no_web   = merged[merged["Website"] == ""].copy()
    with_web = merged[merged["Website"] != ""].copy()
    return with_web, no_web


# ═══════════════════════════════════════════════════════════════
#  PHASE 2 — DETAIL PAGE ENRICHMENT
# ═══════════════════════════════════════════════════════════════
async def _enrich_missing(records: list, pool: asyncpg.Pool, job_id: str, claim_token=None) -> list:
    missing = [r for r in records if
               (not str(r.get("Website","")).strip() or not str(r.get("Phone","")).strip())
               and str(r.get("Maps_URL","")).strip()]

    if not missing:
        log.info(f"[job {job_id[:8]}] no missing data - skipping detail enrichment")
        return records

    log.info(f"[job {job_id[:8]}] detail enrichment: {len(missing)} businesses")
    total = len(missing)
    done  = [0]

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True, slow_mo=0)
        # try/finally guarantees browser.close() runs even if this is cancelled
        # externally (watchdog rescuing a stuck job) — without it, cancellation
        # skips straight past the close() below and leaks a live Chrome process
        # (not a zombie — tini can't reap something that's still running).
        try:
            sem = asyncio.Semaphore(MAX_CONCURRENT_DETAIL)

            async def fetch_one(row):
                async with sem:
                    if await _is_job_canceled(pool, job_id, claim_token):
                        return
                    ctx = await browser.new_context(
                        viewport={"width": 1280, "height": 900},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                    )
                    page = await ctx.new_page()
                    try:
                        await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,ico,mp4,mp3}", lambda r: r.abort())
                        await page.goto(row["Maps_URL"], timeout=int(MAPS_DETAIL_TIMEOUT * 1000), wait_until="domcontentloaded")
                        await asyncio.sleep(0.5)
                        data = await page.evaluate(_DETAIL_JS)
                        if data.get("website") and not str(row.get("Website","")).strip():
                            row["Website"] = data["website"]
                        if data.get("phone") and not str(row.get("Phone","")).strip():
                            row["Phone"] = format_phone(data["phone"])
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        pass
                    finally:
                        try: await page.close()
                        except asyncio.CancelledError: raise
                        except Exception: pass
                        try: await ctx.close()
                        except asyncio.CancelledError: raise
                        except Exception: pass
                        # Checkpoint updated_at periodically — without this, a batch large
                        # enough to take >5min at MAX_CONCURRENT_DETAIL looks "stuck" to the
                        # watchdog (worker/main.py) and gets killed + retried even though it's
                        # still legitimately working. Mirrors the Phase 3 email-crawl pattern.
                        done[0] += 1
                        if done[0] % 10 == 0 or done[0] == total:
                            enriched_so_far = sum(1 for r in records if str(r.get("Website","")).strip())
                            try:
                                await _update_job(pool, job_id, with_website=enriched_so_far)
                            except Exception as e:
                                log.error(f"[job {job_id[:8]}] DB update error: {e}")

            await asyncio.gather(*[fetch_one(r) for r in missing], return_exceptions=True)
        finally:
            try: await browser.close()
            except asyncio.CancelledError: raise
            except Exception: pass

    enriched_web = sum(1 for r in records if str(r.get("Website","")).strip())
    log.info(f"[job {job_id[:8]}] after enrichment: {enriched_web} with website")
    await _update_job(pool, job_id, with_website=enriched_web)
    return records


# ═══════════════════════════════════════════════════════════════
#  PHASE 3 — EMAIL SCRAPING
# ═══════════════════════════════════════════════════════════════
async def _extract_emails_from_page(page, is_homepage=False):
    found = set()
    try:
        if is_homepage:
            try:
                await page.wait_for_selector(
                    "footer, #footer, .footer, [class*='footer'], [id*='footer']",
                    timeout=FOOTER_WAIT_MS, state="attached"
                )
                await asyncio.sleep(1.2)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(0.8)
        else:
            await asyncio.sleep(0.8)

        mailtos = await page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href^=\"mailto:\"]')).map(a => a.getAttribute('href'))"
        )
        for m in mailtos:
            email = m.replace("mailto:", "").split("?")[0].strip()
            if is_valid_email(email): found.add(clean_email(email))

        try:
            header_text = await page.evaluate("""
                () => {
                    const h = document.querySelector('header, #header, .header, [class*="header"], nav');
                    return h ? h.innerText : '';
                }
            """)
            for e in EMAIL_REGEX.findall(header_text or ""):
                if is_valid_email(e): found.add(clean_email(e))
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        try:
            footer_text = await page.evaluate("""
                () => {
                    const f = document.querySelector('footer, #footer, .footer, [class*="footer"]');
                    return f ? f.innerText : '';
                }
            """)
            for e in EMAIL_REGEX.findall(footer_text or ""):
                if is_valid_email(e): found.add(clean_email(e))
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        body_text = await page.inner_text("body")
        clean_html = re.sub(r"<(script|style|noscript)[^>]*>[\s\S]*?</\1>", "", await page.content(), flags=re.IGNORECASE)
        for e in EMAIL_REGEX.findall(body_text + " " + clean_html):
            if is_valid_email(e): found.add(clean_email(e))

        decoded = body_text.replace("[at]","@").replace("[dot]",".").replace(" at ","@").replace(" dot ",".")
        for e in EMAIL_REGEX.findall(decoded):
            if is_valid_email(e): found.add(clean_email(e))

    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    return found


async def _crawl_site_for_email(ctx, start_url):
    if not start_url or not start_url.startswith(("http://", "https://")):
        return ""

    base_url   = start_url.rstrip("/")
    visited    = set()
    all_emails = set()
    FREE = {"gmail.com","yahoo.com","hotmail.com","outlook.com","aol.com","mail.com"}

    def has_business_email(emails):
        site_domain = urlparse(start_url).netloc.replace("www.", "")
        for e in emails:
            domain = e.split("@")[-1].lower()
            if domain not in FREE and domain == site_domain: return True
        return False

    async def visit(url, is_hp=False):
        if url in visited: return set()
        visited.add(url)
        page = await ctx.new_page()
        try:
            await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,ico,mp4,mp3}", lambda r: r.abort())
            await page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            })
            await page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
            return await _extract_emails_from_page(page, is_homepage=is_hp)
        except asyncio.CancelledError:
            raise
        except Exception:
            return set()
        finally:
            try: await page.close()
            except Exception:
                pass

    for i, path in enumerate(PRIORITY_PATHS):
        url = urljoin(base_url + "/", path.lstrip("/")) if path else start_url
        emails = await visit(url, is_hp=(i == 0))
        all_emails.update(emails)
        if has_business_email(all_emails): break

    return select_best_email(all_emails, start_url) if all_emails else ""


async def _add_emails(df: pd.DataFrame, pool: asyncpg.Pool, job_id: str, claim_token=None) -> pd.DataFrame:
    """
    Email scraping using a small BROWSER POOL shared across many contexts.
    Launch EMAIL_BROWSER_POOL_SIZE browsers once and reuse them across all
    sites; run up to MAX_CONCURRENT_EMAIL crawls at a time, each in its own
    fresh context assigned round-robin to a pooled browser. Decoupling the
    two (2026-09-10) keeps the process/thread count low — a full browser is
    ~100 pids, an extra context only ~30 — while still crawling several sites
    in parallel. Also avoids forking hundreds of Chrome processes over a long
    job (the original BlockingIOError fix).
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_EMAIL)
    total     = len(df)
    done      = [0]
    records   = df.to_dict("records")

    async with async_playwright() as p:
        # ── Launch browser pool once ──
        browsers = []
        for _ in range(EMAIL_BROWSER_POOL_SIZE):
            try:
                b = await p.chromium.launch(
                    channel="chrome",
                    headless=True,
                    slow_mo=0,
                    args=[
                        "--ignore-certificate-errors",
                        "--ignore-ssl-errors",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                browsers.append(b)
            except Exception as e:
                log.error(f"[job {job_id[:8]}] browser launch failed: {e}")

        if not browsers:
            # Every browser in the pool failed to even launch — a replica
            # resource problem, not a job problem. Used to silently return the
            # untouched records (every "Email" left blank, job completes
            # looking like a clean run that just found nothing) — raise
            # loudly instead, matching Phase 1's same-class fix, so this
            # doesn't spend the job's retry budget and doesn't masquerade as
            # a real empty result.
            raise ReplicaResourceError(
                f"Phase 3 (email crawl) could not launch any of its "
                f"{EMAIL_BROWSER_POOL_SIZE} browsers"
            )

        log.info(f"[job {job_id[:8]}] email browser pool: {len(browsers)} browsers ready")

        # ── Everything from here on is wrapped in try/finally: without it, an
        # external cancellation (the watchdog rescuing a stuck job, or a future
        # cancel path) skips straight past "Close all browsers" below and leaks
        # every browser in the pool as a genuinely still-running orphaned
        # process — not a zombie, so 2026-09-13's tini fix does nothing for
        # this. Confirmed as a real incident: a stuck job's cancelled task left
        # its browser(s) running, and the next job's Phase 1 browser launch
        # then failed instantly with "Target page, context or browser has been
        # closed" on every single city, completing as "done" with 0 leads.
        try:
            # Round-robin browser assignment
            browser_idx = [0]
            browser_lock = asyncio.Lock()

            async def get_browser():
                async with browser_lock:
                    b = browsers[browser_idx[0] % len(browsers)]
                    browser_idx[0] += 1
                    return b

            # ── Whole-pool self-healing ── a long job (many hours, thousands of
            # sites) can outlive its browsers: if BOTH pooled browsers die at once
            # (observed live: "Browser.new_context: Target page, context or
            # browser has been closed" on every single subsequent attempt), the
            # per-item retry loop below only ever launches one-off replacement
            # browsers per failure, appended to an ever-growing list — it never
            # actually confirms the pool is healthy again, so once truly dead it
            # stayed dead for the rest of the run: thousands of sites each burned
            # a full 3-attempt/2s+4s-backoff retry against a permanently-broken
            # pool for hours, finding nothing, while still counting as "attempted"
            # (2026-09-15 incident: two ~14h jobs each lost most of their real
            # Phase 3 time this way, finishing with a tiny fraction of the emails
            # a healthy run would have found). Track consecutive total failures
            # across ALL concurrent items; past a threshold, tear down and
            # relaunch the whole pool once instead of leaving it for dead.
            consecutive_failures = [0]
            pool_relaunches = [0]
            pool_dead = [False]
            relaunch_lock = asyncio.Lock()
            CONSECUTIVE_FAILURE_THRESHOLD = 12
            MAX_POOL_RELAUNCHES = 3

            async def relaunch_pool():
                async with relaunch_lock:
                    if consecutive_failures[0] < CONSECUTIVE_FAILURE_THRESHOLD or pool_dead[0]:
                        return  # another task already handled this batch of failures
                    if pool_relaunches[0] >= MAX_POOL_RELAUNCHES:
                        pool_dead[0] = True
                        log.error(f"[job {job_id[:8]}] email browser pool unrecoverable after "
                                  f"{pool_relaunches[0]} relaunch attempts — skipping remaining sites")
                        return
                    pool_relaunches[0] += 1
                    log.warning(f"[job {job_id[:8]}] email browser pool appears dead "
                                f"({consecutive_failures[0]} consecutive failures) — "
                                f"relaunching (attempt {pool_relaunches[0]}/{MAX_POOL_RELAUNCHES})")
                    async with browser_lock:
                        dead = browsers[:]
                        browsers.clear()
                        for _ in range(EMAIL_BROWSER_POOL_SIZE):
                            try:
                                b = await p.chromium.launch(
                                    channel="chrome", headless=True, slow_mo=0,
                                    args=["--ignore-certificate-errors", "--ignore-ssl-errors",
                                          "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
                                )
                                browsers.append(b)
                            except Exception as e:
                                log.error(f"[job {job_id[:8]}] pool relaunch: browser launch failed: {e}")
                        browser_idx[0] = 0
                    for b in dead:
                        try: await b.close()
                        except Exception: pass
                    consecutive_failures[0] = 0
                    if not browsers:
                        pool_dead[0] = True
                        log.error(f"[job {job_id[:8]}] email browser pool relaunch produced no browsers")

            async def process_one(row):
                if not str(row.get("Website", "")).strip():
                    return
                # Checked before the semaphore (and before entering the try/finally
                # below that counts done[0]/emails_attempted): once cancelled, every
                # already-queued item behind the semaphore gets to run near-instantly
                # (no real work, just this check), which raced emails_attempted to
                # 503/503 on a job that only genuinely tried ~40 sites before the
                # user cancelled it. Checking here means a skipped item is never
                # counted as "attempted" at all, and skips don't even wait for a slot.
                if await _is_job_canceled(pool, job_id, claim_token):
                    return
                # Same reasoning as the cancellation check above: once the pool is
                # confirmed dead, skip instantly (not counted as "attempted" — an
                # honest signal that Phase 3 didn't really run, rather than
                # emails_attempted misleadingly reaching 100% on a pool that found
                # nothing) instead of burning a guaranteed-to-fail 3-attempt retry
                # (up to ~18s of backoff) on every remaining site.
                if pool_dead[0]:
                    return
                row["Email"] = ""
                ctx = None
                try:
                    async with semaphore:
                        # Getting a working browser context can transiently fail
                        # under real resource pressure (Chrome spawn EAGAIN, or a
                        # pooled browser that just died) — this used to make
                        # exactly one immediate retry attempt and, if that also
                        # failed (likely — the pressure that just killed one
                        # launch rarely clears within milliseconds), permanently
                        # gave up on that site with no email. That silently
                        # zeroed out real, findable emails on sites that were
                        # never actually visited. Retry with backoff instead.
                        last_err = None
                        for attempt in range(3):
                            if attempt > 0:
                                await asyncio.sleep(2 * attempt)  # 2s, 4s
                            browser = await get_browser()
                            try:
                                ctx = await browser.new_context(
                                    viewport={"width": 1280, "height": 900},
                                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                                )
                                last_err = None
                                break
                            except Exception as e:
                                last_err = e
                                # Pooled browser is dead — launch a fresh one for
                                # the next attempt (also covered by the same
                                # retry/backoff, unlike the old one-shot fallback).
                                try:
                                    new_b = await p.chromium.launch(
                                        channel="chrome", headless=True, slow_mo=0,
                                        args=["--ignore-certificate-errors","--ignore-ssl-errors",
                                              "--no-sandbox","--disable-dev-shm-usage","--disable-gpu"],
                                    )
                                    browsers.append(new_b)
                                except Exception:
                                    pass  # next loop iteration just retries get_browser() again

                        if ctx is None:
                            log.error(f"[job {job_id[:8]}] browser recovery failed after retries: {last_err}")
                            consecutive_failures[0] += 1
                            if consecutive_failures[0] >= CONSECUTIVE_FAILURE_THRESHOLD:
                                await relaunch_pool()
                            # (no done[0] += 1 here — the finally block below always
                            # does it on every exit path, including this return; a
                            # second increment here double-counted every dead-pool
                            # failure, which is what actually produced
                            # emails_attempted > with_website on real jobs, not a
                            # duplicate job run as first suspected.)
                            return

                        row["Email"] = await asyncio.wait_for(
                            _crawl_site_for_email(ctx, row["Website"]),
                            timeout=EMAIL_CRAWL_TIMEOUT,
                        )
                        # Only reset on a genuinely completed crawl — resetting right
                        # after context creation succeeded (the old behavior) missed
                        # a real failure mode: the context opens fine but the shared
                        # browser underneath it is already silently broken, so every
                        # actual crawl attempted on it fails instantly. Confirmed
                        # live: hundreds of ZeroDivisionErrors (from Playwright's own
                        # connection handling, not this file — there is no division
                        # anywhere in this file's email-crawl path) landed within the
                        # same second at the tail of a job, while this counter stayed
                        # at 0 the whole time because it kept getting reset before
                        # the crawl was ever attempted, so the pool never relaunched.
                        consecutive_failures[0] = 0
                except asyncio.TimeoutError:
                    log.warning(f"[job {job_id[:8]}] email timeout: {row.get('Website')}")
                    consecutive_failures[0] += 1
                    if consecutive_failures[0] >= CONSECUTIVE_FAILURE_THRESHOLD:
                        await relaunch_pool()
                except Exception as e:
                    # exc_info=True (was just the type name) -- if this recurs, the
                    # next occurrence gets a full traceback instead of another
                    # guessing game.
                    log.warning(f"[job {job_id[:8]}] email error: {type(e).__name__}", exc_info=True)
                    consecutive_failures[0] += 1
                    if consecutive_failures[0] >= CONSECUTIVE_FAILURE_THRESHOLD:
                        await relaunch_pool()
                finally:
                    if ctx:
                        try: await ctx.close()
                        except asyncio.CancelledError: raise
                        except Exception: pass
                    done[0] += 1
                    # Write progress on every completion, not every 10 — at low
                    # concurrency with a per-site budget up to EMAIL_CRAWL_TIMEOUT,
                    # a batch of 10 has no real headroom against the watchdog's
                    # stuck threshold: a real run once hit a 5m13s gap between two
                    # every-10 writes (mostly successful-but-slow page loads, not
                    # even all timeouts) and got wrongly killed as "stalled" while
                    # still actively working. Writing every item removes that risk
                    # at negligible cost (one cheap UPDATE per ~10-30s per slot).
                    found = sum(1 for r in records if r.get("Email"))
                    if done[0] % 10 == 0 or done[0] == total:
                        log.info(f"[job {job_id[:8]}] email progress: {done[0]}/{total} | found: {found}")
                    try:
                        await _update_job(pool, job_id,
                                          emails_attempted=done[0],
                                          emails_found=found)
                    except Exception as e:
                        log.error(f"[job {job_id[:8]}] DB update error: {e}")

            async def safe_process(r):
                try:
                    await process_one(r)
                except Exception as e:
                    log.error(f"[job {job_id[:8]}] task error: {e}")

            await asyncio.gather(
                *[safe_process(r) for r in records if str(r.get("Website","")).strip()],
                return_exceptions=True,
            )
        finally:
            # Close all browsers — guaranteed to run even if the above was
            # cancelled externally (see comment above the try).
            for b in browsers:
                try: await b.close()
                except asyncio.CancelledError: raise
                except Exception: pass

    return pd.DataFrame(records)


# ═══════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════
async def run_scrape_job(
    *,
    job_id: str,
    user_id: str,
    industry: str,
    state: str,
    cities: list[str],
    include_emails: bool,
    pool: asyncpg.Pool,
    upload_fn,
    download_fn,
    delete_fn,
    claim_token=None,
) -> dict:
    # ── Resumable checkpoints ──
    # Phase 1 (Maps) and Phase 2 (enrichment) can each take 20-60+ minutes. Previously,
    # any retry — auto (watchdog) or manual — threw all of that away and restarted at
    # Phase 1, even if the job had actually gotten as far as Phase 3 (email crawl)
    # before being killed. We now durably save the lead records found so far right
    # after each phase finishes; on (re)entry here we check for the most advanced
    # checkpoint that exists and skip straight past whatever it already covers.
    checkpoint_maps_path   = f"{user_id}/{job_id}/_checkpoint_maps.json"
    checkpoint_enrich_path = f"{user_id}/{job_id}/_checkpoint_enrich.json"

    def _split_by_website(df: pd.DataFrame):
        if df.empty:
            return df.copy(), df.copy()
        with_web = df[df["Website"].astype(str).str.strip() != ""].copy()
        no_web   = df[df["Website"].astype(str).str.strip() == ""].copy()
        return with_web, no_web

    async def _load_checkpoint(path: str):
        try:
            raw = await download_fn(path)
        except Exception as e:
            log.warning(f"[job {job_id[:8]}] checkpoint read failed for {path}, ignoring: {e}")
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return data["total_raw"], pd.DataFrame(data["records"])
        except Exception as e:
            log.error(f"[job {job_id[:8]}] checkpoint at {path} unreadable, ignoring: {e}")
            return None

    async def _save_checkpoint(path: str, total_raw_val: int, df: pd.DataFrame):
        # default=str covers non-JSON-native dtypes (e.g. Times_Found is a numpy int)
        payload = json.dumps({"total_raw": total_raw_val, "records": df.to_dict("records")},
                             default=str).encode("utf-8")
        try:
            await upload_fn(payload, path)
        except Exception as e:
            log.error(f"[job {job_id[:8]}] failed to save checkpoint at {path}: {e}")

    async def _backfill_progress_from(df: pd.DataFrame):
        """Resume shortcut: mark every city + the job's Phase-1 counters as already
        done, computed from a loaded checkpoint, so the UI reflects reality
        immediately instead of sitting at 0/N while a later phase runs."""
        per_city = df.groupby("City").size().to_dict() if ("City" in df.columns and not df.empty) else {}
        for city in cities:
            await _update_city(pool, job_id, city, maps_status="done",
                               maps_leads=per_city.get(city, 0), maps_done_at="NOW()")
        await _update_job(pool, job_id, cities_done=len(cities), maps_done_at="NOW()")

    resumed_enrich = await _load_checkpoint(checkpoint_enrich_path)
    resumed_maps   = None if resumed_enrich else await _load_checkpoint(checkpoint_maps_path)

    start_step = "step3_emails" if resumed_enrich else ("step2_enrich" if resumed_maps else "step1_maps")
    if claim_token is None:
        # No fencing token supplied (a non-replica-aware caller, e.g. a test, or
        # the pre-Step-4 single-instance path) — stamp started_at here ourselves,
        # same as before Step 4.
        await _update_job(pool, job_id,
                          status="running", started_at="NOW()",
                          current_step=start_step, cities_total=len(cities))
    else:
        # The poll loop's atomic claim already stamped started_at = claim_token
        # in the same transaction that flipped this job to 'running' — re-setting
        # it here would invalidate the very fencing token we were just handed,
        # before this job even does any work.
        await _update_job(pool, job_id,
                          status="running",
                          current_step=start_step, cities_total=len(cities))

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)

        if resumed_enrich:
            total_raw, all_df = resumed_enrich
            with_web_df, no_web_df = _split_by_website(all_df)
            total_clean = len(with_web_df) + len(no_web_df)
            log.info(f"[job {job_id[:8]}] resuming from enrichment checkpoint — "
                    f"skipping Maps + enrichment ({total_clean} leads already found)")
            await _backfill_progress_from(all_df)
            await _update_job(pool, job_id,
                              total_raw=total_raw, total_clean=total_clean,
                              with_website=len(with_web_df), no_website=len(no_web_df),
                              duplicates_removed=max(total_raw - total_clean, 0))

        else:
            if resumed_maps:
                total_raw, merged = resumed_maps
                log.info(f"[job {job_id[:8]}] resuming from Maps checkpoint — "
                        f"skipping Maps scrape ({len(merged)} leads already found)")
                await _backfill_progress_from(merged)
            else:
                # ── PHASE 1: Google Maps ──
                # Concurrent across cities (MAX_CONCURRENT_CITIES), same
                # semaphore+gather shape as Phase 2/Phase 3 — was a strict
                # one-city-at-a-time for-loop, the biggest sequential bottleneck
                # in the whole pipeline for large multi-city jobs. One shared
                # browser, one fresh context per city (mirrors Phase 2's
                # single-browser/multi-context design) — _scrape_city already
                # closes its own context, so no extra cleanup needed here.
                async with async_playwright() as p:
                    try:
                        browser = await p.chromium.launch(channel="chrome", headless=True, slow_mo=0)
                    except Exception as e:
                        # Can't even get the first browser up — a replica
                        # resource problem, not a job problem (see
                        # ReplicaResourceError). Nothing to clean up yet.
                        raise ReplicaResourceError(f"Phase 1 (Google Maps) could not launch its browser: {e}")
                    browser_ref = [browser]  # mutable — relaunch_browser() below swaps this out
                    # try/finally guarantees browser.close() runs even if this is
                    # cancelled externally (watchdog rescuing a stuck job) —
                    # without it, cancellation skips straight past the close()
                    # below and leaks a live Chrome process (not a zombie — tini
                    # can't reap something that's still running). Confirmed as a
                    # real incident: a stuck job's cancelled task left its Phase 1
                    # browser running, and the next job's own browser launch then
                    # failed instantly on every single city.
                    try:
                        city_sem = asyncio.Semaphore(MAX_CONCURRENT_CITIES)
                        raw_total  = [0]
                        done_total = [0]

                        # ── Whole-browser self-healing ── Phase 1 shares ONE
                        # browser across every city (unlike Phase 3's pool). If it
                        # dies mid-job — observed live: "Target page, context or
                        # browser has been closed" cascading across dozens of
                        # cities within seconds — every remaining city failed
                        # instantly, but since each per-city failure is caught
                        # individually, the job still "completed" with 100% cities
                        # done and zero real leads (2026-09-18 incident). Track
                        # consecutive city failures; past a threshold, relaunch the
                        # browser. If it still won't recover after a few tries,
                        # fail the job loudly instead of completing with
                        # fabricated-looking empty results — unlike Phase 3, there
                        # is no earlier-phase data worth salvaging from a dead
                        # Phase 1.
                        consecutive_failures = [0]
                        browser_relaunches   = [0]
                        phase1_dead          = [False]
                        relaunch_lock = asyncio.Lock()
                        CONSECUTIVE_FAILURE_THRESHOLD = 8
                        MAX_BROWSER_RELAUNCHES = 3

                        async def relaunch_browser():
                            async with relaunch_lock:
                                if consecutive_failures[0] < CONSECUTIVE_FAILURE_THRESHOLD or phase1_dead[0]:
                                    return  # another concurrent city already handled this batch
                                if browser_relaunches[0] >= MAX_BROWSER_RELAUNCHES:
                                    phase1_dead[0] = True
                                    log.error(f"[job {job_id[:8]}] Phase 1 browser unrecoverable after "
                                              f"{browser_relaunches[0]} relaunch attempts — stopping Maps scrape")
                                    return
                                browser_relaunches[0] += 1
                                log.warning(f"[job {job_id[:8]}] Phase 1 browser appears dead "
                                            f"({consecutive_failures[0]} consecutive city failures) — "
                                            f"relaunching (attempt {browser_relaunches[0]}/{MAX_BROWSER_RELAUNCHES})")
                                old = browser_ref[0]
                                try:
                                    browser_ref[0] = await p.chromium.launch(channel="chrome", headless=True, slow_mo=0)
                                except Exception as e:
                                    log.error(f"[job {job_id[:8]}] Phase 1 browser relaunch failed: {e}")
                                    return
                                try:
                                    await old.close()
                                except Exception:
                                    pass
                                consecutive_failures[0] = 0

                        async def scrape_one_city(city):
                            async with city_sem:
                                if await _is_job_canceled(pool, job_id, claim_token):
                                    return
                                # Same reasoning as Phase 3's pool_dead skip: once
                                # the browser is confirmed unrecoverable, skip
                                # instantly rather than trying and failing again,
                                # and don't count this city as attempted.
                                if phase1_dead[0]:
                                    return
                                await _update_job(pool, job_id, current_city=city)
                                try:
                                    rows = await asyncio.wait_for(
                                        _scrape_city(city, state, industry, browser_ref[0], out_dir, pool, job_id),
                                        timeout=CITY_SCRAPE_TIMEOUT_S,
                                    )
                                    consecutive_failures[0] = 0
                                except asyncio.CancelledError:
                                    raise
                                except asyncio.TimeoutError:
                                    log.error(f"[job {job_id[:8]}] {city} scrape timed out after {CITY_SCRAPE_TIMEOUT_S}s")
                                    await _update_city(pool, job_id, city, maps_status="failed", error="City scrape timed out")
                                    rows = []
                                    consecutive_failures[0] += 1
                                except Exception as e:
                                    log.error(f"[job {job_id[:8]}] unexpected error scraping {city}: {e}")
                                    await _update_city(pool, job_id, city, maps_status="failed", error=str(e)[:200])
                                    rows = []
                                    consecutive_failures[0] += 1

                                if consecutive_failures[0] >= CONSECUTIVE_FAILURE_THRESHOLD:
                                    await relaunch_browser()

                                # Update progress on every completion (not batched) —
                                # same reasoning as Phase 2/3: with several cities
                                # in flight at once, batching would let the watchdog
                                # see a long gap with zero DB writes and misfire.
                                raw_total[0]  += len(rows)
                                done_total[0] += 1
                                await _update_job(pool, job_id, cities_done=done_total[0], total_raw=raw_total[0])

                        await asyncio.gather(*[scrape_one_city(city) for city in cities],
                                            return_exceptions=True)
                        if phase1_dead[0]:
                            raise ReplicaResourceError(
                                f"Phase 1 (Google Maps) browser became unrecoverable after "
                                f"{MAX_BROWSER_RELAUNCHES} relaunch attempts"
                            )
                        total_raw = raw_total[0]
                    finally:
                        try: await browser_ref[0].close()
                        except asyncio.CancelledError: raise
                        except Exception: pass

                await _update_job(pool, job_id, current_step="step2_preprocess", maps_done_at="NOW()")

                # ── PREPROCESS ──
                with_web_df, no_web_df = _preprocess(out_dir, state, industry)
                merged = pd.concat([with_web_df, no_web_df], ignore_index=True)

                # Checkpoint: Maps scrape + merge/dedupe is durably saved — a retry
                # from here on will skip straight back to this point instead of
                # re-scraping every city from zero.
                await _save_checkpoint(checkpoint_maps_path, total_raw, merged)

            with_web_df, no_web_df = _split_by_website(merged)
            total_clean = len(merged)
            await _update_job(pool, job_id,
                              current_step="step2_preprocess",
                              total_raw=total_raw, total_clean=total_clean,
                              with_website=len(with_web_df), no_website=len(no_web_df),
                              duplicates_removed=max(total_raw - total_clean, 0))

            # ── PHASE 2: Detail Enrichment ──
            if not no_web_df.empty or (not with_web_df.empty and with_web_df["Phone"].eq("").any()):
                await _update_job(pool, job_id, current_step="step2_enrich")
                all_records = pd.concat([with_web_df, no_web_df], ignore_index=True).to_dict("records")
                all_records = await _enrich_missing(all_records, pool, job_id, claim_token)
                all_df      = pd.DataFrame(all_records)
                # Catches matches enrichment just discovered -- two rows with no
                # phone/website at Phase 1 can end up sharing one after this step
                # fills in a previously-blank field. Safe to re-run: it checks both
                # the primary and " 2" columns, so nothing from the first pass is
                # lost or double-counted.
                all_df      = _merge_duplicate_businesses(all_df)
                with_web_df, no_web_df = _split_by_website(all_df)
                total_clean = len(all_df)
                await _update_job(pool, job_id,
                                  total_clean=total_clean,
                                  with_website=len(with_web_df),
                                  no_website=len(no_web_df),
                                  duplicates_removed=max(total_raw - total_clean, 0))

            # Checkpoint: enrichment is done (or wasn't needed) — a retry from here
            # on will skip Maps AND enrichment and go straight to email scraping.
            await _save_checkpoint(checkpoint_enrich_path, total_raw,
                                   pd.concat([with_web_df, no_web_df], ignore_index=True))

        # ── PHASE 3: Email Scraping ──
        if include_emails and not with_web_df.empty:
            await _update_job(pool, job_id, current_step="step3_emails", emails_started_at="NOW()")
            with_web_df = await _add_emails(with_web_df, pool, job_id, claim_token)
            await _update_job(pool, job_id, emails_done_at="NOW()")

        # ── Cancellation guard ── a user's cancel request only ever flips the
        # DB row (see _is_job_canceled) — check it one last time here before
        # this function would otherwise overwrite that with status="done" and
        # upload whatever partial results exist. The per-item checks above
        # stop new work quickly, but this is the backstop for the case where
        # cancellation lands after the last item already finished.
        if await _is_job_canceled(pool, job_id, claim_token):
            log.info(f"[job {job_id[:8]}] canceled or reclaimed by another replica — stopping without uploading or marking done")
            return {
                "total_raw": total_raw, "total_clean": total_clean,
                "with_website": len(with_web_df), "no_website": len(no_web_df),
                "emails_found": 0, "canceled": True,
            }

        # ── UPLOAD CSVs ──
        # "With website" is split into two deliverables (email found / not found)
        # instead of one combined file -- with_web_csv itself is deliberately left
        # unset on new jobs; it's legacy, still serving only jobs completed before
        # this split shipped (see migrations/0013_split_with_website_by_email.sql).
        with_web_email_path    = f"{user_id}/{job_id}/with_website_with_email.csv"
        with_web_no_email_path = f"{user_id}/{job_id}/with_website_without_email.csv"
        no_web_path             = f"{user_id}/{job_id}/no_website.csv"

        def df_to_bytes(df: pd.DataFrame) -> bytes:
            # Times_Found/Found_In_Cities stay in the working dataframes -- the
            # merge logic itself relies on them (see _merge_duplicate_businesses,
            # called a second time after Phase 2 enrichment, which aggregates
            # counts/cities from the first pass). Only hidden from the delivered
            # CSV, not removed from tracking.
            buf = io.StringIO()
            df.drop(columns=["Times_Found", "Found_In_Cities"], errors="ignore").to_csv(buf, index=False, encoding="utf-8")
            return buf.getvalue().encode("utf-8")

        if with_web_df.empty:
            with_email_df, without_email_df = with_web_df, with_web_df
        else:
            has_email = with_web_df["Email"].astype(str).str.strip().ne("")
            with_email_df, without_email_df = with_web_df[has_email].copy(), with_web_df[~has_email].copy()

        await upload_fn(df_to_bytes(with_email_df),    with_web_email_path)
        await upload_fn(df_to_bytes(without_email_df), with_web_no_email_path)
        await upload_fn(df_to_bytes(no_web_df),        no_web_path)

        emails_found = len(with_email_df)

        await _update_job(pool, job_id,
                          status="done",
                          current_step="complete",
                          emails_found=emails_found,
                          with_web_email_csv=with_web_email_path,
                          with_web_no_email_csv=with_web_no_email_path,
                          no_web_csv=no_web_path,
                          completed_at="NOW()")

        # Checkpoints are only useful mid-flight — clean up now that the job
        # succeeded (best-effort; a leftover file here is harmless clutter, not a
        # correctness problem, since no future job ever reuses this job_id's path).
        for cp_path in (checkpoint_maps_path, checkpoint_enrich_path):
            try:
                await delete_fn(cp_path)
            except Exception as e:
                log.warning(f"[job {job_id[:8]}] checkpoint cleanup failed for {cp_path}: {e}")

        return {
            "total_raw":    total_raw,
            "total_clean":  total_clean,
            "with_website": len(with_web_df),
            "no_website":   len(no_web_df),
            "emails_found": emails_found,
            "canceled":     False,
        }
