"""
Tests for app._parse_usernames — the handle/URL normalizer behind /api/scrape.
Importing `app` pulls in Flask (a declared dependency) but makes no network
calls at import time. Run directly:

    python3 tests/test_parse_usernames.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import _parse_usernames


def test_plain_comma_list():
    assert _parse_usernames("alice, bob ,charlie") == ["alice", "bob", "charlie"]


def test_strips_at_sign():
    assert _parse_usernames("@alice, @bob") == ["alice", "bob"]


def test_extracts_handle_from_url():
    assert _parse_usernames("https://instagram.com/dave/") == ["dave"]
    assert _parse_usernames("https://www.instagram.com/eve") == ["eve"]


def test_drops_bare_domain_with_no_handle():
    assert _parse_usernames("instagram.com/") == []
    assert _parse_usernames("www.instagram.com") == []


def test_empty_and_whitespace():
    assert _parse_usernames("") == []
    assert _parse_usernames("   ,  ,") == []


def test_mixed_input():
    out = _parse_usernames("@alice, https://instagram.com/bob/, carol")
    assert out == ["alice", "bob", "carol"]


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
