"""
Layer 0: Social profile scraper for contact enrichment.

Detects platform from URL, scrapes the profile, and extracts:
  name, bio, external links, emails/phones when present.

After scraping, follows the bio/external link one level deep
(Linktree, personal sites, etc.) to find emails.

Platforms
---------
Instagram  → Apify apify/instagram-profile-scraper
Twitter/X  → Apify apidojo/twitter-user-scraper
TikTok     → Apify clockworks/tiktok-profile-scraper
Reddit     → Reddit public JSON API (no Apify needed)
Substack   → Direct HTTP scrape of /about
Generic    → Direct HTTP + regex + optional LLM extraction
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

# Domains we won't follow as bio links — social/app destinations, not contact pages
_SKIP_BIO_DOMAINS = frozenset([
    "facebook.com", "youtube.com", "apple.com", "google.com",
    "spotify.com", "amazon.com", "tiktok.com", "instagram.com",
    "twitter.com", "x.com", "reddit.com",
])


# ── Name normalisation ───────────────────────────────────────────────────────

def _clean_name(raw: str) -> str:
    """
    Normalize a scraped display name.
    - slug_format / dot.format → title-cased words
    - all-lowercase with spaces → title-cased
    - already mixed-case with spaces → left as-is
    - trailing digit runs stripped (john_doe_123 → John Doe)
    """
    if not raw:
        return raw
    # Slug: underscores or dots with no spaces → split and title-case
    if "_" in raw or ("." in raw and " " not in raw):
        cleaned = re.sub(r"[_.]", " ", raw)
        cleaned = re.sub(r"\s+\d+\s*$", "", cleaned).strip()
        return cleaned.title()
    # Has spaces and already mixed-case → real name, leave alone
    if " " in raw and raw != raw.lower():
        return raw
    # Has spaces but all-lowercase → title-case it
    if " " in raw:
        return raw.title()
    # Single word: just capitalise the first letter
    return raw[0].upper() + raw[1:] if raw else raw


# ── Public entry point ────────────────────────────────────────────────────────

def scrape_profile(url: str, apify_token: str = None, openai_api_key: str = None, twitter_bearer: str = None) -> dict | None:  # twitter_bearer kept for call-site compat
    """
    Scrape a social profile URL and return contact fragments.

    Returns dict with keys: name, emails, phones, bio, profiles, external_url, source
    or None if nothing useful was found.
    """
    platform, identifier = _detect_platform(url)

    raw = None
    if platform == "instagram" and apify_token:
        raw = _scrape_instagram(identifier, apify_token)
    elif platform == "twitter":
        raw = _scrape_twitter(identifier, apify_token=apify_token)
    elif platform == "tiktok" and apify_token:
        raw = _scrape_tiktok(identifier, apify_token)
    elif platform == "reddit":
        raw = _scrape_reddit(identifier)
    elif platform == "substack":
        raw = _scrape_substack(identifier, openai_api_key)
    else:
        full_url = url if "://" in url else ("https://" + url)
        raw = _scrape_generic(full_url, openai_api_key)

    if not raw:
        return None

    # Follow external/bio link one level deep when no email found yet
    if not raw.get("emails"):
        external = raw.get("external_url") or ""
        if external and external.startswith("http"):
            extra = _extract_from_bio_link(external, openai_api_key)
            if extra:
                raw.setdefault("emails", [])
                raw.setdefault("phones", [])
                raw["emails"] += extra.get("emails") or []
                raw["phones"] += extra.get("phones") or []

    profiles = raw.get("profiles") or {}
    external = raw.get("external_url") or ""
    if external:
        profiles["website"] = external

    result = {
        "name": _clean_name(raw.get("name")),
        "emails": list(dict.fromkeys(raw.get("emails") or [])),
        "phones": list(dict.fromkeys(raw.get("phones") or [])),
        "bio": raw.get("bio"),
        "profiles": profiles,
        "external_url": external,
        "source": f"social_scrape:{platform}",
    }
    if result["name"] or result["emails"] or result["phones"] or result["profiles"]:
        return result
    return None


# ── Platform detection ────────────────────────────────────────────────────────

def _detect_platform(url: str) -> tuple[str, str]:
    """Returns (platform, identifier) from a URL string."""
    raw_url = url if "://" in url else ("https://" + url)
    try:
        parsed = urllib.parse.urlparse(raw_url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.strip("/")
        parts = [p for p in path.split("/") if p]

        if "instagram.com" in host:
            return ("instagram", parts[0] if parts else "")

        if "twitter.com" in host or "x.com" in host:
            return ("twitter", parts[0] if parts else "")

        if "tiktok.com" in host:
            return ("tiktok", (parts[0] if parts else "").lstrip("@"))

        if "reddit.com" in host:
            if len(parts) >= 2 and parts[0] in ("u", "user"):
                return ("reddit", parts[1])
            return ("reddit", parts[0] if parts else "")

        if host.endswith("substack.com"):
            if host == "substack.com":
                username = (parts[0] if parts else "").lstrip("@")
            else:
                username = host.replace(".substack.com", "")
            return ("substack", username)

    except Exception:
        pass

    return ("generic", url)


# ── Apify helper ──────────────────────────────────────────────────────────────

def _run_apify_actor(actor_id: str, run_input: dict, token: str, timeout: int = 90) -> list:
    try:
        from apify_client import ApifyClient
        client = ApifyClient(token)
        run = client.actor(actor_id).call(run_input=run_input, timeout_secs=timeout)
        if not run:
            return []
        return list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception:
        return []


# ── Platform scrapers ─────────────────────────────────────────────────────────

def _scrape_instagram(handle: str, token: str) -> dict | None:
    if not handle:
        return None
    items = _run_apify_actor(
        "apify/instagram-profile-scraper",
        {"usernames": [handle]},
        token,
        timeout=60,
    )
    if not items:
        return None
    d = items[0]
    bio = d.get("biography") or ""
    emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", bio)
    return {
        "name": d.get("fullName") or handle,
        "bio": bio,
        "emails": emails,
        "phones": [],
        "external_url": d.get("externalUrl") or d.get("external_url") or "",
        "profiles": {"instagram": f"https://www.instagram.com/{handle}/"},
    }


_SOCIAL_SKIP = frozenset([
    "twitter.com", "x.com", "t.co", "instagram.com", "facebook.com",
    "tiktok.com", "youtube.com", "linkedin.com", "reddit.com",
    "duckduckgo.com", "google.com", "apple.com",
])


def _scrape_twitter(handle: str, apify_token: str = None) -> dict | None:
    """
    Scrape a Twitter/X profile.
    Primary:  apidojo/twitter-user-scraper Apify actor (requires subscription).
    Fallback: DuckDuckGo search (name only, no website).
    """
    if not handle:
        return None
    if apify_token:
        result = _scrape_twitter_apify(handle, apify_token)
        if result:
            return result
    return _scrape_twitter_search(handle)


def _scrape_twitter_apify(handle: str, token: str) -> dict | None:
    """dead00/twitter-profile-scraper-no-cookies — name, bio, website, no auth required."""
    items = _run_apify_actor(
        "dead00/twitter-profile-scraper-no-cookies",
        {"usernames": [handle]},
        token,
        timeout=60,
    )
    if not items:
        return None
    d = items[0]
    bio = d.get("bio") or ""
    website_obj = d.get("website") or {}
    website = website_obj.get("expanded_url") or website_obj.get("display_url") or ""
    if website and not website.startswith("http"):
        website = "https://" + website
    emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", bio)
    return {
        "name": d.get("display_name") or handle,
        "bio": bio,
        "emails": emails,
        "phones": [],
        "external_url": website,
        "profiles": {"twitter": f"https://twitter.com/{handle}"},
    }


def _scrape_twitter_search(handle: str) -> dict | None:
    """DuckDuckGo fallback when Apify is unavailable: name only, best-effort website."""
    try:
        from duckduckgo_search import DDGS
        name = handle
        bio = ""
        website = ""

        with DDGS(timeout=10) as ddgs:
            profile_results = list(ddgs.text(f"twitter.com/{handle}", max_results=5))

        if profile_results:
            title = profile_results[0].get("title") or ""
            nm = re.match(r"^([^(@/|·—]+)", title)
            if nm:
                extracted = nm.group(1).strip()
                if extracted and extracted.lower() not in (handle.lower(), "x"):
                    name = extracted
            snippets = " ".join(r.get("body", "") for r in profile_results)
            bio = profile_results[0].get("body", "")
            website = _extract_website_from_text(snippets, skip=_SOCIAL_SKIP)

        return {
            "name": name,
            "bio": bio,
            "emails": [],
            "phones": [],
            "external_url": website,
            "profiles": {"twitter": f"https://twitter.com/{handle}"},
        }
    except Exception:
        return None


def _extract_website_from_text(text: str, skip: frozenset = None) -> str:
    """Pull the first non-social, non-tracking URL out of a text blob."""
    if skip is None:
        skip = frozenset([
            "twitter.com", "x.com", "t.co", "instagram.com", "facebook.com",
            "tiktok.com", "youtube.com", "linkedin.com", "reddit.com",
            "duckduckgo.com", "google.com", "apple.com", "amazon.com",
        ])
    urls = re.findall(r'(?:https?://|www\.)[^\s,)>\'"<\]]+', text)
    for u in urls:
        u = u.rstrip(".,;)>]\"'")
        if not any(s in u.lower() for s in skip):
            return u if u.startswith("http") else "https://" + u
    return ""


def _scrape_tiktok(handle: str, token: str) -> dict | None:
    if not handle:
        return None
    items = _run_apify_actor(
        "clockworks/tiktok-profile-scraper",
        {"profiles": [f"https://www.tiktok.com/@{handle}"], "resultsPerPage": 1},
        token,
        timeout=60,
    )
    if not items:
        return None
    d = items[0]
    bio = d.get("signature") or d.get("bio") or ""
    bio_link = d.get("bioLink") or d.get("bioUrl") or ""
    emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", bio)
    return {
        "name": d.get("nickName") or d.get("nickname") or handle,
        "bio": bio,
        "emails": emails,
        "phones": [],
        "external_url": bio_link,
        "profiles": {"tiktok": f"https://www.tiktok.com/@{handle}"},
    }


def _scrape_reddit(username: str) -> dict | None:
    if not username:
        return None
    try:
        url = f"https://www.reddit.com/user/{username}/about.json"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 contact-enrichment/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        d = data.get("data") or {}
        subreddit = d.get("subreddit") or {}
        bio = subreddit.get("public_description") or ""
        name = subreddit.get("title") or username
        emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", bio)
        return {
            "name": name,
            "bio": bio,
            "emails": emails,
            "phones": [],
            "external_url": "",
            "profiles": {"reddit": f"https://www.reddit.com/user/{username}/"},
        }
    except Exception:
        return None


def _scrape_substack(username: str, openai_api_key: str = None) -> dict | None:
    if not username:
        return None
    about_url = f"https://{username}.substack.com/about"
    result = _scrape_generic(about_url, openai_api_key)
    if result:
        result.setdefault("profiles", {})
        result["profiles"]["substack"] = f"https://{username}.substack.com"
    return result


# ── Generic HTTP scrape + extraction ─────────────────────────────────────────

def _scrape_generic(url: str, openai_api_key: str = None) -> dict | None:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; contact-enrichment/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    return _extract_contacts_from_html(html, openai_api_key)


def _extract_from_bio_link(url: str, openai_api_key: str = None) -> dict | None:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if any(d in host for d in _SKIP_BIO_DOMAINS):
        return None
    return _scrape_generic(url, openai_api_key)


def _extract_contacts_from_html(html: str, openai_api_key: str = None) -> dict | None:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    emails = list(dict.fromkeys(
        re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    ))
    phones = list(dict.fromkeys(
        re.findall(r"\+?1?\s*[\(\-\.]?\d{3}[\)\-\.\s]\s*\d{3}[\-\.\s]\d{4}", text)
    ))
    _NOISE = ("example.com", "sentry.io", "w3.org", "schema.org", "amazonaws.com", "wixpress.com")
    emails = [e for e in emails if not any(e.endswith(d) for d in _NOISE)]

    if emails or phones:
        return {"name": None, "emails": emails, "phones": phones, "bio": None, "profiles": {}, "external_url": None}

    if openai_api_key:
        return _llm_extract(text[:3000], openai_api_key)
    return None


def _llm_extract(text: str, api_key: str) -> dict | None:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    "Extract contact information from the following text.\n"
                    'Return JSON only: {"name": "...", "emails": [...], "phones": [...]}\n'
                    "Use null / empty arrays if not found.\n\n" + text
                ),
            }],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        name = data.get("name") or None
        emails = data.get("emails") or []
        phones = data.get("phones") or []
        if name or emails or phones:
            return {"name": name, "emails": emails, "phones": phones, "bio": None, "profiles": {}, "external_url": None}
    except Exception:
        pass
    return None
