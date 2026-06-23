"""
Intelligent Scraper — Job Runner
Based on best working local scrap.py logic.
Maps scraping uses minimal flags (same as local).
Email scraping uses full Docker flags.
"""

import asyncio
from datetime import datetime, timezone
import csv
import io
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import asyncpg
import pandas as pd
from playwright.async_api import async_playwright

# ═══════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════
MAX_CONCURRENT_SITES = 5
PAGE_TIMEOUT_MS      = 12000
FOOTER_WAIT_MS       = 3000
EMAIL_CRAWL_TIMEOUT  = 30.0

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

# Minimal flags for Maps scraping (same as local — avoids DOM rendering differences)
MAPS_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
]

# Full flags for email scraping (Docker safe)
EMAIL_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-first-run",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
    "--mute-audio",
]


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


# ═══════════════════════════════════════════════════════════════
#  STEP 1 — GOOGLE MAPS SCRAPING
# ═══════════════════════════════════════════════════════════════
async def _scroll_to_end(page):
    prev = 0; stable_count = 0
    while True:
        await page.evaluate("""
            () => {
                const f = document.querySelector('div[role="feed"]');
                if (f) { f.scrollTop = f.scrollHeight; f.scrollBy(0, 3000); }
            }
        """)
        await asyncio.sleep(1.2)
        cur = await page.locator('div[role="feed"] > div > div[jsaction]').count()
        html = await page.content()
        if "You've reached the end" in html or "end of the list" in html:
            for _ in range(2):
                await page.evaluate('() => { const f = document.querySelector(\'div[role="feed"]\'); if (f) f.scrollTop = f.scrollHeight; }')
                await asyncio.sleep(1.0)
            return await page.locator('div[role="feed"] > div > div[jsaction]').count()
        if cur == prev:
            stable_count += 1
            if stable_count >= 6:
                for _ in range(3):
                    await page.evaluate('() => { const f = document.querySelector(\'div[role="feed"]\'); if (f) f.scrollTop = f.scrollHeight; }')
                    await asyncio.sleep(1.5)
                final = await page.locator('div[role="feed"] > div > div[jsaction]').count()
                return final
        else:
            stable_count = 0; prev = cur


async def _extract_cards(page):
    """Exact same JS logic as working local scrap.py extract_all_at_once."""
    data = await page.evaluate("""
        () => {
            const phoneRegex = /(\\(?\\d{3}\\)?[\\s\\-\\.]?\\d{3}[\\s\\-\\.]?\\d{4})/;
            const addressKeywords = [' St',' St,',' Ave',' Ave,',' Rd',' Rd,',' Blvd',' Dr',' Dr,',' Ln',' Ln,',' Way',' Ct',' Ct,',' Pl',' Pl,',' Hwy',' Pkwy',' Suite',' #',' Ste'];
            function looksLikeAddress(txt) {
                if (!txt || txt.length < 5) return false;
                return /\\d/.test(txt) && addressKeywords.some(kw => txt.includes(kw));
            }
            function looksLikePhone(txt) {
                if (!txt) return false;
                const m = txt.match(phoneRegex);
                return m ? m[0] : null;
            }
            function isJunk(txt) {
                if (!txt) return true;
                const lower = txt.toLowerCase();
                return /open|closed|hours|^\\d+(\\.\\d)?\\s*\\(/.test(lower) || txt.length < 5;
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

                const catEl = card.querySelector('.W4Efsd .W4Efsd span');
                if (catEl) row.category = catEl.innerText.trim();

                const ratingEl = card.querySelector('.MW4etd');
                if (ratingEl) row.rating = ratingEl.innerText.trim();

                const revEl = card.querySelector('.UY7F9');
                if (revEl) row.reviews = revEl.innerText.replace(/[()]/g,'').trim();

                const webEl = card.querySelector('a[data-value="Website"]');
                if (webEl) row.website = webEl.href || '';

                const mapsEl = card.querySelector('a.hfpxzc');
                if (mapsEl) row.maps_url = mapsEl.href || '';

                card.querySelectorAll('[aria-label]').forEach(el => {
                    const label = (el.getAttribute('aria-label') || '').trim();
                    if (/^Address[:\\s]/i.test(label) && !row.address) {
                        const addr = label.replace(/^Address[:\\s]*/i,'').trim();
                        if (!isJunk(addr)) row.address = addr;
                    }
                    if (/^Phone[:\\s]/i.test(label) && !row.phone) {
                        row.phone = label.replace(/^Phone[:\\s]*/i,'').trim();
                    }
                });

                if (!row.address) {
                    const addrEl = card.querySelector('[data-item-id="address"]');
                    if (addrEl) {
                        const txt = addrEl.getAttribute('aria-label') || addrEl.innerText || '';
                        const clean = txt.replace(/^Address[:\\s]*/i,'').trim();
                        if (looksLikeAddress(clean)) row.address = clean;
                    }
                }

                if (!row.phone) {
                    const telEl = card.querySelector('a[href^="tel:"]');
                    if (telEl) row.phone = telEl.href.replace('tel:','').trim();
                }

                if (!row.address) {
                    const spans = card.querySelectorAll('.W4Efsd > span, .W4Efsd > div');
                    for (const span of spans) {
                        const txt = span.innerText.split('\\n')[0].trim();
                        if (looksLikeAddress(txt) && !isJunk(txt)) { row.address = txt; break; }
                    }
                }

                if (!row.phone) {
                    const spans = card.querySelectorAll('.W4Efsd span, .W4Efsd div');
                    for (const span of spans) {
                        const txt = span.innerText.split('\\n')[0].trim();
                        const ph = looksLikePhone(txt);
                        if (ph && txt.replace(/[\\d\\s\\-\\(\\)\\+]/g,'').length < 3) { row.phone = ph; break; }
                    }
                }

                results.push(row);
            });
            return results;
        }
    """)
    rows = []
    for r in data:
        if not r.get("name"): continue
        rows.append({
            "Name": r["name"], "Category": r.get("category", ""),
            "Rating": r.get("rating", ""), "Reviews": r.get("reviews", ""),
            "Address": clean_address(r.get("address", "")),
            "Phone": format_phone(r.get("phone", "")),
            "Email": "", "Website": r.get("website", ""), "Maps_URL": r.get("maps_url", ""),
        })
    return rows


