"""
SQLite-backed cache for Hendon Mob harvesting.

Keyed by `player_id` (the `n=` value in a profile URL — a stable unique id), so
the harvest is resumable and idempotent: re-running the roster phase updates
standings without touching already-scraped profile data, and the profile phase
only visits players that haven't been enriched yet (the work queue).

One row per player:
    player_id           stable id from the profile URL (primary key)
    rank, name, country, earnings, profile_url   from the ranking page
    city_state, profiles (JSON)                   from the profile page
    profile_scraped_at  ISO timestamp, NULL until the profile has been enriched
    roster_updated_at   ISO timestamp of the last roster upsert
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "hendon_mob.db")


def player_id_from_url(profile_url: str) -> str | None:
    """Extract the stable player id (the `n=` param) from a profile URL."""
    if not profile_url:
        return None
    m = re.search(r"[?&]n=(\d+)", profile_url)
    return m.group(1) if m else None


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (creating if needed) the cache DB and ensure the schema exists."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # safer concurrent reads while writing
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            player_id          TEXT PRIMARY KEY,
            rank               INTEGER,
            name               TEXT,
            country            TEXT,
            earnings           TEXT,
            profile_url        TEXT,
            city_state         TEXT,
            profiles           TEXT,
            last_cash_date     TEXT,
            recent_earnings    TEXT,
            profile_scraped_at TEXT,
            roster_updated_at  TEXT
        )
        """
    )
    # Migrate older DBs created before the results columns existed.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    for col in ("last_cash_date", "recent_earnings"):
        if col not in existing:
            conn.execute(f"ALTER TABLE players ADD COLUMN {col} TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scraped ON players(profile_scraped_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_country ON players(country)")
    conn.commit()
    return conn


def upsert_roster(conn: sqlite3.Connection, players: list[dict]) -> int:
    """
    Insert/update ranking-page rows, keyed by player_id.

    Updates rank/name/country/earnings/profile_url on conflict but deliberately
    leaves city_state/profiles/profile_scraped_at alone so enrichment survives a
    roster refresh. Rows without a derivable player_id are skipped. Returns the
    number of rows written.
    """
    now = datetime.utcnow().isoformat()
    rows = []
    for p in players:
        pid = player_id_from_url(p.get("profile_url", ""))
        if not pid:
            continue
        rows.append((
            pid, p.get("rank"), p.get("name", ""), p.get("country", ""),
            p.get("earnings", ""), p.get("profile_url", ""), now,
        ))
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO players
            (player_id, rank, name, country, earnings, profile_url, roster_updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            rank=excluded.rank,
            name=excluded.name,
            country=excluded.country,
            earnings=excluded.earnings,
            profile_url=excluded.profile_url,
            roster_updated_at=excluded.roster_updated_at
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def pending_profiles(conn: sqlite3.Connection, limit: int | None = None,
                     country: str | None = None,
                     refresh_after_days: int | None = None) -> list[sqlite3.Row]:
    """
    Return the profile work queue: players not yet enriched (or stale).

    `country` restricts to one nationality (so we don't visit profiles we'll
    discard). `refresh_after_days` also re-queues rows last scraped longer ago
    than that. `limit` caps the batch for incremental runs.
    """
    where = ["profile_url IS NOT NULL AND profile_url != ''"]
    params: list = []
    if refresh_after_days is not None:
        cutoff = (datetime.utcnow() - timedelta(days=refresh_after_days)).isoformat()
        where.append("(profile_scraped_at IS NULL OR profile_scraped_at < ?)")
        params.append(cutoff)
    else:
        where.append("profile_scraped_at IS NULL")
    if country:
        where.append("country = ?")
        params.append(country)

    sql = f"SELECT * FROM players WHERE {' AND '.join(where)} ORDER BY rank"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def save_profile(conn: sqlite3.Connection, player_id: str, city_state: str,
                 profiles: dict, last_cash_date: str = "",
                 recent_earnings: str = "") -> None:
    """Write enrichment for one player and stamp profile_scraped_at."""
    conn.execute(
        "UPDATE players SET city_state=?, profiles=?, last_cash_date=?, "
        "recent_earnings=?, profile_scraped_at=? WHERE player_id=?",
        (city_state, json.dumps(profiles or {}), last_cash_date, recent_earnings,
         datetime.utcnow().isoformat(), player_id),
    )
    conn.commit()


def save_results(conn: sqlite3.Connection, player_id: str,
                 last_cash_date: str, recent_earnings: str) -> None:
    """
    Backfill only the results-derived fields on an already-enriched row,
    leaving profile_scraped_at (and the rest of the profile data) untouched.
    """
    conn.execute(
        "UPDATE players SET last_cash_date=?, recent_earnings=? WHERE player_id=?",
        (last_cash_date, recent_earnings, player_id),
    )
    conn.commit()


def rows_missing_results(conn: sqlite3.Connection, country: str | None = None,
                         limit: int | None = None) -> list[sqlite3.Row]:
    """
    Already-enriched rows that predate the results columns (the backfill queue):
    a profile was scraped but last_cash_date was never populated.
    """
    where = ["profile_scraped_at IS NOT NULL",
             "(last_cash_date IS NULL OR last_cash_date = '')",
             "profile_url IS NOT NULL AND profile_url != ''"]
    params: list = []
    if country:
        where.append("country = ?")
        params.append(country)
    sql = f"SELECT * FROM players WHERE {' AND '.join(where)} ORDER BY rank"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def counts(conn: sqlite3.Connection, country: str | None = None) -> dict:
    """Progress snapshot: total roster, profiles scraped, profiles pending."""
    base = "SELECT COUNT(*) FROM players"
    cond, params = "", []
    if country:
        cond = " WHERE country = ?"
        params = [country]
    total = conn.execute(base + cond, params).fetchone()[0]
    scraped_cond = (cond + " AND " if cond else " WHERE ") + "profile_scraped_at IS NOT NULL"
    scraped = conn.execute(base + scraped_cond, params).fetchone()[0]
    return {"total": total, "scraped": scraped, "pending": total - scraped}


def iter_rows(conn: sqlite3.Connection, country: str | None = None,
              scraped_only: bool = False, limit: int | None = None) -> list[sqlite3.Row]:
    """Read back stored players (for display/export)."""
    where, params = [], []
    if country:
        where.append("country = ?")
        params.append(country)
    if scraped_only:
        where.append("profile_scraped_at IS NOT NULL")
    sql = "SELECT * FROM players"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rank"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()
