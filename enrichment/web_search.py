"""Web search + LLM contact extraction — fallback when social scraping finds no email."""

import json
import re


def enrich_web(name, profession_hint="", anthropic_api_key=None):
    """
    Search DuckDuckGo for contact info, then extract with LLM (or regex fallback).

    Two passes: first the DDG result snippets (cheap), then — when no email turned
    up — fetch the top candidate result pages and extract from the real page, since
    contact emails usually live on the page (contact/about, link hubs) rather than
    in the ~160-char snippet. Returns None if nothing useful is found.
    """
    found = _ddg_search(name, profession_hint)
    snippets, urls = found["snippets"], found["urls"]
    if not snippets and not urls:
        return None

    result = None
    if snippets:
        extracted = _llm_extract(name, snippets, anthropic_api_key) if anthropic_api_key \
            else _regex_extract(snippets)
        if extracted:
            result = extracted
            result["source"] = ["web_search"]

    # Page-fetch pass: only when the snippets gave us no email (augment-on-miss,
    # to bound cost). Fetch the top non-social pages and merge any hits.
    if not (result and result.get("emails")) and urls:
        page = _fetch_pages(urls, anthropic_api_key)
        if page:
            if result is None:
                result = {"emails": [], "phones": [], "profiles": {}, "source": []}
            result["emails"] += [e for e in (page.get("emails") or [])
                                 if e not in result["emails"]]
            result["phones"] += [p for p in (page.get("phones") or [])
                                 if p not in result["phones"]]
            if page.get("emails") or page.get("phones"):
                result.setdefault("source", []).append("web_page")

    if not result or not (result.get("emails") or result.get("phones")):
        return None
    return result


# Max result pages to actually fetch per person — page fetches are ~10s each, so
# keep this small; bulk follower enrichment skips web search entirely.
_MAX_PAGES = 2


def _ddg_search(name, profession_hint=""):
    """Return {'snippets': [str], 'urls': [str]} from a small set of DDG queries.

    Captures the result URLs (not just snippets) so callers can fetch the real
    pages. Social/tracking domains are dropped so we only fetch personal/contact
    pages and link hubs.
    """
    empty = {"snippets": [], "urls": []}
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return empty
    try:
        from .social_scraper import _SOCIAL_SKIP
    except Exception:
        _SOCIAL_SKIP = frozenset()

    hint = profession_hint.strip()
    queries = [
        f'"{name}" {hint} email contact'.strip(),
        f'"{name}" {hint} email'.strip(),
        f'"{name}" {hint} contact'.strip(),
        f'"{name}" {hint} site:linktr.ee'.strip(),
        f'"{name}" {hint} site:twitter.com OR site:linkedin.com'.strip(),
    ]
    snippets, urls, seen_urls = [], [], set()
    try:
        with DDGS(timeout=8) as ddgs:
            for q in queries:
                try:
                    for r in ddgs.text(q, max_results=3):
                        body = r.get("body") or r.get("snippet", "")
                        if body:
                            snippets.append(body)
                        href = (r.get("href") or r.get("url") or "").strip()
                        if not href.startswith("http"):
                            continue
                        if any(s in href.lower() for s in _SOCIAL_SKIP):
                            continue
                        if href not in seen_urls:
                            seen_urls.add(href)
                            urls.append(href)
                except Exception:
                    pass
    except Exception:
        return {"snippets": snippets, "urls": urls}
    return {"snippets": snippets, "urls": urls}


def _fetch_pages(urls, anthropic_api_key=None):
    """Fetch the top candidate pages and return merged {emails, phones} or None.

    Reuses the SSRF-guarded fetch + extraction from social_scraper (imported
    lazily to avoid an import cycle). apify_token is intentionally None — the
    paid crawler fallback stays off.
    """
    try:
        from .social_scraper import _scrape_generic
    except Exception:
        return None
    emails, phones = [], []
    for url in urls[:_MAX_PAGES]:
        try:
            hit = _scrape_generic(url, anthropic_api_key=anthropic_api_key, apify_token=None)
        except Exception:
            hit = None
        if not hit:
            continue
        emails += [e for e in (hit.get("emails") or []) if e not in emails]
        phones += [p for p in (hit.get("phones") or []) if p not in phones]
        if emails:
            break  # got what we came for; don't spend the second fetch
    if not emails and not phones:
        return None
    return {"emails": emails, "phones": phones}


def _regex_extract(snippets):
    text = " ".join(snippets)
    emails = list(dict.fromkeys(re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)))
    phones = list(dict.fromkeys(re.findall(r"\+?1?\s*[\(\-\.]?\d{3}[\)\-\.\s]\s*\d{3}[\-\.\s]\d{4}", text)))
    # strip common false-positive domains
    emails = [e for e in emails if not any(e.endswith(d) for d in ("example.com", "sentry.io", "w3.org"))]
    if not emails and not phones:
        return None
    return {"emails": emails, "phones": phones, "profiles": {}}


def _llm_extract(name, snippets, api_key):
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        combined = "\n\n".join(snippets[:6])[:3000]
        prompt = (
            f"Extract contact information for the person named '{name}' from these web snippets.\n"
            "Only include info clearly about THIS specific person — ignore unrelated mentions.\n"
            'Return JSON only: {"emails": [...], "phones": [...], "profiles": {"twitter": "url", "linkedin": "url"}}\n'
            "Return empty arrays/objects if nothing is found for a field.\n\n"
            + combined
        )
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        emails = data.get("emails") or []
        phones = data.get("phones") or []
        profiles = data.get("profiles") or {}
        if not emails and not phones and not profiles:
            return None
        return {"emails": emails, "phones": phones, "profiles": profiles}
    except Exception:
        return _regex_extract(snippets)
