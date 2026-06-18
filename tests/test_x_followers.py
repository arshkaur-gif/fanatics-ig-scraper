"""
Tests for the brand-follower X enrichment path. No test framework and NO Apify
credits required — the mapping helpers are pure, and enrich_followers is driven
with a monkeypatched scrape_followers. Run directly:

    python3 tests/test_x_followers.py

The canned records mirror the real kaitoeasyapi/premium-x-follower-scraper
output shape captured from a live probe (top-level name/screen_name/description/
location/email, t.co-wrapped `url`, expanded link under entities.url.urls).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichment import pipeline
from enrichment.social_scraper import (
    _x_follower_to_contact,
    _x_followers_items_to_contacts,
    _x_profile_website,
)


# ── Canned actor records (real shape, no network) ─────────────────────────────

def _record(**over):
    base = {
        "name": "Harrison Ehrlich",
        "screen_name": "ehrlichh",
        "description": "",
        "location": "",
        "url": None,
        "entities": {"description": {"urls": []}},
        "email": None,
        "type": "follower",
        "target_username": "Fanatics",
    }
    base.update(over)
    return base


# ── Website extraction ────────────────────────────────────────────────────────

def test_website_prefers_expanded_profile_url():
    d = _record(
        url="https://t.co/abc123",
        entities={"url": {"urls": [{"expanded_url": "https://acme.com"}]},
                  "description": {"urls": []}},
    )
    assert _x_profile_website(d) == "https://acme.com"


def test_website_falls_back_to_bio_link():
    d = _record(entities={"description": {"urls": [{"expanded_url": "https://me.dev"}]}})
    assert _x_profile_website(d) == "https://me.dev"


def test_website_empty_when_none():
    assert _x_profile_website(_record()) == ""


def test_website_schemes_bare_raw_url():
    d = _record(url="acme.com", entities={})
    assert _x_profile_website(d) == "https://acme.com"


# ── Record → contact mapping ──────────────────────────────────────────────────

def test_contact_basic_fields():
    c = _x_follower_to_contact(_record(name="jane_doe", description="hi there"))
    assert c["handle"] == "ehrlichh"
    assert c["name"] == "Jane Doe"                       # _clean_name applied
    assert c["bio"] == "hi there"
    assert c["profiles"]["twitter"] == "https://twitter.com/ehrlichh"
    assert c["source"] == "social_scrape:x_followers"


def test_contact_inline_email_and_bio_email():
    c = _x_follower_to_contact(_record(
        email="inline@acme.com",
        description="reach me at bio@acme.com",
    ))
    assert c["emails"] == ["inline@acme.com", "bio@acme.com"]


def test_contact_no_handle_is_dropped():
    assert _x_follower_to_contact(_record(screen_name="")) is None


def test_items_dedupe_by_handle_and_cap():
    items = [
        _record(screen_name="a"),
        _record(screen_name="A"),     # same handle, different case → deduped
        _record(screen_name="b"),
        _record(screen_name=""),      # no handle → dropped
        _record(screen_name="c"),
    ]
    out = _x_followers_items_to_contacts(items, limit=2)
    assert [c["handle"] for c in out] == ["a", "b"]   # deduped, then capped at 2


# ── enrich_followers (scrape_followers monkeypatched) ─────────────────────────

def test_enrich_followers_shape_and_email_confidence():
    contacts = [
        {"handle": "a", "name": "A", "emails": ["a@x.com"], "phones": [],
         "external_url": "https://a.com", "profiles": {"twitter": "https://twitter.com/a"},
         "source": "social_scrape:x_followers"},
        {"handle": "b", "name": "B", "emails": [], "phones": [],
         "external_url": "", "profiles": {"twitter": "https://twitter.com/b"},
         "source": "social_scrape:x_followers"},
    ]
    # enrich_followers does `from .social_scraper import scrape_followers` at
    # call time, so patching the module attribute is picked up.
    import enrichment.social_scraper as ss
    saved = ss.scrape_followers
    ss.scrape_followers = lambda handle, token, limit=200: contacts
    try:
        res = pipeline.enrich_followers("Fanatics", limit=200, apify_token="tok",
                                        follow_bio_links=False)
    finally:
        ss.scrape_followers = saved

    assert set(res.keys()) == {"a", "b"}
    assert res["a"]["confidence"] == "medium"          # had an email
    assert res["a"]["profiles"]["website"] == "https://a.com"
    assert res["b"]["confidence"] == "none"            # no email, bio-follow off


def test_enrich_followers_no_token_returns_empty():
    assert pipeline.enrich_followers("Fanatics", apify_token=None) == {}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
