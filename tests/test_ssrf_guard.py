"""
Tests for the SSRF / local-file-read guard on server-side fetches
(enrichment.social_scraper). No test framework or network required — every case
uses a literal IP or `localhost`, so getaddrinfo resolves offline. Run directly:

    python3 tests/test_ssrf_guard.py

Why this matters: `/api/enrich-contacts` feeds a caller-supplied `instagram_url`
into `scrape_profile` → `_scrape_generic`, which fetches the URL from this
server. Without the guard that is an SSRF + local-file-read primitive.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichment.social_scraper import (
    _SafeRedirectHandler,
    _safe_urlopen,
    _scrape_generic,
    _url_is_fetchable,
)


def test_non_http_schemes_blocked():
    for url in (
        "file:///etc/passwd",
        "file://localhost/etc/passwd",
        "ftp://example.com/secret",
        "gopher://127.0.0.1:25/",
        "data:text/plain,hello",
        "//8.8.8.8/",          # scheme-relative → no scheme
        "8.8.8.8",             # bare host, no scheme
    ):
        assert _url_is_fetchable(url) is False, url


def test_private_and_special_ips_blocked():
    for url in (
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://localhost/",
        "http://10.0.0.5/",
        "http://10.255.255.255/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://172.31.255.255/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[::1]/",
        "http://0.0.0.0/",
    ):
        assert _url_is_fetchable(url) is False, url


def test_public_http_urls_allowed():
    # Literal public IPs so the check is deterministic without DNS.
    for url in ("http://8.8.8.8/", "https://1.1.1.1/", "https://8.8.4.4/path?q=1"):
        assert _url_is_fetchable(url) is True, url


def test_malformed_urls_blocked():
    for url in ("", "not a url", "http://", "https://", "http:///nohost"):
        assert _url_is_fetchable(url) is False, url


def test_safe_urlopen_raises_on_blocked():
    for url in ("file:///etc/passwd", "http://169.254.169.254/", "http://127.0.0.1/"):
        try:
            _safe_urlopen(url)
            assert False, f"expected ValueError for {url}"
        except ValueError:
            pass


def test_scrape_generic_does_not_read_local_files():
    # The whole point: a file:// (or internal) URL must yield nothing, never the
    # file's contents. /etc/hosts exists on the CI box but must not be scraped.
    assert _scrape_generic("file:///etc/passwd") is None
    assert _scrape_generic("file:///etc/hosts") is None
    assert _scrape_generic("http://127.0.0.1:1/") is None


class _FakeReq:
    """Minimal stand-in for the (req, fp, code, msg, headers) redirect args."""
    full_url = "https://8.8.8.8/"
    def get_full_url(self):
        return self.full_url


def test_redirect_handler_blocks_internal_target():
    handler = _SafeRedirectHandler()
    # Redirecting to an internal/non-http target must return None (stop following).
    assert handler.redirect_request(
        _FakeReq(), None, 302, "Found", {}, "http://169.254.169.254/"
    ) is None
    assert handler.redirect_request(
        _FakeReq(), None, 302, "Found", {}, "file:///etc/passwd"
    ) is None


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
