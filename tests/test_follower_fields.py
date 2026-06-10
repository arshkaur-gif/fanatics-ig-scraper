"""
Tests for enrichment.follower_fields. No test framework required — run directly:

    python3 tests/test_follower_fields.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichment.follower_fields import enrich_follower, extract_links, split_name


def test_split_name():
    assert split_name("John Doe") == ("John", "Doe")
    assert split_name("Ana Beatriz Costa") == ("Ana", "Beatriz Costa")
    assert split_name("madonna") == ("madonna", "")
    assert split_name("", "cool_user") == ("cool_user", "")
    assert split_name("", "@handle") == ("handle", "")
    assert split_name("   ", "fallback") == ("fallback", "")
    # Emoji and surrounding punctuation stripped
    assert split_name("🔥 Jane  Mary Smith ✨") == ("Jane", "Mary Smith")
    assert split_name("José García-López") == ("José", "García-López")


def test_extract_links():
    assert extract_links("", "") == []
    assert extract_links("no links here", "") == []
    # external_url is normalized and comes first
    assert extract_links("", "mysite.com") == ["https://mysite.com"]
    # URLs pulled from bio text, de-duplicated with external_url
    assert extract_links("visit http://x.com/foo", "x.com/foo") == ["https://x.com/foo"]
    links = extract_links("portfolio at www.ana.com and http://blog.ana.com", "")
    assert links == ["https://www.ana.com", "http://blog.ana.com"]
    # Bare domains (common in Twitter/IG bios) are caught
    assert extract_links("designer · portfolio jane.design", "") == ["https://jane.design"]
    assert extract_links("shop linktr.ee/me today", "") == ["https://linktr.ee/me"]
    # Emails are NOT treated as links
    assert extract_links("reach me at hi@jane.design", "") == []
    # Period-separated bio phrases (unknown TLDs) are skipped
    assert extract_links("Eat.Sleep.Repeat", "") == []
    assert extract_links("coffee vs.tea debate", "") == []


def test_enrich_follower():
    rec = enrich_follower({
        "full_name": "Ana Beatriz Costa",
        "username": "ana",
        "biography": "photographer www.ana.com",
        "location": "Rio, Brazil",
    })
    assert rec["first_name"] == "Ana"
    assert rec["last_name"] == "Beatriz Costa"
    assert rec["bio"] == "photographer www.ana.com"
    assert rec["location"] == "Rio, Brazil"
    assert rec["links"] == ["https://www.ana.com"]

    # IG-style record: name from full_name, no location, link from external_url
    ig = enrich_follower({
        "full_name": "John Doe",
        "username": "jdoe",
        "biography": "just here",
        "externalUrl": "https://linktr.ee/jdoe",
    })
    assert (ig["first_name"], ig["last_name"]) == ("John", "Doe")
    assert ig["location"] == ""
    assert ig["links"] == ["https://linktr.ee/jdoe"]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failures else 0)
