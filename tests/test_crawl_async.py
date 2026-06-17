"""
Tests for the async website-content-crawler path (start + poll). No test
framework and NO Apify credits required — a fake client stands in for the
Apify SDK, so the state machine, dataset shaping, and route gating are all
exercised offline. Run directly:

    python3 tests/test_crawl_async.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichment.social_scraper import (
    _crawl_items_to_result,
    _crawler_fallback_enabled,
    _crawler_run_input,
    fetch_crawl_result,
    start_website_crawl,
)


# ── Fake Apify client (no network, no credits) ───────────────────────────────

class _FakeDataset:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        return iter(self._items)


class _FakeActorHandle:
    def __init__(self, parent):
        self._parent = parent

    def start(self, run_input=None):
        self._parent.started_input = run_input
        return {"id": "run_abc123"}  # returns immediately, like .start()


class _FakeRunHandle:
    def __init__(self, run):
        self._run = run

    def get(self):
        return self._run


class FakeClient:
    """Mimics the slice of ApifyClient that start/fetch use."""
    def __init__(self, run=None, items=None):
        self._run = run
        self._items = items or []
        self.started_input = None

    def actor(self, _actor_id):
        return _FakeActorHandle(self)

    def run(self, _run_id):
        return _FakeRunHandle(self._run)

    def dataset(self, _dataset_id):
        return _FakeDataset(self._items)


class _BoomClient:
    """A client whose SDK calls raise — exercises the except branches."""
    def actor(self, _actor_id):
        raise RuntimeError("apify is down")

    def run(self, _run_id):
        raise RuntimeError("apify is down")


# ── Tests ────────────────────────────────────────────────────────────────────

def test_run_input_shape():
    """startUrls must be a list of objects; crawlerType the namespaced enum."""
    ri = _crawler_run_input("https://example.org")
    assert ri["startUrls"] == [{"url": "https://example.org"}]
    assert ri["crawlerType"] == "playwright:adaptive"
    assert ri["maxCrawlPages"] == 5 and ri["maxCrawlDepth"] == 1


def test_start_returns_run_id():
    client = FakeClient()
    run_id = start_website_crawl("https://example.org", "tok", client=client)
    assert run_id == "run_abc123"
    # the input actually sent to the actor is the shared run-input
    assert client.started_input["startUrls"] == [{"url": "https://example.org"}]


def test_poll_while_running_has_no_result():
    client = FakeClient(run={"status": "RUNNING", "defaultDatasetId": "ds1"})
    out = fetch_crawl_result("run_abc123", "tok", client=client)
    assert out == {"status": "RUNNING", "result": None}


def test_poll_succeeded_extracts_contacts():
    items = [
        {
            "url": "https://example.org/contact",
            "markdown": "Reach us at hello@example.org or call 415-555-0100.",
            "metadata": {"title": "Acme Poker"},
        },
        {"url": "https://example.org/about", "markdown": "About Acme."},
    ]
    client = FakeClient(run={"status": "SUCCEEDED", "defaultDatasetId": "ds1"}, items=items)
    out = fetch_crawl_result("run_abc123", "tok", client=client)
    assert out["status"] == "SUCCEEDED"
    res = out["result"]
    assert "hello@example.org" in res["emails"]
    assert any("555-0100" in p for p in res["phones"])
    assert res["name"] == "Acme Poker"          # from metadata.title
    assert res["external_url"] == "https://example.org/contact"  # first item's url


def test_poll_succeeded_but_no_contacts_returns_none_result():
    items = [{"url": "https://example.org", "markdown": "Just some prose, no contacts."}]
    client = FakeClient(run={"status": "SUCCEEDED", "defaultDatasetId": "ds1"}, items=items)
    out = fetch_crawl_result("run_abc123", "tok", client=client)
    assert out["status"] == "SUCCEEDED"
    assert out["result"] is None  # crawl finished, but nothing extractable (no LLM key)


def test_poll_missing_run():
    client = FakeClient(run=None)
    out = fetch_crawl_result("nope", "tok", client=client)
    assert out["status"] == "NOT_FOUND" and out["result"] is None


def test_items_to_result_handles_empty():
    assert _crawl_items_to_result([], None) is None
    assert _crawl_items_to_result([{"markdown": "   "}], None) is None


def test_route_gating_off_by_default():
    """With the flag unset, both routes must refuse (503) before touching Apify."""
    os.environ.pop("ENABLE_CRAWLER_FALLBACK", None)
    import app as flask_app
    client = flask_app.app.test_client()
    for path in ("/api/crawl-start", "/api/crawl-status"):
        resp = client.post(path, json={"url": "https://example.org", "run_id": "x"})
        assert resp.status_code == 503, f"{path} should be gated off, got {resp.status_code}"


def test_start_returns_none_on_failure():
    """SDK error during .start() is swallowed → None, never raised to the route."""
    assert start_website_crawl("https://example.org", "tok", client=_BoomClient()) is None


def test_start_returns_none_when_no_run_id():
    """A run object without an id (e.g. odd SDK response) yields None, not a KeyError."""
    class _NoIdActor:
        def actor(self, _id): return self
        def start(self, run_input=None): return {}  # no "id"
    assert start_website_crawl("https://example.org", "tok", client=_NoIdActor()) is None


def test_fetch_error_path():
    """SDK error during polling is reported as status ERROR, not raised."""
    out = fetch_crawl_result("run_abc123", "tok", client=_BoomClient())
    assert out["status"] == "ERROR" and out["result"] is None
    assert "apify is down" in out.get("error", "")


def test_fallback_flag_parsing():
    """Only the truthy spellings enable the gate; everything else stays off."""
    for on in ("1", "true", "TRUE", "yes", "On", " true "):
        os.environ["ENABLE_CRAWLER_FALLBACK"] = on
        assert _crawler_fallback_enabled() is True, f"{on!r} should enable"
    for off in ("0", "false", "no", "", "maybe"):
        os.environ["ENABLE_CRAWLER_FALLBACK"] = off
        assert _crawler_fallback_enabled() is False, f"{off!r} should NOT enable"
    os.environ.pop("ENABLE_CRAWLER_FALLBACK", None)
    assert _crawler_fallback_enabled() is False  # unset → off


def test_items_to_result_uses_fallback_url_when_item_has_none():
    """external_url falls back to the requested URL when the item carries no url."""
    items = [{"markdown": "Mail me: hi@acme.org"}]  # no "url" key
    res = _crawl_items_to_result(items, None, fallback_url="https://acme.org")
    assert res is not None
    assert res["external_url"] == "https://acme.org"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
