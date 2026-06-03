"""
Scraper for public rankings pages.

Three fetch strategies, by site:
  - WSOP standings    → direct JSON API (clean, fast, no browser needed).
  - The Hendon Mob    → headed browser via undetected-chromedriver (see below).
  - Everything else   → curl_cffi HTTP fetch + LLM table parsing.

Getting past The Hendon Mob's Cloudflare challenge
--------------------------------------------------
The Hendon Mob's data lives on `pokerdb.thehendonmob.com`, which sits behind
Cloudflare's "Just a moment..." managed challenge. The first response isn't the
page — it's a small HTML page carrying obfuscated JavaScript that probes the
client and only issues a `cf_clearance` cookie (unlocking the real content) if
the client looks like a genuine browser. There is no API or unprotected route;
every path on that subdomain is challenged.

Why the obvious approaches fail:
  - Plain HTTP (requests / curl_cffi) never runs the JS, so it can't complete
    the challenge — it gets 403/429 no matter how the TLS handshake is faked.
  - Headless automation (headless Chrome, Playwright) *does* run the JS but is
    flagged by the challenge's fingerprinting: `navigator.webdriver`, ChromeDriver
    artifacts (cdc_ vars), and the distinct headless-Chrome fingerprint.

What works: `undetected-chromedriver` (Selenium with patches that strip those
automation tells) run *headed*. To the challenge's JS it looks like an ordinary
human-driven Chrome, so the check passes on its own and the clearance cookie is
issued. We are not breaking anything — we are passing the check legitimately by
not looking like a bot. After it clears once, the cookie persists in the browser
session, so reusing a single driver across pages/profiles means Cloudflare only
challenges us on the first load (~8s) and later loads are fast.

Caveats for maintainers:
  - It's an arms race. A Cloudflare detection update or a uc/Chrome version bump
    can break this overnight; treat it as more fragile than the WSOP API path.
  - Headed-only here. Headless gets flagged for this site, so it needs a visible
    browser — on a headless server you'd need a virtual display (e.g. xvfb).
  - Don't hammer it. Too-fast / high-volume traffic can make Cloudflare escalate
    from the passive managed challenge to an interactive Turnstile/CAPTCHA, which
    uc cannot silently solve. The `delay` / `profile_delay` pauses exist to stay
    under that threshold — keep them.
"""

import json
import random
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _jittered_delay(base, spread=0.5):
    """
    Randomize a politeness pause so request timing doesn't look botlike.

    A fixed gap between requests is itself a tell Cloudflare's heuristics key
    on, and regular cadence is part of what escalates the passive challenge to
    an interactive one. Returns a value uniformly in [base - spread, base + spread],
    clamped at 0 — so the default base=1.0 / spread=0.5 yields pauses in
    [0.5, 1.5]s. Bump `base` to widen the whole window.
    """
    return max(0.0, random.uniform(base - spread, base + spread))


def scrape_leaderboard(url, us_only=True, months_active=12, max_players=50, openai_api_key=None):
    """
    Scrape a public rankings page and return enriched player records.

    Each record: {rank, name, country, metric, city_state, last_active_year, profile_url}
    """
    # WSOP standings pages have a direct JSON API — no scraping or LLM needed
    if "wsop.com/player-standings/" in url:
        return _scrape_wsop_standings(url, us_only=us_only, max_players=max_players)

    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for non-WSOP URLs")

    html = _fetch(url)
    players = _parse_rankings(html, url, openai_api_key)

    if us_only:
        players = [p for p in players if _is_us(p.get("country", ""))]

    players = players[:max_players]

    for i, player in enumerate(players):
        if player.get("profile_url"):
            try:
                profile_html = _fetch(player["profile_url"])
                soup = BeautifulSoup(profile_html, "html.parser")
                player["city_state"] = _extract_location(soup)
                player["last_active_year"] = _extract_last_year(soup)
            except Exception:
                pass
        if i < len(players) - 1:
            time.sleep(0.2)

    if months_active:
        cutoff_year = (datetime.now() - timedelta(days=months_active * 30)).year
        players = [p for p in players if _is_recently_active(p.get("last_active_year"), cutoff_year)]

    return players


