"""
CLI for the Hendon Mob bulk harvest — the resumable, multi-day path.

This is the entrypoint for the one-time full harvest (and the CSV handoff). It
wraps the same engine the UI's one-shot scraper uses, but is built for long runs:
no browser/web server needed, logs progress to stdout, Ctrl-C stops cleanly, and
everything is durable in SQLite so re-running resumes where it left off.

    # walk the whole money list (roster) + enrich every US profile
    python -m scraper.harvest run --us-only

    # incremental chunk: 50 roster pages, enrich 5000 profiles this run
    python -m scraper.harvest run --pages 50 --limit 5000 --us-only

    # progress snapshot from the cache
    python -m scraper.harvest status

    # stream the handoff CSV (defaults to stdout)
    python -m scraper.harvest export --us-only -o hendon_us.csv

See scraper/hendon_mob.py's module docstring for the Cloudflare / headed-browser
constraints (this still drives a visible Chrome — it just isn't tied to the UI).
"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import sys
import threading
import time

from . import hendon_store as store
from . import hendon_harvest
from .hendon_mob import ALL_TIME_MONEY_LIST_URL


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def cmd_run(args: argparse.Namespace) -> int:
    country = "United States" if args.us_only else None
    max_pages = None if str(args.pages).lower() == "all" else int(args.pages)

    stop_event = threading.Event()

    def handle_sigint(signum, frame):
        _log("Stop requested — finishing current item, then exiting cleanly…")
        stop_event.set()
    signal.signal(signal.SIGINT, handle_sigint)

    last = {"phase": None}

    def progress(p):
        phase = p.get("phase")
        if phase == "roster":
            _log(f"roster · page {p.get('page')} · {p.get('total', 0)} players cached")
        elif phase == "profiles":
            # log every 25th profile (and the first) to keep output readable
            done = p.get("queue_done", 0)
            if done == 1 or done % 25 == 0 or done == p.get("queue_total"):
                _log(f"profiles · {done}/{p.get('queue_total', 0)} this run · "
                     f"{p.get('scraped', 0)} enriched / {p.get('pending', 0)} pending")
        last["phase"] = phase

    _log(f"Starting harvest — db={args.db} url={args.url}")
    _log(f"  roster={'on' if not args.no_roster else 'off'} "
         f"profiles={'on' if not args.no_profiles else 'off'} "
         f"max_pages={max_pages} profile_limit={args.limit} country={country}")

    started = time.time()
    summary = hendon_harvest.harvest(
        db_path=args.db,
        url=args.url,
        max_pages=max_pages,
        do_roster=not args.no_roster,
        do_profiles=not args.no_profiles,
        country=country,
        profile_limit=args.limit,
        refresh_after_days=args.refresh_after,
        progress_cb=progress,
        stop_event=stop_event,
    )

    elapsed = round(time.time() - started, 1)
    conn = store.connect(args.db)
    counts = store.counts(conn, country=country)
    conn.close()
    _log(f"{'STOPPED' if summary['stopped'] else 'DONE'} in {elapsed}s — "
         f"roster +{summary['roster_added']}, {summary['profiles_done']} profiles this run")
    _log(f"  cache: {counts['scraped']} enriched / {counts['pending']} pending / {counts['total']} total"
         + (f" ({country})" if country else ""))
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    country = "United States" if args.us_only else None

    stop_event = threading.Event()

    def handle_sigint(signum, frame):
        _log("Stop requested — finishing current item, then exiting cleanly…")
        stop_event.set()
    signal.signal(signal.SIGINT, handle_sigint)

    def progress(p):
        done = p.get("queue_done", 0)
        if done == 1 or done % 25 == 0 or done == p.get("queue_total"):
            _log(f"backfill · {done}/{p.get('queue_total', 0)} results filled this run")

    conn = store.connect(args.db)
    pending = len(store.rows_missing_results(conn, country=country))
    conn.close()
    _log(f"Backfilling last_cash_date / recent_earnings — {pending} enriched rows missing them"
         + (f" ({country})" if country else ""))

    started = time.time()
    summary = hendon_harvest.backfill_results(
        db_path=args.db, country=country, limit=args.limit, progress_cb=progress,
        stop_event=stop_event,
    )
    _log(f"{'STOPPED' if summary['stopped'] else 'DONE'} in {round(time.time() - started, 1)}s — "
         f"{summary['backfilled']} rows backfilled this run")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    conn = store.connect(args.db)
    overall = store.counts(conn)
    us = store.counts(conn, country="United States")
    conn.close()
    print(f"DB: {args.db}")
    print(f"  total roster : {overall['total']}")
    print(f"  enriched     : {overall['scraped']}")
    print(f"  pending      : {overall['pending']}")
    print(f"  US enriched  : {us['scraped']} / {us['total']}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    country = "United States" if args.us_only else None
    out = open(args.output, "w", newline="") if args.output else sys.stdout
    try:
        writer = csv.writer(out)
        writer.writerow(["rank", "name", "country", "earnings", "recent_earnings",
                         "last_cash_date", "city_state", "profile_url", "socials",
                         "profile_scraped_at"])
        conn = store.connect(args.db)
        where, params = [], []
        if country:
            where.append("country = ?")
            params.append(country)
        if args.scraped_only:
            where.append("profile_scraped_at IS NOT NULL")
        sql = ("SELECT rank, name, country, earnings, recent_earnings, last_cash_date, "
               "city_state, profile_url, profiles, profile_scraped_at FROM players")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY rank"
        n = 0
        for row in conn.execute(sql, params):  # cursor streams; no fetchall
            try:
                socials = " ".join(json.loads(row["profiles"] or "{}").values())
            except Exception:
                socials = ""
            writer.writerow([row["rank"], row["name"], row["country"], row["earnings"],
                             row["recent_earnings"], row["last_cash_date"],
                             row["city_state"], row["profile_url"], socials,
                             row["profile_scraped_at"]])
            n += 1
        conn.close()
    finally:
        if args.output:
            out.close()
    if args.output:
        _log(f"Wrote {n} rows to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scraper.harvest",
                                     description="Hendon Mob bulk harvest (resumable, SQLite-cached).")
    parser.add_argument("--db", default=store.DEFAULT_DB_PATH, help="SQLite cache path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Harvest roster and/or profiles (resumable)")
    p_run.add_argument("--url", default=ALL_TIME_MONEY_LIST_URL, help="Ranking list URL")
    p_run.add_argument("--pages", default="all", help="Roster pages to walk (int or 'all')")
    p_run.add_argument("--limit", type=int, default=None, help="Max profiles to enrich this run")
    p_run.add_argument("--us-only", action="store_true", help="Restrict profile enrichment to US players")
    p_run.add_argument("--no-roster", action="store_true", help="Skip the roster phase")
    p_run.add_argument("--no-profiles", action="store_true", help="Skip the profile phase")
    p_run.add_argument("--refresh-after", type=int, default=None,
                       help="Also re-enrich rows older than N days")
    p_run.set_defaults(func=cmd_run)

    p_backfill = sub.add_parser("backfill",
                                help="Fill last_cash_date / recent_earnings on already-enriched rows")
    p_backfill.add_argument("--us-only", action="store_true", help="Restrict to US players")
    p_backfill.add_argument("--limit", type=int, default=None, help="Max rows to backfill this run")
    p_backfill.set_defaults(func=cmd_backfill)

    p_status = sub.add_parser("status", help="Print cache counts")
    p_status.set_defaults(func=cmd_status)

    p_export = sub.add_parser("export", help="Stream cached players to CSV")
    p_export.add_argument("-o", "--output", default=None, help="Output file (default: stdout)")
    p_export.add_argument("--us-only", action="store_true", help="Only US players")
    p_export.add_argument("--scraped-only", action="store_true", help="Only enriched players")
    p_export.set_defaults(func=cmd_export)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
