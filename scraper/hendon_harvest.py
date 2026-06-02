"""
Resumable, two-phase harvester for The Hendon Mob, backed by the SQLite cache.

Phase 1 (roster): walk the ranking pages and upsert each player into the cache.
Phase 2 (profiles): work through players not yet enriched, visiting each profile
to fill city/state and social links.

Both phases reuse a single headed browser session (Cloudflare solved once — see
hendon_mob's module docstring), commit to SQLite incrementally, and honour a
stop_event so a long run can be cancelled and resumed later with no lost work.
Designed to run on a background thread; create the driver inside that thread.
"""

from __future__ import annotations

import threading
import time

from . import hendon_store as store
from .hendon_mob import (
    ALL_TIME_MONEY_LIST_URL,
    _load_via_driver,
    _new_undetected_driver,
    _parse_money_list_page,
    _parse_profile_details,
)


def harvest(db_path: str = store.DEFAULT_DB_PATH,
            url: str = ALL_TIME_MONEY_LIST_URL,
            max_pages: int | None = None,
            do_roster: bool = True,
            do_profiles: bool = True,
            country: str | None = None,
            profile_limit: int | None = None,
            refresh_after_days: int | None = None,
            page_delay: float = 1.0,
            profile_delay: float = 0.3,
            progress_cb=None,
            stop_event: threading.Event | None = None) -> dict:
    """
    Run a (possibly partial) harvest. See module docstring for the two phases.

    Args:
        db_path: SQLite cache file.
        url: ranking list to harvest.
        max_pages: roster pages to walk; None = all.
        do_roster / do_profiles: enable each phase independently.
        country: restrict the profile phase to one nationality.
        profile_limit: cap profiles enriched this run (incremental batches).
        refresh_after_days: also re-enrich rows older than this many days.
        page_delay / profile_delay: politeness pauses (keep them — see docstring).
        progress_cb: optional callable(dict) invoked as progress changes.
        stop_event: optional threading.Event; set it to stop cleanly.

    Returns a final summary dict.
    """
    stop_event = stop_event or threading.Event()

    def report(**kw):
        if progress_cb:
            progress_cb(kw)

    driver = _new_undetected_driver()
    if driver is None:
        raise RuntimeError("undetected-chromedriver is required to harvest The Hendon Mob")
    conn = store.connect(db_path)

    roster_added = 0
    profiles_done = 0
    try:
        # ── Phase 1: roster ──────────────────────────────────────────────
        if do_roster and not stop_event.is_set():
            base = url.rstrip("/")
            page = 1
            while (max_pages is None or page <= max_pages) and not stop_event.is_set():
                page_url = base + "/" if page == 1 else f"{base}/{page}"
                html = _load_via_driver(driver, page_url, ready_marker="table--ranking-list")
                if not html:
                    break
                batch, has_next = _parse_money_list_page(html, page_url)
                if not batch:
                    break
                roster_added += store.upsert_roster(conn, batch)
                report(phase="roster", page=page, roster_added=roster_added,
                       **store.counts(conn, country))
                if not has_next:
                    break
                page += 1
                time.sleep(page_delay)

        # ── Phase 2: profiles ────────────────────────────────────────────
        if do_profiles and not stop_event.is_set():
            queue = store.pending_profiles(
                conn, limit=profile_limit, country=country,
                refresh_after_days=refresh_after_days,
            )
            total_queue = len(queue)
            for i, row in enumerate(queue, 1):
                if stop_event.is_set():
                    break
                html = _load_via_driver(driver, row["profile_url"], ready_marker="<table")
                if html:
                    city_state, profiles, last_cash_date, recent_earnings = _parse_profile_details(
                        html, row["profile_url"], row["country"] or ""
                    )
                    store.save_profile(conn, row["player_id"], city_state, profiles,
                                       last_cash_date, recent_earnings)
                profiles_done = i
                report(phase="profiles", queue_done=i, queue_total=total_queue,
                       **store.counts(conn, country))
                time.sleep(profile_delay)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        conn.close()

    return {
        "stopped": stop_event.is_set(),
        "roster_added": roster_added,
        "profiles_done": profiles_done,
    }


def backfill_results(db_path: str = store.DEFAULT_DB_PATH,
                     country: str | None = None,
                     limit: int | None = None,
                     profile_delay: float = 0.3,
                     progress_cb=None,
                     stop_event: threading.Event | None = None) -> dict:
    """
    Re-visit already-enriched profiles to populate last_cash_date /
    recent_earnings on rows scraped before those columns existed.

    Reuses one headed browser session and only touches the results fields
    (profile_scraped_at and the rest of the profile data are left intact), so
    it's resumable: re-running picks up whatever is still missing.
    """
    stop_event = stop_event or threading.Event()

    def report(**kw):
        if progress_cb:
            progress_cb(kw)

    driver = _new_undetected_driver()
    if driver is None:
        raise RuntimeError("undetected-chromedriver is required to harvest The Hendon Mob")
    conn = store.connect(db_path)

    done = 0
    try:
        queue = store.rows_missing_results(conn, country=country, limit=limit)
        total_queue = len(queue)
        for i, row in enumerate(queue, 1):
            if stop_event.is_set():
                break
            html = _load_via_driver(driver, row["profile_url"], ready_marker="<table")
            if html:
                _, _, last_cash_date, recent_earnings = _parse_profile_details(
                    html, row["profile_url"], row["country"] or ""
                )
                store.save_results(conn, row["player_id"], last_cash_date, recent_earnings)
            done = i
            report(phase="backfill", queue_done=i, queue_total=total_queue)
            time.sleep(profile_delay)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        conn.close()

    return {"stopped": stop_event.is_set(), "backfilled": done}