async def _scrape_city(city, state, industry, browser, out_dir, pool, job_id):
    query = f"{industry} in {city}, {state}"
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
        await asyncio.sleep(2)

        try:
            btn = page.locator('button:has-text("Accept all")').first
            if await btn.is_visible(timeout=2000):
                await btn.click(); await asyncio.sleep(0.5)
        except: pass

        try:
            await page.wait_for_selector('div[role="feed"]', timeout=15000)
        except Exception as e:
            title = await page.title()
            print(f"[RUNNER] Feed not found for {city}. Title: {title}")
            await context.close()
            await _update_city(pool, job_id, city, maps_status="done", maps_leads=0)
            return []

        title = await page.title()
        card_count = await page.locator('div[role="feed"] > div > div[jsaction]').count()
        print(f"[RUNNER] {city}: title={title}, cards_before_scroll={card_count}")

        await _scroll_to_end(page)
        results = await _extract_cards(page)
        print(f"[RUNNER] {city}: found {len(results)} results")

        if results:
            fields = ["Name","Category","Rating","Reviews","Address","Phone","Email","Website","Maps_URL"]
            with open(out_file, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader(); w.writerows(results)

    except Exception as e:
        print(f"[RUNNER] Error scraping {city}: {e}")
        await _update_city(pool, job_id, city, maps_status="failed", error=str(e)[:200])
        return []
    finally:
        await context.close()

    await _update_city(pool, job_id, city, maps_status="done",
                       maps_leads=len(results), maps_done_at="NOW()")
    return results


# ═══════════════════════════════════════════════════════════════
#  STEP 2 — PREPROCESS
# ═══════════════════════════════════════════════════════════════
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

    name_cities = merged.groupby("Name")["City"].apply(
        lambda x: ", ".join(sorted(set(c.strip() for c in x if c.strip())))
    ).to_dict()
    name_count = merged.groupby("Name")["Name"].count().to_dict()
    merged["Times_Found"]     = merged["Name"].map(lambda n: name_count.get(n, 1))
    merged["Found_In_Cities"] = merged["Name"].map(lambda n: name_cities.get(n, ""))

    has_phone = merged[merged["Phone"] != ""].copy()
    no_phone  = merged[merged["Phone"] == ""].copy()
    has_phone = has_phone.drop_duplicates(subset=["Name","Phone"], keep="first")
    merged    = pd.concat([has_phone, no_phone], ignore_index=True).sort_values(["City","Name"]).reset_index(drop=True)

    no_web   = merged[merged["Website"] == ""].copy()
    with_web = merged[merged["Website"] != ""].copy()
    return with_web, no_web


# ═══════════════════════════════════════════════════════════════
#  STEP 3 — EMAIL SCRAPING
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
            except:
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
                    const h = document.querySelector('header, #header, .header, [class*="header"], [id*="header"], nav, .navbar');
                    return h ? h.innerText : '';
                }
            """)
            for e in EMAIL_REGEX.findall(header_text):
                if is_valid_email(e): found.add(clean_email(e))
        except: pass

        try:
            footer_text = await page.evaluate("""
                () => {
                    const f = document.querySelector('footer, #footer, .footer, [class*="footer"], [id*="footer"]');
                    return f ? f.innerText : '';
                }
            """)
            for e in EMAIL_REGEX.findall(footer_text):
                if is_valid_email(e): found.add(clean_email(e))
        except: pass

        body_text = await page.inner_text("body")
        clean_html = re.sub(r"<(script|style|noscript)[^>]*>[\s\S]*?</\1>", "", await page.content(), flags=re.IGNORECASE)
        for e in EMAIL_REGEX.findall(body_text + " " + clean_html):
            if is_valid_email(e): found.add(clean_email(e))

        decoded = body_text.replace("[at]","@").replace("[dot]",".").replace(" at ","@").replace(" dot ",".")
        for e in EMAIL_REGEX.findall(decoded):
            if is_valid_email(e): found.add(clean_email(e))

    except: pass
    return found


async def _crawl_site_for_email(context, start_url):
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
        page = await context.new_page()
        try:
            await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,ico,mp4,mp3}", lambda r: r.abort())
            await page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            })
            await page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
            return await _extract_emails_from_page(page, is_homepage=is_hp)
        except:
            return set()
        finally:
            try: await page.close()
            except: pass

    for i, path in enumerate(PRIORITY_PATHS):
        url = urljoin(base_url + "/", path.lstrip("/")) if path else start_url
        emails = await visit(url, is_hp=(i == 0))
        all_emails.update(emails)
        if has_business_email(all_emails): break

    return select_best_email(all_emails, start_url) if all_emails else ""


async def _add_emails(df: pd.DataFrame, pool: asyncpg.Pool, job_id: str) -> pd.DataFrame:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SITES)
    total   = len(df)
    done    = [0]
    records = df.to_dict("records")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            slow_mo=0,
            args=EMAIL_CHROMIUM_ARGS,
        )

        async def process_one(row):
            if not str(row.get("Website", "")).strip(): return
            async with semaphore:
                ctx = await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                )
                try:
                    row["Email"] = await asyncio.wait_for(
                        _crawl_site_for_email(ctx, row["Website"]),
                        timeout=EMAIL_CRAWL_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    print(f"[RUNNER] Timeout: {row.get('Website')}")
                    row["Email"] = ""
                except Exception as e:
                    print(f"[RUNNER] Email error: {e}")
                    row["Email"] = ""
                finally:
                    try: await ctx.close()
                    except: pass

                done[0] += 1
                if done[0] % 10 == 0 or done[0] == total:
                    found = sum(1 for r in records if r.get("Email"))
                    print(f"[RUNNER] Email progress: {done[0]}/{total} | found: {found}")
                    await _update_job(pool, job_id,
                                      emails_attempted=done[0],
                                      emails_found=found)

        await asyncio.gather(*[process_one(r) for r in records if str(r.get("Website","")).strip()])
        await browser.close()

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
) -> dict:
    await _update_job(pool, job_id,
                      status="running",
                      started_at="NOW()",
                      current_step="step1_maps",
                      cities_total=len(cities))

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)

        # ── STEP 1: Google Maps (minimal flags — same as local) ──
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                slow_mo=0,
                args=MAPS_CHROMIUM_ARGS,
            )
            total_raw = 0
            for i, city in enumerate(cities):
                await _update_job(pool, job_id, current_city=city, cities_done=i)
                rows = await _scrape_city(city, state, industry, browser, out_dir, pool, job_id)
                total_raw += len(rows)
                await _update_job(pool, job_id, cities_done=i + 1, total_raw=total_raw)
            await browser.close()

        await _update_job(pool, job_id, current_step="step2_preprocess", maps_done_at="NOW()")

        # ── STEP 2: Preprocess ──
        with_web_df, no_web_df = _preprocess(out_dir, state, industry)
        total_clean      = len(with_web_df) + len(no_web_df)
        with_website_cnt = len(with_web_df)
        no_website_cnt   = len(no_web_df)
        duplicates       = total_raw - total_clean

        await _update_job(pool, job_id,
                          total_clean=total_clean,
                          with_website=with_website_cnt,
                          no_website=no_website_cnt,
                          duplicates_removed=max(duplicates, 0))

        # ── STEP 3: Email scraping ──
        if include_emails and not with_web_df.empty:
            await _update_job(pool, job_id, current_step="step3_emails", emails_started_at="NOW()")
            with_web_df = await _add_emails(with_web_df, pool, job_id)
            await _update_job(pool, job_id, emails_done_at="NOW()")

        # ── UPLOAD CSVs ──
        with_web_path = f"{user_id}/{job_id}/with_website.csv"
        no_web_path   = f"{user_id}/{job_id}/no_website.csv"

        def df_to_bytes(df: pd.DataFrame) -> bytes:
            buf = io.StringIO()
            df.to_csv(buf, index=False, encoding="utf-8")
            return buf.getvalue().encode("utf-8")

        await upload_fn(df_to_bytes(with_web_df), with_web_path)
        await upload_fn(df_to_bytes(no_web_df),   no_web_path)

        emails_found = int(with_web_df["Email"].astype(str).str.strip().ne("").sum()) if not with_web_df.empty else 0

        await _update_job(pool, job_id,
                          status="done",
                          current_step="complete",
                          emails_found=emails_found,
                          with_web_csv=with_web_path,
                          no_web_csv=no_web_path,
                          completed_at="NOW()")

        return {
            "total_raw":    total_raw,
            "total_clean":  total_clean,
            "with_website": with_website_cnt,
            "no_website":   no_website_cnt,
            "emails_found": emails_found,
        }
