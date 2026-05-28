"""Scraper for public rankings pages. WSOP standings use a direct API; other sites use LLM parsing."""

import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup


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
    """Fetch using curl_cffi (Chrome TLS). Falls back to Playwright for JS-heavy pages."""
    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, impersonate="chrome120", timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.find("table"):
                return r.text
    except Exception:
        pass
    return _fetch_playwright(url)


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