# ---------------------------------------------------------------------------
# The Hendon Mob All Time Money List (paginated, direct parse, no LLM)
# ---------------------------------------------------------------------------

ALL_TIME_MONEY_LIST_URL = "https://pokerdb.thehendonmob.com/ranking/all-time-money-list/"


def split_ranking_page(url):
    """
    Split a ranking URL into (base_without_trailing_page, page_or_None).

    Hendon Mob paginates as `<ranking>/<n>`, e.g. `.../all-time-money-list/3`
    or `.../ranking/194/2`. A single numeric segment (`.../ranking/194`) is a
    ranking id, not a page, so it's left on the base.
    """
    base = url.rstrip("/")
    m = re.search(r"/ranking/(.+)$", base)
    if m:
        parts = m.group(1).split("/")
        if len(parts) >= 2 and parts[-1].isdigit():
            return base[: -(len(parts[-1]) + 1)], int(parts[-1])
    return base, None


def scrape_money_list(url=ALL_TIME_MONEY_LIST_URL, start_page=None, num_pages=1, delay=1.0,
                      fetch_profiles=False, profile_delay=1.0, country=None):
    """
    Scrape a Hendon Mob ranking list, one shot, for a small page range.

    The list lives behind Cloudflare, so this drives one headed browser session
    (the challenge is solved once and reused for every page). Each page holds 100
    players in a `table--ranking-list` table; pages are `<url>/2`, `<url>/3`, ...

    For the full multi-day harvest use scraper.harvest (CLI) instead — this is the
    interactive, bounded path.

    Args:
        url: ranking page URL. If it already ends in a page number (e.g.
            `.../all-time-money-list/3`) that page is used as the start.
        start_page: page to start at when `url` has no trailing page (default 1).
        num_pages: how many consecutive pages to scrape from the start.
        delay: seconds to pause between page loads.
        fetch_profiles: if True, visit each player's profile page (reusing the
            same browser) to fill `city_state` and `profiles` (social links).
        profile_delay: seconds to pause between profile visits.
        country: if set, keep only players from this country. Applied before the
            profile phase so non-matching profiles aren't visited.

    Returns:
        List of {rank, name, country, earnings, profile_url, city_state, profiles} dicts.
    """
    driver = _new_undetected_driver()
    if driver is None:
        raise RuntimeError("undetected-chromedriver is required to scrape The Hendon Mob")

    base, url_page = split_ranking_page(url)
    # A page number in the URL wins; otherwise use start_page (default 1).
    start = url_page if url_page else (int(start_page) if start_page else 1)
    last = start + max(1, int(num_pages)) - 1

    players = []
    try:
        page = start
        while page <= last:
            page_url = base + "/" if page == 1 else f"{base}/{page}"
            html = _load_via_driver(driver, page_url, ready_marker="table--ranking-list")
            if not html:
                break
            batch, has_next = _parse_money_list_page(html, page_url)
            if not batch:
                break
            players.extend(batch)
            if not has_next:
                break
            page += 1
            time.sleep(delay)

        if country:
            players = [p for p in players if p.get("country") == country]

        if fetch_profiles:
            for p in players:
                if not p.get("profile_url"):
                    continue
                # profiles always have a results table; wait on that to know the
                # challenge cleared, then parse the (optional) location + socials.
                prof_html = _load_via_driver(driver, p["profile_url"], ready_marker="<table")
                if prof_html:
                    city_state, profiles, last_cash_date, recent_earnings = _parse_profile_details(
                        prof_html, p["profile_url"], p.get("country", "")
                    )
                    p["city_state"] = city_state
                    p["profiles"] = profiles
                    p["last_cash_date"] = last_cash_date
                    p["recent_earnings"] = recent_earnings
                time.sleep(_jittered_delay(profile_delay))
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return players


