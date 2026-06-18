"""
Contact enrichment pipeline.

Layer 0 — Social profile scraping (Apify actors + direct HTTP)
           Handles Instagram, Twitter/X, TikTok, Reddit, Substack, generic URLs.
           Follows bio/external links (Linktree, personal sites) for email.
Layer 1 — DuckDuckGo web search + LLM extraction (free fallback)

Input:  list of {name, country?, instagram_url?}
Output: dict keyed by name → {emails, phones, profiles, confidence, source}
"""

from __future__ import annotations

import time

from .web_search import enrich_web


def enrich_person(name, profession_hint="", location_hint="", profile_urls=None,
                  openai_api_key=None, apify_token=None):
    result = {
        "name": name,
        "emails": [],
        "phones": [],
        "profiles": {},
        "confidence": "none",
        "source": [],
    }

    # Layer 0 — social profile scraping (bio links, email-in-bio, platform data)
    if profile_urls and apify_token:
        from .social_scraper import scrape_profile
        for purl in profile_urls:
            scraped = scrape_profile(purl, apify_token=apify_token, openai_api_key=openai_api_key)
            if not scraped:
                continue
            if scraped.get("name") and scraped["name"] != name:
                result["name"] = scraped["name"]
            result["emails"] += [e for e in (scraped.get("emails") or []) if e not in result["emails"]]
            result["phones"] += [p for p in (scraped.get("phones") or []) if p not in result["phones"]]
            result["profiles"].update(scraped.get("profiles") or {})
            result["source"].append(scraped.get("source", "social_scrape"))
            if result["confidence"] == "none" and (scraped.get("emails") or scraped.get("phones")):
                result["confidence"] = "medium"

    # Layer 1 — web search + LLM extraction (slow, ~5s/person). Only when no
    # email was found above and we have an OpenAI key.
    if not result["emails"] and openai_api_key:
        web = enrich_web(name, profession_hint=profession_hint, openai_api_key=openai_api_key)
        if web:
            result["emails"] += [e for e in (web.get("emails") or []) if e not in result["emails"]]
            result["phones"] += [p for p in (web.get("phones") or []) if p not in result["phones"]]
            result["profiles"].update(web.get("profiles") or {})
            if web.get("emails"):
                result["source"].append("web_search")
                if result["confidence"] == "none":
                    result["confidence"] = "low"

    return result


def enrich_followers(brand_handle, limit=200, openai_api_key=None, apify_token=None,
                     follow_bio_links=True):
    """
    Enrich the followers of a brand/team X account.

    One actor call fans `brand_handle` out into up to `limit` follower contacts
    (name, bio, email-in-bio, website) via scrape_followers. Each follower still
    missing an email then gets the same one-level bio-link follow that
    enrich_person uses. Web-search fallback is intentionally NOT run per
    follower — at 200+ records its ~5s/lookup would dominate runtime.

    Returns a dict keyed by follower handle → the standard enrichment record.
    """
    if not (brand_handle and apify_token):
        return {}

    from .social_scraper import scrape_followers, _extract_from_bio_link, _X_COST_PER_USER

    followers = scrape_followers(brand_handle, apify_token, limit=limit)
    # No silent truncation: a full `limit` batch means more followers went
    # unfetched. Surface that plus the (rough) cost of what we did pull.
    n = len(followers)
    print(f"[enrich_followers] @{brand_handle}: {n} followers "
          f"(~${n * _X_COST_PER_USER:.2f})"
          + (f"; capped at limit={limit}, more not fetched" if n >= limit else ""))

    results = {}
    for f in followers:
        result = {
            "name": f.get("name"),
            "emails": list(f.get("emails") or []),
            "phones": list(f.get("phones") or []),
            "profiles": dict(f.get("profiles") or {}),
            "confidence": "medium" if f.get("emails") else "none",
            "source": [f.get("source", "social_scrape:x_followers")],
        }
        external = f.get("external_url") or ""
        if external:
            result["profiles"]["website"] = external

        if (not result["emails"] and follow_bio_links
                and external.startswith("http")):
            extra = _extract_from_bio_link(external, openai_api_key, apify_token)
            if extra:
                result["emails"] += [e for e in (extra.get("emails") or [])
                                     if e not in result["emails"]]
                result["phones"] += [p for p in (extra.get("phones") or [])
                                     if p not in result["phones"]]
                if result["emails"]:
                    result["confidence"] = "medium"
                    result["source"].append("bio_link")

        results[f.get("handle") or f.get("name")] = result

    return results


def enrich_batch(players, profession_hint="", openai_api_key=None, apify_token=None):
    """
    Enrich a list of player dicts.
    Each dict needs at minimum: {name}
    Optional fields used for accuracy: {country, instagram_url}
    Returns dict keyed by player name.
    """
    results = {}
    for i, player in enumerate(players):
        name = (player.get("name") or "").strip()
        if not name:
            continue
        location = player.get("country") or player.get("city_state") or ""
        instagram_url = player.get("instagram_url") or ""
        profile_urls = [instagram_url] if instagram_url else []

        results[name] = enrich_person(
            name=name,
            profession_hint=profession_hint,
            location_hint=location,
            profile_urls=profile_urls,
            openai_api_key=openai_api_key,
            apify_token=apify_token,
        )
        if i < len(players) - 1:
            time.sleep(0.15)
    return results
