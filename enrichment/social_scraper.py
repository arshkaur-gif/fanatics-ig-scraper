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
Generic    → Direct HTTP + regex + optional LLM extraction, escalating to
             the apify/website-content-crawler actor (JS render + residential
             proxies + shallow crawl) when the cheap fetch finds nothing useful.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
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

def scrape_profile(url: str, apify_token: str = None, openai_api_key: str = None) -> dict | None:
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
        raw = _scrape_substack(identifier, openai_api_key, apify_token)
    else:
        full_url = url if "://" in url else ("https://" + url)
        raw = _scrape_generic(full_url, openai_api_key, apify_token)

    if not raw:
        return None

    # Follow external/bio link one level deep when no email found yet
    if not raw.get("emails"):
        external = raw.get("external_url") or ""
        if external and external.startswith("http"):
            extra = _extract_from_bio_link(external, openai_api_key, apify_token)
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


# ── Brand-follower discovery (X / Twitter) ────────────────────────────────────
#
# Goal: given a brand/team X account, pull its followers and enrich each.
# kaitoeasyapi/premium-x-follower-scraper-following-data returns the follower
# LIST with full profile data inline, so one actor call is discovery +
# enrichment in a single request (~$0.15 / 1,000 users). This is a different
# shape from the per-handle lookup above — it fans one brand handle out into N
# follower contacts.

_X_FOLLOWER_ACTOR = "kaitoeasyapi/premium-x-follower-scraper-following-data"
_X_FOLLOWER_MIN = 200          # actor floor for both maxFollowers and maxFollowings
_X_COST_PER_USER = 0.00015     # $0.15 / 1,000 users — for the cost estimate

_EMAIL_RE = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"


def _x_profile_website(d: dict) -> str:
    """
    Pull the real (un-shortened) website from a kaitoeasyapi user record.

    The top-level `url` is a t.co short link (or null); the expanded URL lives
    in entities.url.urls[].expanded_url (profile website) — fall back to links
    in the bio (entities.description.urls) and finally the raw `url`.
    """
    ent = d.get("entities") or {}
    for key in ("url", "description"):
        for u in (ent.get(key) or {}).get("urls") or []:
            exp = u.get("expanded_url")
            if exp:
                return exp
    raw = d.get("url") or ""
    if raw and not raw.startswith("http"):
        raw = "https://" + raw
    return raw


def _x_follower_to_contact(d: dict) -> dict | None:
    """Map one kaitoeasyapi follower record → the standard contact dict.

    Pure (no network) so it's unit-testable with canned items. Returns None for
    a record with no usable handle.
    """
    handle = d.get("screen_name") or ""
    if not handle:
        return None
    bio = d.get("description") or ""
    # Inline `email` is rare but real when present; also scan the bio.
    emails = []
    if d.get("email"):
        emails.append(d["email"])
    emails += re.findall(_EMAIL_RE, bio)
    return {
        "handle": handle,
        "name": _clean_name(d.get("name") or handle),
        "bio": bio,
        "emails": list(dict.fromkeys(emails)),
        "phones": [],
        "external_url": _x_profile_website(d),
        "location": d.get("location") or "",
        "profiles": {"twitter": f"https://twitter.com/{handle}"},
        "source": "social_scrape:x_followers",
    }


def _x_followers_items_to_contacts(items: list, limit: int = None) -> list:
    """Map + dedupe a follower dataset into contact dicts (pure, testable)."""
    contacts, seen = [], set()
    for d in items or []:
        c = _x_follower_to_contact(d)
        if not c:
            continue
        key = c["handle"].lower()
        if key in seen:
            continue
        seen.add(key)
        contacts.append(c)
        if limit and len(contacts) >= limit:
            break
    return contacts