# Player-profile social menu links use class `menu_<platform>`; these are the
# platforms we treat as social media (vs. menu_graphs, menu_g, etc.).
_PROFILE_SOCIAL_PLATFORMS = ("twitter", "facebook", "instagram", "youtube", "tiktok", "twitch")


def _parse_player_results(soup):
    """
    From a profile's results table → (last_cash_date, recent_earnings_usd).

    last_cash_date is the ISO date (YYYY-MM-DD) of the player's most recent
    recorded tournament cash — the "is this player still active?" signal.
    recent_earnings_usd is their total USD winnings over the trailing 12 months,
    formatted like the all-time earnings column ("$ 1,234,567"). Both are ""
    when the table has no parseable results.

    The results table (`table--player-results`) lists one cash per row, newest
    first; `td.date` holds e.g. "20-May-2026" and the USD-normalised prize is the
    `td.currency` cell containing "$" (a second cell holds the local currency).
    """
    table = soup.find("table", class_="table--player-results")
    if not table:
        return "", ""

    cutoff = datetime.utcnow() - timedelta(days=365)
    dates = []
    recent_total = 0.0
    for tr in table.find_all("tr"):
        date_cell = tr.find("td", class_="date")
        if not date_cell:
            continue  # header / spacer row
        try:
            dt = datetime.strptime(date_cell.get_text(strip=True), "%d-%b-%Y")
        except ValueError:
            continue
        dates.append(dt)
        if dt >= cutoff:
            for cur in tr.find_all("td", class_="currency"):
                txt = cur.get_text(strip=True).replace("\xa0", " ")
                if "$" in txt:
                    digits = re.sub(r"[^\d.]", "", txt)
                    if digits:
                        try:
                            recent_total += float(digits)
                        except ValueError:
                            pass
                    break

    if not dates:
        return "", ""
    return max(dates).strftime("%Y-%m-%d"), f"$ {recent_total:,.0f}"


def _parse_profile_details(html, profile_url, country=""):
    """
    Parse a player profile page → (city_state, profiles, last_cash_date, recent_earnings).

    city_state comes from the profile's Residence (falling back to Born) field;
    the trailing country is trimmed since country has its own column. Social
    links are the player's `menu_<platform>` links, returned as absolute Hendon
    Mob URLs (the site routes them through its own /<platform>/<slug> redirect).
    last_cash_date / recent_earnings come from the results table (see
    _parse_player_results) and signal recency + recent value.
    """
    soup = BeautifulSoup(html, "html.parser")

    city_state = ""
    loc = soup.find("div", class_="player-profile-location")
    if loc:
        labels = loc.find_all("span", class_="player-profile-location__entry-label")
        values = loc.find_all("span", class_="player-profile-location__entry-value")
        pairs = {}
        for label, value in zip(labels, values):
            text_wrap = value.find("span", class_="text-wrap")
            text = (text_wrap.get_text(strip=True) if text_wrap
                    else value.get_text(" ", strip=True))
            pairs[label.get_text(strip=True).rstrip(":").lower()] = text
        city_state = pairs.get("residence") or pairs.get("born") or ""
        if country and city_state.endswith(", " + country):
            city_state = city_state[: -len(", " + country)]

    profiles = {}
    for a in soup.find_all("a", href=True):
        classes = a.get("class") or []
        for platform in _PROFILE_SOCIAL_PLATFORMS:
            if f"menu_{platform}" in classes:
                profiles[platform] = urljoin(profile_url, a["href"])

    last_cash_date, recent_earnings = _parse_player_results(soup)
    return city_state, profiles, last_cash_date, recent_earnings


