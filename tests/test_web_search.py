"""
Tests for the web-search enrichment fallback (enrichment.web_search). No test
framework, no network, and no API keys required — DuckDuckGo is replaced with a
fake module in sys.modules, and the page-fetch step (_scrape_generic) is
monkeypatched. Run directly:

    python3 tests/test_web_search.py

Covers the two yield improvements: capturing result URLs (not just snippets) +
broadened queries, and fetching the top pages when snippets carry no email.
"""

import contextlib
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichment import web_search
import enrichment.social_scraper as ss


# ── Fakes ─────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def fake_ddg(results, recorder=None):
    """Install a fake `duckduckgo_search` module whose DDGS.text() returns
    `results` for every query and records the queries it was asked."""
    class FakeDDGS:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, q, max_results=3):
            if recorder is not None:
                recorder.append(q)
            return list(results)

    mod = types.ModuleType("duckduckgo_search")
    mod.DDGS = FakeDDGS
    saved = sys.modules.get("duckduckgo_search")
    sys.modules["duckduckgo_search"] = mod
    try:
        yield
    finally:
        if saved is not None:
            sys.modules["duckduckgo_search"] = saved
        else:
            del sys.modules["duckduckgo_search"]


@contextlib.contextmanager
def patched_scrape_generic(fn):
    """Patch _scrape_generic on the social_scraper module — _fetch_pages imports
    it lazily from there, so the attribute swap is picked up."""
    saved = ss._scrape_generic
    ss._scrape_generic = fn
    try:
        yield
    finally:
        ss._scrape_generic = saved


def _r(body="", href=""):
    return {"body": body, "href": href}


# ── _ddg_search: URL capture + query breadth ──────────────────────────────────

def test_ddg_search_captures_urls_and_filters_social():
    results = [
        _r("Bookings: see site", "https://danielnegreanu.com/contact"),
        _r("on twitter", "https://twitter.com/RealKidPoker"),       # social → dropped
        _r("linkedin", "https://www.linkedin.com/in/dnegreanu"),    # social → dropped
        _r("link hub", "https://linktr.ee/dnegreanu"),
    ]
    with fake_ddg(results):
        out = web_search._ddg_search("Daniel Negreanu", "poker player")

    assert "https://danielnegreanu.com/contact" in out["urls"]
    assert "https://linktr.ee/dnegreanu" in out["urls"]
    assert not any("twitter.com" in u for u in out["urls"])
    assert not any("linkedin.com" in u for u in out["urls"])
    assert out["snippets"]                     # snippets still captured


def test_ddg_search_broadened_queries():
    recorder = []
    with fake_ddg([_r("x", "https://x.example/contact")], recorder):
        web_search._ddg_search("Jane Doe", "poker")

    assert len(recorder) >= 4                  # broadened beyond the original 2
    joined = " | ".join(recorder).lower()
    assert "email" in joined
    assert "contact" in joined
    assert "linktr.ee" in joined


# ── enrich_web: page-fetch behaviour ──────────────────────────────────────────

def test_page_fetch_finds_email_when_snippets_have_none():
    # Snippets carry no email; the fetched page does. This is the core win.
    results = [_r("No address in this snippet.", "https://janedoe.com/contact")]
    calls = []

    def fake_generic(url, anthropic_api_key=None, apify_token=None):
        calls.append(url)
        return {"emails": ["jane@janedoe.com"], "phones": []}

    with fake_ddg(results), patched_scrape_generic(fake_generic):
        out = web_search.enrich_web("Jane Doe", anthropic_api_key=None)

    assert out is not None
    assert out["emails"] == ["jane@janedoe.com"]
    assert "web_page" in out["source"]
    assert calls == ["https://janedoe.com/contact"]


def test_page_fetch_skipped_when_snippet_has_email():
    # Snippet already yields an email → no page fetch should happen.
    results = [_r("reach me at jane@janedoe.com anytime", "https://janedoe.com/contact")]

    def boom(*a, **k):
        raise AssertionError("_scrape_generic must not be called when snippet has an email")

    with fake_ddg(results), patched_scrape_generic(boom):
        out = web_search.enrich_web("Jane Doe", anthropic_api_key=None)

    assert out["emails"] == ["jane@janedoe.com"]
    assert out["source"] == ["web_search"]


def test_page_fetch_bounded_to_max_pages():
    # Many candidate URLs, none yielding an email → fetch capped at _MAX_PAGES.
    results = [_r("nothing", f"https://site{i}.com/contact") for i in range(6)]
    calls = []

    def fake_generic(url, anthropic_api_key=None, apify_token=None):
        calls.append(url)
        return None

    with fake_ddg(results), patched_scrape_generic(fake_generic):
        out = web_search.enrich_web("Jane Doe", anthropic_api_key=None)

    assert out is None                          # nothing found anywhere
    assert len(calls) == web_search._MAX_PAGES  # didn't fetch all 6


def test_fetch_failure_degrades_gracefully():
    results = [_r("no email here", "https://janedoe.com/contact")]

    def boom(*a, **k):
        raise RuntimeError("network down")

    with fake_ddg(results), patched_scrape_generic(boom):
        out = web_search.enrich_web("Jane Doe", anthropic_api_key=None)

    assert out is None                          # no crash, just no result


def test_no_search_results_returns_none():
    with fake_ddg([]):
        assert web_search.enrich_web("Nobody Here", anthropic_api_key=None) is None


def test_first_page_email_stops_second_fetch():
    results = [
        _r("none", "https://a.com/contact"),
        _r("none", "https://b.com/contact"),
    ]
    calls = []

    def fake_generic(url, anthropic_api_key=None, apify_token=None):
        calls.append(url)
        return {"emails": ["hit@a.com"], "phones": []} if "a.com" in url else None

    with fake_ddg(results), patched_scrape_generic(fake_generic):
        out = web_search.enrich_web("Jane Doe", anthropic_api_key=None)

    assert out["emails"] == ["hit@a.com"]
    assert calls == ["https://a.com/contact"]   # stopped after the hit


# ── runner ────────────────────────────────────────────────────────────────────

def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {fn.__name__}: {e!r}")
    if failed:
        print(f"\n{failed} of {len(fns)} tests FAILED.")
        sys.exit(1)
    print(f"\nAll {len(fns)} tests passed.")


if __name__ == "__main__":
    _run()