def scrape_followers(brand_handle: str, apify_token: str, *, limit: int = 200) -> list:
    """
    Pull a brand/team X account's followers, each as a standard contact dict.

    One actor call returns up to `limit` followers WITH profile data inline
    (name, bio, website, email-in-bio), so this is discovery + enrichment in a
    single request. `limit` is floored at the actor minimum (200). Records are
    deduped by handle. Returns [] on any failure (token missing, actor error).
    """
    if not brand_handle or not apify_token:
        return []
    limit = max(_X_FOLLOWER_MIN, int(limit))
    items = _run_apify_actor(
        _X_FOLLOWER_ACTOR,
        {
            "user_names": [brand_handle],
            "getFollowers": True,
            "getFollowing": False,
            "maxFollowers": limit,
            "maxFollowings": _X_FOLLOWER_MIN,  # actor validates >=200 even when off
        },
        apify_token,
        timeout=300,
    )
    return _x_followers_items_to_contacts(items, limit=limit)


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


def _scrape_substack(username: str, openai_api_key: str = None, apify_token: str = None) -> dict | None:
    if not username:
        return None
    about_url = f"https://{username}.substack.com/about"
    result = _scrape_generic(about_url, openai_api_key, apify_token)
    if result:
        result.setdefault("profiles", {})
        result["profiles"]["substack"] = f"https://{username}.substack.com"
    return result


# ── SSRF guard for server-side fetches ───────────────────────────────────────
#
# `_scrape_generic` fetches caller-influenced URLs (player `instagram_url`,
# bio/external links) directly from this server. Without a guard that is an SSRF
# + local-file-read primitive: `file:///etc/passwd`, cloud-metadata
# (169.254.169.254), or internal hosts would all be fetched and any emails/phones
# in the response handed back to the caller. So every server-side fetch is gated
# on `_url_is_fetchable`: http(s) scheme only, and the host must resolve solely to
# public IPs. Redirects are re-validated (a public URL can 30x to an internal one).

