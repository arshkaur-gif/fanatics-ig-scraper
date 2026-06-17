"""
Tests for scraper.airtable_store formula building + record normalization.

These run offline — `_build_formula`, `_esc`, `_normalize` and friends do no
network I/O (pyairtable is imported lazily inside query_players, not at module
load). The escaping tests double as a regression guard against formula
injection: `states` is the one string value interpolated into a filterByFormula
literal, so a quote in it must be escaped, not break out of the literal.

    python3 tests/test_airtable_store.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.airtable_store import (
    _build_formula,
    _esc,
    _fmt_num,
    _normalize,
    _rank_int,
    _year_from_date,
    FIELDS,
)


def _f(**kw):
    base = dict(
        earnings_min=None, earnings_max=None, recent_min=None, recent_max=None,
        months_active=0, states=[], has_social=False,
    )
    base.update(kw)
    return _build_formula(**base)


def test_no_filters_returns_empty():
    assert _f() == ""


def test_single_clause_not_wrapped_in_and():
    out = _f(earnings_min=1000)
    assert out.startswith("VALUE(")
    assert ">= 1000" in out
    assert not out.startswith("AND(")


def test_multiple_clauses_wrapped_in_and():
    out = _f(earnings_min=1000, earnings_max=5000)
    assert out.startswith("AND(")
    assert ">= 1000" in out and "<= 5000" in out


def test_state_filter_uppercased_and_escaped():
    out = _f(states=["ny"])
    assert "RIGHT(" in out
    assert "'NY'" in out


def test_multiple_states_use_or():
    out = _f(states=["ny", "ca"])
    assert "OR(" in out
    assert "'NY'" in out and "'CA'" in out


def test_esc_escapes_single_quote_injection():
    # The core injection-defense assertion: a quote in a state value must be
    # backslash-escaped so it can't terminate the formula literal early.
    assert _esc("a'b") == "a\\'b"
    assert _esc("x\\y") == "x\\\\y"
    # End to end: a state value crafted to break out of the literal and inject a
    # second clause stays trapped inside one quoted literal. The injected quote is
    # escaped (\'), and the whole thing remains a single RIGHT(...) = '...' clause.
    out = _f(states=["n'y) , 1, 1) OR (1"])
    assert "\\'Y" in out                                  # the breakout quote got escaped
    assert out.startswith("RIGHT({city_state}, 2) = '")   # one clause...
    assert out.endswith("'")                              # ...still a closed literal
    assert "), " not in out                               # no second top-level clause injected


def test_fmt_num_drops_trailing_zero():
    assert _fmt_num(1000.0) == "1000"
    assert _fmt_num(1000) == "1000"
    assert _fmt_num(12.5) == "12.5"


def test_months_active_uses_int():
    out = _f(months_active=6)
    assert "-6, 'months'" in out
    assert "DATETIME_PARSE" in out


def test_has_social_clause():
    out = _f(has_social=True)
    assert f"NOT({{{FIELDS['socials']}}} = '')" in out


def test_rank_int_strips_non_digits():
    assert _rank_int("#1,234") == 1234
    assert _rank_int("") is None
    assert _rank_int(None) is None
    assert _rank_int("abc") is None


def test_year_from_date():
    assert _year_from_date("2023-05-01") == 2023
    assert _year_from_date("") is None
    assert _year_from_date(None) is None


def test_normalize_parses_json_socials():
    rec = {
        "rank": "5", "name": "Jane Doe", "earnings": "$ 1,000",
        "socials": '{"twitter": "https://twitter.com/jane"}',
        "last_cash_date": "2024-03-02",
    }
    out = _normalize(rec)
    assert out["rank"] == 5
    assert out["name"] == "Jane Doe"
    assert out["profiles"] == {"twitter": "https://twitter.com/jane"}
    assert out["last_active_year"] == 2024


def test_normalize_handles_bare_url_socials():
    # A bare URL with no "/twitter/" segment is labelled the generic "profile".
    out = _normalize({"socials": "https://twitter.com/joe"})
    assert out["profiles"] == {"profile": "https://twitter.com/joe"}
    # The Hendon Mob "socials" column uses ".../twitter/<handle>" — that maps to twitter.
    out2 = _normalize({"socials": "https://www.thehendonmob.com/twitter/joe"})
    assert out2["profiles"] == {"twitter": "https://www.thehendonmob.com/twitter/joe"}


def test_normalize_handles_empty_and_garbage_socials():
    assert _normalize({"socials": ""})["profiles"] == {}
    assert _normalize({"socials": "not json"})["profiles"] == {}
    assert _normalize({"socials": "{bad json"})["profiles"] == {}


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
