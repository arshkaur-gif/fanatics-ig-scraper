"""
Extract a location from a social profile bio.

Instagram exposes no location field at all, and many Twitter users leave the
profile `location` blank while still stating where they are in their bio. This
module derives a single display string (e.g. "Las Vegas, NV") from free-text
bio content. It is the "LLM layer" deferred by follower_fields.py / app.py.

Hybrid strategy, cheapest first:
  Pass 1 — regex/heuristic, free, no network: pin-emoji prefixes, flag emoji,
           and `City, ST` / `City, Country` patterns.
  Pass 2 — gpt-4o-mini fallback, only when pass 1 finds nothing AND an
           OpenAI key is available AND the bio is non-trivial. Mirrors the
           existing _llm_extract() in social_scraper.py.

`extract_location` never raises and returns "" when no location is found.
"""

from __future__ import annotations

import json
import re

# Pin-style emoji that reliably prefix a location: 📍 pin, 🗺 map, 🏠 home.
# Globe emoji (🌍🌎🌏) are deliberately excluded — they're decorative far more
# often than they mark a location ("🌎Amazing Racer").
_PIN_RE = re.compile(r"[\U0001F4CD\U0001F5FA\U0001F3E0]+\s*")
# A pair of regional-indicator symbols = a flag emoji (e.g. 🇬🇧).
_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}\s*")
# Separators that terminate a location run inside a single-line bio.
_SEP_RE = re.compile(r"\s*[|•·\n\r]\s*")
# Strip remaining emoji/pictographs from a candidate (same ranges as follower_fields).
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿️]"
)
_TRIM = " \t\r\n.-_|·•,"

# US state / territory postal abbreviations — used to recognise "City, ST".
_US_STATES = frozenset([
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR",
])

# Known country names / common short forms — the only second-halves accepted for
# the "City, Country" pattern. Keeps "Poker, Travel" / "CEO, Founder" from matching.
_COUNTRIES = frozenset(s.lower() for s in [
    "USA", "US", "U.S.", "U.S.A.", "America", "Canada", "Mexico", "Brazil",
    "Argentina", "UK", "U.K.", "England", "Scotland", "Wales", "Ireland",
    "France", "Germany", "Spain", "Portugal", "Italy", "Netherlands", "Belgium",
    "Switzerland", "Austria", "Sweden", "Norway", "Denmark", "Finland", "Poland",
    "Greece", "Russia", "Ukraine", "Turkey", "Israel", "UAE", "India", "China",
    "Japan", "Korea", "Australia", "New Zealand", "Singapore", "Philippines",
    "Indonesia", "Thailand", "Vietnam", "Malaysia", "Nigeria", "Kenya",
    "South Africa", "Egypt", "Colombia", "Chile", "Peru", "Czechia", "Hungary",
    "Romania", "Croatia",
])

# "City, ST" — a place name followed by a 2-letter US state code (word boundary).
_CITY_STATE_RE = re.compile(
    r"\b([A-Z][A-Za-z.\-]+(?:[ '][A-Z][A-Za-z.\-]+){0,3}),\s*([A-Z]{2})\b"
)
# "City, Country" — capitalised place + comma + (validated) country name.
_CITY_COUNTRY_RE = re.compile(
    r"\b([A-Z][A-Za-z.\-]+(?:[ '][A-Z][A-Za-z.\-]+){0,2}),\s*"
    r"([A-Z][A-Za-z.\-]+(?:[ '][A-Z][A-Za-z.\-]+){0,2})\b"
)


def _clean(text: str) -> str:
    """Strip emoji, collapse whitespace, trim stray punctuation."""
    text = _EMOJI_RE.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip(_TRIM)
    return text


def _looks_like_place(text: str) -> bool:
    """
    Guard against grabbing prose as a location. A real place name is short and
    free of handles/URLs, so reject segments that are long, multi-clause, or
    contain @ / http / a slash (e.g. decorative emoji followed by bio prose like
    "@GGPoker Ambassador Join me @ https://...").
    """
    if not text or len(text) > 40:
        return False
    if "@" in text or "/" in text or "http" in text.lower():
        return False
    return len(text.split()) <= 6


def _emoji_segments(bio: str, splitter: re.Pattern) -> str:
    """
    Split a bio on a location-marker emoji (pin or flag) and join the place
    name following each marker. Each marker delimits a separate location, so a
    bio like "📍West Adams📍Pasadena" yields "West Adams, Pasadena" rather than
    one run-together string. Each segment is cut at the next text separator
    (|, •, ·, newline). Returns "" when the marker is absent.
    """
    parts = splitter.split(bio)
    if len(parts) < 2:  # marker not present (parts[0] is the pre-marker text)
        return ""
    out: list[str] = []
    seen: set[str] = set()
    for seg in parts[1:]:
        seg = _clean(_SEP_RE.split(seg, 1)[0])
        if _looks_like_place(seg) and seg.lower() not in seen:
            seen.add(seg.lower())
            out.append(seg)
    return ", ".join(out)


def _regex_location(bio: str) -> str:
    """Pass 1: pull a location from a bio using free heuristics. "" if none."""
    if not bio:
        return ""

    # 1. Pin emoji (📍) markers: join the place after each pin.
    pinned = _emoji_segments(bio, _PIN_RE)
    if pinned:
        return pinned

    # 2. Flag emoji markers: join the place after each flag.
    flagged = _emoji_segments(bio, _FLAG_RE)
    if flagged:
        return flagged

    # 3. "City, ST" with a known US state code.
    for city, st in _CITY_STATE_RE.findall(bio):
        if st in _US_STATES:
            return f"{_clean(city)}, {st}"

    # 4. "City, Country" — only when the second half is a recognised country,
    #    so generic phrases ("Poker, Travel") don't match. Anything else falls
    #    through to the LLM fallback.
    for city, country in _CITY_COUNTRY_RE.findall(bio):
        if country.lower().rstrip(".") in _COUNTRIES:
            return f"{_clean(city)}, {_clean(country)}"

    return ""


def _llm_location(bio: str, api_key: str) -> str:
    """Pass 2: ask gpt-4o-mini for the location. "" on any failure."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    "Extract the person's home location (city/region/country) from "
                    "this social media bio, ONLY if they state where they are based "
                    "or located. Do not infer from team names, brands, or hashtags.\n"
                    'Return JSON only: {"location": "..."} — use an empty string if '
                    "no location is stated.\n\n" + bio
                ),
            }],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        return (data.get("location") or "").strip()
    except Exception:
        return ""


def extract_location(bio: str, openai_api_key: str | None = None) -> str:
    """
    Return a location display string parsed from `bio`, or "" if none found.

    Tries free regex heuristics first; only falls back to gpt-4o-mini when those
    find nothing, an OpenAI key is supplied, and the bio has enough text to be
    worth a call. Never raises.

    Future optimization: batch the LLM fallback across many bios in one call
    rather than one request per unresolved bio.
    """
    bio = (bio or "").strip()
    if not bio:
        return ""

    found = _regex_location(bio)
    if found:
        return found

    if openai_api_key and len(bio) >= 3:
        return _llm_location(bio, openai_api_key)

    return ""