def _url_is_fetchable(url: str) -> bool:
    """True only for http(s) URLs whose host resolves entirely to public IPs."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, parsed.port or None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return False
    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect target so a public URL can't bounce to an
    internal one (or to a non-http scheme)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _url_is_fetchable(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _safe_urlopen(url: str, timeout: int = 10):
    """urlopen that rejects non-public / non-http(s) URLs and unsafe redirects."""
    if not _url_is_fetchable(url):
        raise ValueError("URL is not a fetchable public http(s) address")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; contact-enrichment/1.0)"},
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    return opener.open(req, timeout=timeout)


# ── Generic HTTP scrape + extraction ─────────────────────────────────────────

def _scrape_generic(url: str, openai_api_key: str = None, apify_token: str = None) -> dict | None:
    result = None
    try:
        with _safe_urlopen(url, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        result = _extract_contacts_from_html(html, openai_api_key)
    except Exception:
        result = None

    # Tiered fallback: the cheap urllib fetch can't render JS, gets bot-blocked,
    # and only sees one page. When it yields nothing useful, escalate to the
    # Apify content crawler (pay-per-use, so gated to hard cases only).
    #
    # Gated behind ENABLE_CRAWLER_FALLBACK and OFF by default: the crawler runs
    # ~30s–2min, which exceeds Vercel Hobby's 10s cap. Only enable on a Pro
    # deploy with maxDuration raised (see vercel.json / README deploy note).
    if (
        apify_token
        and _crawler_fallback_enabled()
        and _url_is_fetchable(url)
        and (not result or not (result.get("emails") or result.get("phones")))
    ):
        crawled = _scrape_website_crawler(url, apify_token, openai_api_key)
        if crawled:
            return crawled
    return result


def _crawler_fallback_enabled() -> bool:
    """The Apify crawler fallback is opt-in (Pro deploy only) — see _scrape_generic."""
    return os.environ.get("ENABLE_CRAWLER_FALLBACK", "").strip().lower() in ("1", "true", "yes", "on")


_CRAWLER_ACTOR = "apify/website-content-crawler"


def _crawler_run_input(url: str) -> dict:
    """Shared actor input for both the blocking and async crawl paths."""
    return {
        "startUrls": [{"url": url}],            # objects, not strings
        "crawlerType": "playwright:adaptive",   # namespaced enum, NOT bare "adaptive"
        "maxCrawlDepth": 1,                      # follow same-domain links one level
        "maxCrawlPages": 5,                      # HARD cost cap per lookup
        "saveMarkdown": True,
    }


def _crawl_items_to_result(items: list, openai_api_key: str = None, fallback_url: str = None) -> dict | None:
    """
    Turn website-content-crawler dataset items into the standard contact dict.

    Dataset = one item per crawled page; concatenate before extraction. Shared by
    the blocking scraper and the async poll endpoint so the shaping logic is in
    one place (and unit-testable with fake items — no Apify credits needed).
    """
    if not items:
        return None
    combined = "\n\n".join(
        (it.get("markdown") or it.get("text") or "") for it in items
    ).strip()
    if not combined:
        return None
    result = _extract_contacts_from_text(combined, openai_api_key)
    if not result:
        return None
    title = (items[0].get("metadata") or {}).get("title")
    if title:
        result["name"] = title  # run through _clean_name at scrape_profile exit
    result["external_url"] = items[0].get("url") or fallback_url
    return result


def _scrape_website_crawler(url: str, token: str, openai_api_key: str = None) -> dict | None:
    """
    BLOCKING fallback generic scraper backed by apify/website-content-crawler.

    Runs on Apify's infra (headless browser + residential proxies), renders JS,
    rotates past bot-protection, and shallow-crawls (depth=1) to reach
    /contact and /about. Waits for the crawl (~30s–2min), so it only fits a
    long-timeout (Pro) deploy. For serverless under a tight cap, use the
    start_website_crawl / fetch_crawl_result pair below instead.
    """
    items = _run_apify_actor(_CRAWLER_ACTOR, _crawler_run_input(url), token, timeout=90)
    return _crawl_items_to_result(items, openai_api_key, fallback_url=url)


# ── Async crawl (start + poll) — serverless-safe alternative to the blocking path ─
#
# The crawl runs on Apify's servers, not here; .start() returns a run id in ~1s
# without waiting, and each poll is a sub-second status check. So no single
# request blocks for the ~2min crawl — it fits even Vercel Hobby's 10s cap.
# Driven by /api/crawl-start and /api/crawl-status (see app.py).
#
# The `client` param is injectable purely so the state machine can be tested
# with a fake client (no real Apify run, no credits); production passes None.

def start_website_crawl(url: str, token: str, client=None) -> str | None:
    """Kick off a crawl WITHOUT waiting. Returns an Apify run id to poll later."""
    try:
        if client is None:
            from apify_client import ApifyClient
            client = ApifyClient(token)
        run = client.actor(_CRAWLER_ACTOR).start(run_input=_crawler_run_input(url))
        return (run or {}).get("id")
    except Exception:
        return None


def fetch_crawl_result(run_id: str, token: str, openai_api_key: str = None, client=None) -> dict:
    """
    Poll a crawl run started by start_website_crawl.

    Returns {"status": <apify run status>, "result": <contact dict | None>}.
    `result` stays None until status == "SUCCEEDED". Reading run status and the
    dataset costs no Apify credits — only the actor run itself does.
    """
    try:
        if client is None:
            from apify_client import ApifyClient
            client = ApifyClient(token)
        run = client.run(run_id).get()
        if not run:
            return {"status": "NOT_FOUND", "result": None}
        status = run.get("status")
        if status != "SUCCEEDED":
            return {"status": status, "result": None}
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        return {"status": status, "result": _crawl_items_to_result(items, openai_api_key)}
    except Exception as e:
        return {"status": "ERROR", "result": None, "error": str(e)}


def _extract_from_bio_link(url: str, openai_api_key: str = None, apify_token: str = None) -> dict | None:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if any(d in host for d in _SKIP_BIO_DOMAINS):
        return None
    return _scrape_generic(url, openai_api_key, apify_token)


def _extract_contacts_from_html(html: str, openai_api_key: str = None) -> dict | None:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _extract_contacts_from_text(text, openai_api_key)


def _extract_contacts_from_text(text: str, openai_api_key: str = None) -> dict | None:
    """Pull emails/phones (then LLM as last resort) out of already-clean text."""
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