def _parse_money_list_page(html, page_url):
    """Parse one money-list page → (list of player dicts, has_next_page bool)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="table--ranking-list")
    players = []
    if table:
        for tr in table.find_all("tr"):
            place = tr.find("td", class_="place")
            name_cell = tr.find("td", class_="name")
            if not place or not name_cell:
                continue  # header / non-player row
            link = name_cell.find("a", href=True)
            name = (link.get_text(strip=True) if link else name_cell.get_text(strip=True))
            profile_url = urljoin(page_url, link["href"]) if link else None

            flag = tr.find("td", class_="flag")
            span = flag.find("span") if flag else None
            country = (span.get("title") or span.get_text(strip=True)) if span else ""

            prize = tr.find("td", class_="prize")
            earnings = prize.get_text(strip=True).replace("\xa0", " ") if prize else ""

            rank_digits = re.sub(r"\D", "", place.get_text())
            players.append({
                "rank": int(rank_digits) if rank_digits else None,
                "name": name,
                "country": country,
                "earnings": earnings,
                "profile_url": profile_url,
                "city_state": "",
                "profiles": {},
                "last_cash_date": "",
                "recent_earnings": "",
            })

    has_next = any(
        a.get_text(strip=True).lower() == "next" for a in soup.find_all("a", href=True)
    )
    return players, has_next


# ---------------------------------------------------------------------------
# WSOP direct API
# ---------------------------------------------------------------------------

_WSOP_HEADERS = {
    "Referer": "https://www.wsop.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


def _wsop_accolade_type(url):
    """Extract accolade slug from a WSOP player-standings URL."""
    m = re.search(r"player-standings/([^/?#]+)", url)
    return m.group(1).rstrip("/") if m else "all-time-earnings-men"


def _scrape_wsop_standings(url, us_only=True, max_players=200):
    from curl_cffi import requests as cffi_requests

    accolade = _wsop_accolade_type(url)
    country_param = "&country=US" if us_only else ""
    api_base = f"https://www.wsop.com/api/standings?type={accolade}{country_param}"

    players = []
    offset = 0
    page_size = 50

    while len(players) < max_players:
        r = cffi_requests.get(
            f"{api_base}&offset={offset}&limit={page_size}",
            impersonate="chrome120",
            timeout=15,
            headers=_WSOP_HEADERS,
        )
        if r.status_code != 200:
            break
        data = r.json()
        batch = data.get("dataList", [])
        if not batch:
            break

        for item in batch:
            info = item.get("playerInfo", {})
            slug = info.get("playerNameSlug", "")
            country_code = info.get("playerCountry", "")
            earnings = item.get("earnings", 0)

            # Determine metric label based on accolade type
            if "earnings" in accolade:
                metric = f"${earnings:,.0f}" if earnings else ""
            elif "bracelet" in accolade:
                metric = f"{item.get('bracelets', '')} bracelets"
            elif "ring" in accolade:
                metric = f"{item.get('rings', '')} rings"
            else:
                metric = str(earnings) if earnings else ""

            # playerNameFixed can be a slug string; playerName is always human-readable
            name = info.get("playerName") or info.get("playerNameFixed", "")
            players.append({
                "rank": item.get("rank"),
                "name": name,
                "country": _country_code_to_name(country_code),
                "metric": metric,
                "profile_url": f"https://www.wsop.com/players/{slug}/" if slug else None,
                "city_state": "",
                "last_active_year": None,
            })

        offset += page_size
        if offset >= data.get("totalCount", 0):
            break
        time.sleep(0.15)

    # The WSOP country filter is by registered account, not displayed nationality.
    # Post-filter on the playerCountry field to ensure accuracy.
    if us_only:
        players = [p for p in players if p["country"] == "United States"]

    return players[:max_players]


def _country_code_to_name(code):
    """Map common 2-letter country codes to full names."""
    _MAP = {
        "US": "United States", "CA": "Canada", "GB": "United Kingdom",
        "AU": "Australia", "DE": "Germany", "FR": "France", "ES": "Spain",
        "IT": "Italy", "BR": "Brazil", "MX": "Mexico", "RU": "Russia",
        "CN": "China", "JP": "Japan", "KR": "South Korea", "PH": "Philippines",
        "IL": "Israel", "AT": "Austria", "SE": "Sweden", "NL": "Netherlands",
        "BE": "Belgium", "PT": "Portugal", "PL": "Poland", "HU": "Hungary",
        "CZ": "Czech Republic", "DK": "Denmark", "NO": "Norway", "FI": "Finland",
        "CH": "Switzerland", "LT": "Lithuania", "LV": "Latvia", "EE": "Estonia",
        "UA": "Ukraine", "RO": "Romania", "BG": "Bulgaria", "GR": "Greece",
        "TR": "Turkey", "ZA": "South Africa", "NG": "Nigeria", "EG": "Egypt",
        "IN": "India", "TH": "Thailand", "SG": "Singapore", "MY": "Malaysia",
        "NZ": "New Zealand", "AR": "Argentina", "CO": "Colombia", "CL": "Chile",
        "PE": "Peru", "VE": "Venezuela", "UY": "Uruguay", "BY": "Belarus",
        "HK": "Hong Kong", "TW": "Taiwan",
    }
    return _MAP.get(code.upper(), code) if code else ""


# ---------------------------------------------------------------------------
# Generic HTML scraper (non-WSOP)
# ---------------------------------------------------------------------------

def _fetch(url):
    """Fetch using curl_cffi (Chrome TLS). Falls back to a real browser for JS-heavy pages."""
    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, impersonate="chrome120", timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.find("table"):
                return r.text
    except Exception:
        pass
    # Some sites (e.g. The Hendon Mob's pokerdb subdomain) sit behind a
    # Cloudflare "Just a moment" JS challenge that blocks both plain HTTP and
    # headless automation. undetected-chromedriver run *headed* clears it;
    # headless Chrome and Playwright get flagged, so they're only a last resort.
    html = _fetch_undetected(url)
    if html:
        return html
    return _fetch_playwright(url)


def _chrome_major_version():
    """Major version of the installed Chrome, so uc fetches a matching driver. None → uc autodetects."""
    import subprocess
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome", "google-chrome-stable", "chromium-browser", "chromium",
    ]
    for path in candidates:
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"\b(\d+)\.\d+", out)
            if m:
                return int(m.group(1))
        except Exception:
            continue
    return None


def _new_undetected_driver():
    """Create a headed undetected-chromedriver instance, or None if uc is unavailable."""
    try:
        import undetected_chromedriver as uc
    except Exception:
        return None
    try:
        return uc.Chrome(options=uc.ChromeOptions(), headless=False,
                         version_main=_chrome_major_version())
    except Exception:
        return None


def _load_via_driver(driver, url, ready_marker="<table", wait_secs=30,
                     challenge_wait_secs=0, challenge_refresh_secs=30,
                     on_challenge=None):
    """
    Navigate an existing uc driver to url and wait out any Cloudflare challenge.

    Returns the page HTML once the "Just a moment" interstitial clears and
    `ready_marker` appears, or None if it never resolves. Reusing one driver
    across calls means Cloudflare is solved once and the session is kept warm.

    Normally waits up to `wait_secs` for the page to render. If the "Just a
    moment" interstitial is *still* up at that point and `challenge_wait_secs`
    > 0, keeps waiting up to that many extra seconds before giving up —
    Cloudflare's managed challenge occasionally stalls for many minutes — and
    re-navigates to the URL every `challenge_refresh_secs` to nudge it into
    re-evaluating. `on_challenge(elapsed_secs)` is called when the long wait
    first kicks in and again on each nudge, so callers can report it. Callers
    that can't afford a long stall (the roster walk) leave the default 0 and
    keep the old fast-fail behaviour.
    """
    try:
        driver.get(url)
    except Exception:
        return None
    started = time.time()
    last_refresh = started
    long_wait_started = None
    while True:
        try:
            src = driver.page_source
        except Exception:
            return None
        low = src.lower()
        challenged = "just a moment" in low
        if not challenged and ready_marker.lower() in low:
            return src

        now = time.time()
        if now - started < wait_secs:
            time.sleep(1)
            continue

        # Past the normal window. Only keep going if we're genuinely stuck on
        # the Cloudflare interstitial and a long-challenge budget was granted;
        # otherwise this is just an empty/slow page — fail fast as before.
        if not (challenged and challenge_wait_secs > 0):
            return None
        if long_wait_started is None:
            long_wait_started = now
            last_refresh = now  # measure the refresh interval from the stall, not page load
            if on_challenge:
                on_challenge(0)
        if now - long_wait_started > challenge_wait_secs:
            return None  # rode it out for the whole budget and it never cleared
        if now - last_refresh >= challenge_refresh_secs:
            try:
                driver.get(url)  # reload nudges the stalled challenge to re-evaluate
            except Exception:
                return None
            last_refresh = now
            if on_challenge:
                on_challenge(round(now - long_wait_started))
        time.sleep(2)


def _fetch_undetected(url, wait_secs=30):
    """
    Fetch a single Cloudflare-challenged page with undetected-chromedriver (headed).

    Cloudflare's managed challenge flags headless browsers, so this runs with a
    visible window. Returns the page HTML once the challenge clears and a table
    appears, or None if uc is unavailable or the challenge never resolves.
    """
    driver = _new_undetected_driver()
    if driver is None:
        return None
    try:
        return _load_via_driver(driver, url, wait_secs=wait_secs)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _fetch_playwright(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector("table", timeout=12000)
            except Exception:
                page.wait_for_timeout(3000)
            html = page.content()
        finally:
            page.close()
            browser.close()
    return html


def _parse_rankings(html, page_url, api_key):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError("No table found on page — the URL may not contain a rankings table")

    table_html = str(table)
    if len(table_html) > 25000:
        table_html = table_html[:25000]

    return _llm_parse_rankings(table_html, page_url, api_key)


def _llm_parse_rankings(table_html, page_url, api_key):
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    prompt = (
        "Extract player/person rankings from this HTML table.\n"
        "Return a JSON array where each object has:\n"
        '- rank: integer\n'
        '- name: string (full name)\n'
        '- country: string (full country name, e.g. "United States"; infer from flag image alt text if needed)\n'
        '- metric: string (the ranking metric shown — earnings, bracelet count, points, titles, etc.)\n'
        '- profile_path: string (the href/path to the person\'s profile page, or null)\n\n'
        "Return ONLY valid JSON, no explanation or markdown.\n\n"
        + table_html
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data = json.loads(raw)
    result = []
    for p in data:
        path = p.get("profile_path") or ""
        profile_url = urljoin(page_url, path) if path else None
        result.append({
            "rank": p.get("rank"),
            "name": p.get("name", ""),
            "country": p.get("country", ""),
            "metric": p.get("metric", ""),
            "profile_url": profile_url,
            "city_state": "",
            "last_active_year": None,
        })
    return result


def _extract_location(soup):
    text = soup.get_text(separator="\n")
    for pattern in [
        r"Hometown[:\s]+([^\n]+)",
        r"From[:\s]+([^\n]+)",
        r"Location[:\s]+([^\n]+)",
        r"Lives in[:\s]+([^\n]+)",
        r"Residence[:\s]+([^\n]+)",
        r"City[:\s]+([^\n]+)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            loc = m.group(1).strip()[:80]
            if len(loc) > 2 and not loc.startswith(("http", "www")):
                return loc
    return ""


def _extract_last_year(soup):
    text = soup.get_text()
    current_year = datetime.now().year
    years = [int(y) for y in re.findall(r"\b(20[0-2]\d)\b", text) if 2000 <= int(y) <= current_year]
    return max(years) if years else None


def _is_us(country):
    return any(x in country for x in ("United States", "USA", "U.S.A", "America"))


def _is_recently_active(year, cutoff_year):
    if year is None:
        return True  # don't exclude players where activity date couldn't be determined
    return year >= cutoff_year
