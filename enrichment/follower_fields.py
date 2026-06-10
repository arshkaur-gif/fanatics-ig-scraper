"""
Per-follower field extraction.

Pure functions (no network) shared by the Instagram and Twitter follower
scrapers. Given a follower's raw fields, derive:

  first_name, last_name  — split from the display/full name
  links                  — actual URLs (external_url + any found in the bio)
  bio, location          — passed through as-is

`location` is only populated for Twitter (explicit profile field). Extracting
location *from* the bio text is a deliberate later phase (LLM layer).
"""

from __future__ import annotations

import re

# Pull URLs out of free text. Two passes:
#   1. explicit URLs (http(s):// or www.) — same as social_scraper.
#   2. bare domains (jane.design, linktr.ee/x) — common in Twitter/IG bios.
_URL_RE = re.compile(r'(?:https?://|www\.)[^\s,)>\'"<\]]+', re.IGNORECASE)
_BARE_DOMAIN_RE = re.compile(
    r'\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}'
    r'(?:/[^\s,)>\'"<\]]*)?',
    re.IGNORECASE,
)
# Emails first, so their domain part isn't mistaken for a bare-domain link.
_EMAIL_RE = re.compile(r'[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}', re.IGNORECASE)
# Only treat a bare domain as a link when its TLD is in this allowlist — keeps
# period-separated bio phrases ("Eat.Sleep.Repeat") from matching as domains.
# Covers common gTLDs + country codes used as domain hacks (linktr.ee, bit.ly).
_LINK_TLDS = frozenset([
    "com", "net", "org", "io", "co", "me", "tv", "gg", "xyz", "app", "dev",
    "design", "link", "bio", "site", "shop", "store", "blog", "info", "page",
    "online", "live", "studio", "art", "photo", "media", "news", "club", "fm",
    "fan", "ai", "gl", "gd", "ly", "to", "sh", "st", "ee", "am", "us", "uk",
    "ca", "au", "de", "fr", "es", "it", "nl", "eu", "in", "tech",
])

# Leading/trailing junk to strip off a matched URL.
_URL_TRIM = ".,;)>]\"'"

# Emoji / pictographic ranges to strip from names.
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿️]"
)


def split_name(full_name: str, username: str = "") -> tuple[str, str]:
    """
    Split a display/full name into (first, last).

    - Emoji and surrounding punctuation are stripped first.
    - first = first whitespace-delimited token, last = the rest joined.
    - Empty/blank name falls back to (username, "").
    """
    cleaned = _EMOJI_RE.sub("", full_name or "")
    # Collapse separators and trim stray punctuation around tokens.
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n.-_|·•")
    parts = [p for p in cleaned.split(" ") if p]

    if not parts:
        return ((username or "").strip().lstrip("@"), "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


def extract_links(bio: str, external_url="") -> list[str]:
    """
    Return the actual URLs for a follower: the explicit external link(s) (if any)
    plus every URL/bare domain found in the bio text, de-duplicated and
    scheme-normalized. Email addresses are excluded.

    `external_url` may be a single URL string or a list of them (e.g. Instagram's
    `externalUrls` array, where each entry can be a {"url": ...} dict or a string).
    """
    links: list[str] = []
    seen: set[str] = set()

    def _add(url: str) -> None:
        url = (url or "").strip().rstrip(_URL_TRIM)
        if not url:
            return
        if not url.startswith("http"):
            url = "https://" + url
        # De-dupe ignoring scheme and a trailing slash (http vs https, /foo vs /foo/).
        key = re.sub(r"^https?://", "", url).rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            links.append(url)

    externals = external_url if isinstance(external_url, (list, tuple)) else [external_url]
    for ext in externals:
        if isinstance(ext, dict):
            ext = ext.get("url") or ext.get("link") or ""
        _add(ext)

    # Drop emails so their domain isn't matched as a bare-domain link.
    text = _EMAIL_RE.sub(" ", bio or "")
    for match in _URL_RE.findall(text):
        _add(match)
    for match in _BARE_DOMAIN_RE.findall(text):
        tld = match.split("/")[0].rsplit(".", 1)[-1].lower()
        if tld in _LINK_TLDS:
            _add(match)

    return links


def enrich_follower(record: dict) -> dict:
    """
    Attach derived fields to a follower record (mutates and returns it).

    Reads:  full_name (or name), username, biography (or bio), external_url, location
    Writes: first_name, last_name, bio, location, links
    """
    full_name = record.get("full_name") or record.get("name") or ""
    username = record.get("username") or ""
    bio = record.get("biography") or record.get("bio") or ""
    external_url = record.get("external_url") or record.get("externalUrl") or ""
    location = record.get("location") or ""

    first, last = split_name(full_name, username)
    record["first_name"] = first
    record["last_name"] = last
    record["bio"] = bio
    record["location"] = location
    record["links"] = extract_links(bio, external_url)
    return record
