"""
Airtable-backed reader for the curated Hendon Mob dataset.

This is the runtime source of truth for the UI's "Hendon Mob database" mode
(the ~85k US players, $10k–$1M total earnings). It mirrors the read side of
``hendon_store`` but talks to Airtable instead of SQLite.

Config (env):
    AIRTABLE_API_KEY      personal access token, scope ``data.records:read``
    AIRTABLE_BASE_ID      e.g. ``appXXXXXXXXXXXXXX``
    AIRTABLE_TABLE_NAME   table name or id (default "Players")

``FIELDS`` maps our internal keys to the Airtable column names — edit it here if
your columns are named differently.

The numeric columns (``earnings``, ``recent_earnings``) are stored as currency
*text* ("$ 21,505") and ``last_cash_date`` as an ISO date *string*, so all
filtering is pushed into the Airtable ``filterByFormula`` using ``VALUE`` +
``SUBSTITUTE`` (text → number) and ``DATETIME_PARSE`` (text → date). That way the
API returns only matching rows instead of the whole 85k-row table.
"""

from __future__ import annotations

import json
import os
import re

# Internal key -> Airtable column name. Defaults match the live `hendonmob` table.
FIELDS = {
    "rank":            "rank",
    "name":            "name",
    "country":         "country",
    "earnings":        "earnings",
    "recent_earnings": "recent_earnings",
    "last_cash_date":  "last_cash_date",
    "city_state":      "city_state",
    "socials":         "socials",
    "profile_url":     "profile_url",
}


def _config() -> tuple[str, str, str]:
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    table = os.getenv("AIRTABLE_TABLE_NAME", "Players")
    missing = [n for n, v in (("AIRTABLE_API_KEY", api_key), ("AIRTABLE_BASE_ID", base_id)) if not v]
    if missing:
        raise RuntimeError(
            "Airtable is not configured — set " + " and ".join(missing) + " in your .env"
        )
    return api_key, base_id, table


def _fmt_num(v: float) -> str:
    """Format a number for a formula literal (drop a trailing .0)."""
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def _esc(value: str) -> str:
    """Escape a string for an Airtable formula single-quoted literal."""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _num_expr(col: str) -> str:
    """Airtable expression that parses a currency-text column to a number."""
    return f"VALUE(SUBSTITUTE(SUBSTITUTE(SUBSTITUTE({{{col}}},'$',''),',',''),' ',''))"


def _build_formula(*, earnings_min, earnings_max, recent_min, recent_max,
                   months_active, states, has_social) -> str:
    clauses: list[str] = []

    earn = _num_expr(FIELDS["earnings"])
    if earnings_min is not None:
        clauses.append(f"{earn} >= {_fmt_num(earnings_min)}")
    if earnings_max is not None:
        clauses.append(f"{earn} <= {_fmt_num(earnings_max)}")

    recent = _num_expr(FIELDS["recent_earnings"])
    if recent_min is not None:
        clauses.append(f"{recent} >= {_fmt_num(recent_min)}")
    if recent_max is not None:
        clauses.append(f"{recent} <= {_fmt_num(recent_max)}")

    if months_active and months_active > 0:
        col = FIELDS["last_cash_date"]
        clauses.append(
            f"IS_AFTER(DATETIME_PARSE({{{col}}}, 'YYYY-MM-DD'), "
            f"DATEADD(TODAY(), -{int(months_active)}, 'months'))"
        )

    if states:
        col = FIELDS["city_state"]
        # city_state looks like "New York, NY" — match the trailing 2-letter code.
        ors = [f"RIGHT({{{col}}}, 2) = '{_esc(s.upper())}'" for s in states]
        clauses.append(ors[0] if len(ors) == 1 else "OR(" + ", ".join(ors) + ")")

    if has_social:
        clauses.append(f"NOT({{{FIELDS['socials']}}} = '')")

    if not clauses:
        return ""
    return clauses[0] if len(clauses) == 1 else "AND(" + ", ".join(clauses) + ")"


def _year_from_date(value) -> int | None:
    if not value:
        return None
    m = re.search(r"\d{4}", str(value))
    return int(m.group(0)) if m else None


def _rank_int(value) -> int | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits) if digits else None


def _normalize(fields: dict) -> dict:
    """Shape an Airtable record's fields like the UI table expects."""
    socials = fields.get(FIELDS["socials"]) or {}
    if isinstance(socials, str):
        s = socials.strip()
        if not s:
            socials = {}
        elif s.startswith("{"):
            try:
                socials = json.loads(s)
            except (ValueError, TypeError):
                socials = {}
        elif s.startswith("http"):
            # Bare profile URL (the Hendon Mob "socials" column is a twitter link).
            net = "twitter" if "/twitter/" in s else "profile"
            socials = {net: s}
        else:
            socials = {}
    return {
        "rank": _rank_int(fields.get(FIELDS["rank"])),
        "name": fields.get(FIELDS["name"], ""),
        "country": fields.get(FIELDS["country"], "United States"),
        "metric": fields.get(FIELDS["earnings"], "") or "",
        "profile_url": fields.get(FIELDS["profile_url"], ""),
        "city_state": fields.get(FIELDS["city_state"], ""),
        "last_active_year": _year_from_date(fields.get(FIELDS["last_cash_date"])),
        "last_cash_date": fields.get(FIELDS["last_cash_date"], "") or "",
        "recent_earnings": fields.get(FIELDS["recent_earnings"], "") or "",
        "profiles": socials if isinstance(socials, dict) else {},
    }


def query_players(*, earnings_min: float | None = None, earnings_max: float | None = None,
                  recent_min: float | None = None, recent_max: float | None = None,
                  months_active: int = 0, states: list[str] | None = None,
                  has_social: bool = False, limit: int | None = None) -> list[dict]:
    """
    Read matching players from Airtable, normalized to the UI record shape and
    sorted by numeric rank.

    All filters are optional; passing none returns the whole table (large/slow).
    Filtering runs entirely in the Airtable formula, so only matching rows are
    fetched.
    """
    from pyairtable import Api

    api_key, base_id, table_name = _config()
    table = Api(api_key).table(base_id, table_name)

    formula = _build_formula(
        earnings_min=earnings_min, earnings_max=earnings_max,
        recent_min=recent_min, recent_max=recent_max,
        months_active=months_active, states=states or [], has_social=has_social,
    )

    kwargs: dict = {}
    if formula:
        kwargs["formula"] = formula
    if limit:
        kwargs["max_records"] = int(limit)

    rows = [_normalize(rec.get("fields", {})) for rec in table.all(**kwargs)]
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))
    return rows
