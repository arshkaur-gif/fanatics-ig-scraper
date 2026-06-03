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

import re
import threading
import time

from . import hendon_store as store
from .hendon_mob import (
    ALL_TIME_MONEY_LIST_URL,
    _jittered_delay,
    _load_via_driver,
    _new_undetected_driver,
    _parse_money_list_page,
    _parse_profile_details,
)


# Hendon's ranking pages list 100 players each (observed), so a page number
# maps to a rank range: page N covers ranks (N-1)*100+1 .. N*100.
ROSTER_PAGE_SIZE = 100


def _earnings_to_number(earnings: str | None) -> float | None:
    """Parse a money-list earnings string ("$ 1,234,567") to a number.

    Returns None when there are no digits to read (blank/garbage), so callers
    can tell "below threshold" apart from "unknown" and not stop on a bad row.
    """
    digits = re.sub(r"[^\d]", "", earnings or "")
    return float(digits) if digits else None


def harvest(db_path: str = store.DEFAULT_DB_PATH,
            url: str = ALL_TIME_MONEY_LIST_URL,
            max_pages: int | None = None,
            start_page: int = 1,
            do_roster: bool = True,
            do_profiles: bool = True,
            country: str | None = None,
            profile_limit: int | None = None,
            min_earnings: float | None = None,
            refresh_after_days: int | None = None,
            page_delay: float = 1.0,
            page_retries: int = 3,
            profile_delay: float = 1.0,
            challenge_wait_secs: int = 2700,
            progress_cb=None,
            stop_event: threading.Event | None = None) -> dict:
    """
    Run a (possibly partial) harvest. See module docstring for the two phases.

    Args:
        db_path: SQLite cache file.
        url: ranking list to harvest.
        max_pages: walk roster up to this page number; None = all.
        start_page: roster page to start walking from (skip earlier pages
            already cached — they'd only be re-upserted unchanged).
        do_roster / do_profiles: enable each phase independently.
        country: restrict the profile phase to one nationality.
        profile_limit: cap profiles enriched this run (incremental batches).
        min_earnings: stop the profile phase at the first player whose all-time
            earnings fall below this amount. The queue is ordered by rank
            (earnings descending), so once we cross the line everyone left is
            below it — we stop rather than keep visiting profiles we don't want.
        refresh_after_days: also re-enrich rows older than this many days.
        page_delay / profile_delay: politeness pauses (keep them — see docstring).
            profile_delay is the *center* of a jittered pause (±0.5s, so the
            default 1.0 means each gap is a random 0.5–1.5s); randomized timing
            avoids the regular cadence that helps escalate the challenge.
        page_retries: how many times to re-load a roster page that comes back
            empty before deciding the list has ended (rides out Cloudflare blips
            so one flaky load doesn't truncate a multi-thousand-page walk).
        challenge_wait_secs: how long to ride out a stalled Cloudflare "Just a
            moment" challenge during the profile phase before skipping that
            profile. Cloudflare occasionally sits on the interstitial for 30+
            minutes; rather than blow through the whole enrich queue getting
            nothing, we wait it out (re-navigating to nudge it) and resume. The
            roster phase doesn't use this — a blip there just retries the page.
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
    hit_floor = False
    try:
        # ── Phase 1: roster ──────────────────────────────────────────────
        # The all-time list runs to thousands of pages, so the walk has to
        # survive the odd flaky load. We retry a page that comes back empty
        # (Cloudflare blip / slow render) rather than ending the whole run, and
        # we decide the list is finished from the data itself — a page with no
        # players, or one that stops introducing higher ranks (an out-of-range
        # page echoing the last one) — instead of the brittle "Next" link text.
        if do_roster and not stop_event.is_set():
            base = url.rstrip("/")
            page = max(1, start_page)
            max_rank_seen = 0
            while (max_pages is None or page <= max_pages) and not stop_event.is_set():
                page_url = base + "/" if page == 1 else f"{base}/{page}"

                batch = None
                for attempt in range(1, page_retries + 1):
                    if stop_event.is_set():
                        break
                    html = _load_via_driver(driver, page_url, ready_marker="table--ranking-list")
                    if html:
                        batch, _ = _parse_money_list_page(html, page_url)
                        if batch:
                            break
                    report(phase="roster_retry", page=page, attempt=attempt,
                           retries=page_retries, roster_added=roster_added)
                    time.sleep(page_delay * attempt)  # simple backoff

                if not batch:
                    # No players after every retry: treat as the end of the list
                    # (or a hard block). Resumable — re-run with --start-page N.
                    report(phase="roster_end", page=page, roster_added=roster_added,
                           **store.counts(conn, country))
                    break

                batch_max_rank = max((p.get("rank") or 0) for p in batch)
                if batch_max_rank <= max_rank_seen:
                    # No forward progress (out-of-range page repeated content) → done.
                    report(phase="roster_end", page=page, roster_added=roster_added,
                           **store.counts(conn, country))
                    break
                max_rank_seen = batch_max_rank

                roster_added += store.upsert_roster(conn, batch)
                report(phase="roster", page=page, roster_added=roster_added,
                       **store.counts(conn, country))

                if min_earnings is not None:
                    # Pages are earnings-descending: once the cheapest player on
                    # this page is below the floor, every later page is too.
                    page_min = min(
                        (v for v in (_earnings_to_number(p.get("earnings")) for p in batch)
                         if v is not None),
                        default=None,
                    )
                    if page_min is not None and page_min < min_earnings:
                        hit_floor = True
                        report(phase="roster_stopped", page=page,
                               roster_added=roster_added, **store.counts(conn, country))
                        break
                page += 1
                time.sleep(page_delay)

        # ── Phase 2: profiles ────────────────────────────────────────────
        if do_profiles and not stop_event.is_set():
            # start_page also offsets the enrich queue: begin at the first rank
            # on that page (e.g. page 101 → rank 10001), skipping earlier ranks.
            min_rank = (start_page - 1) * ROSTER_PAGE_SIZE + 1 if start_page > 1 else None
            queue = store.pending_profiles(
                conn, limit=profile_limit, country=country,
                refresh_after_days=refresh_after_days, min_rank=min_rank,
            )
            total_queue = len(queue)
            for i, row in enumerate(queue, 1):
                if stop_event.is_set():
                    break
                if min_earnings is not None:
                    value = _earnings_to_number(row["earnings"])
                    if value is not None and value < min_earnings:
                        hit_floor = True
                        report(phase="profiles_stopped", queue_done=i - 1,
                               queue_total=total_queue, stop_name=row["name"],
                               stop_earnings=row["earnings"], **store.counts(conn, country))
                        break
                def on_cf(elapsed, _done=i - 1):
                    report(phase="cloudflare_wait", elapsed=elapsed, queue_done=_done,
                           queue_total=total_queue, **store.counts(conn, country))
                html = _load_via_driver(driver, row["profile_url"], ready_marker="<table",
                                        challenge_wait_secs=challenge_wait_secs, on_challenge=on_cf)
                if html:
                    city_state, profiles, last_cash_date, recent_earnings = _parse_profile_details(
                        html, row["profile_url"], row["country"] or ""
                    )
                    store.save_profile(conn, row["player_id"], city_state, profiles,
                                       last_cash_date, recent_earnings)
                profiles_done = i
                report(phase="profiles", queue_done=i, queue_total=total_queue,
                       **store.counts(conn, country))
                time.sleep(_jittered_delay(profile_delay))
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        conn.close()

    return {
        "stopped": stop_event.is_set(),
        "hit_floor": hit_floor,
        "roster_added": roster_added,
        "profiles_done": profiles_done,
    }


def backfill_results(db_path: str = store.DEFAULT_DB_PATH,
                     country: str | None = None,
                     limit: int | None = None,
                     profile_delay: float = 1.0,
                     challenge_wait_secs: int = 2700,
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
            def on_cf(elapsed, _done=i - 1):
                report(phase="cloudflare_wait", elapsed=elapsed, queue_done=_done,
                       queue_total=total_queue)
            html = _load_via_driver(driver, row["profile_url"], ready_marker="<table",
                                    challenge_wait_secs=challenge_wait_secs, on_challenge=on_cf)
            if html:
                _, _, last_cash_date, recent_earnings = _parse_profile_details(
                    html, row["profile_url"], row["country"] or ""
                )
                store.save_results(conn, row["player_id"], last_cash_date, recent_earnings)
            done = i
            report(phase="backfill", queue_done=i, queue_total=total_queue)
            time.sleep(_jittered_delay(profile_delay))
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        conn.close()

    return {"stopped": stop_event.is_set(), "backfilled": done}
