#!/usr/bin/env python3
"""
One-off prototype: single call to kaitoeasyapi/premium-x-follower-scraper-following-data.

Goal: confirm the real output JSON shape (field names) for a brand account's
followers before we build any field mapping. NOT wired into the pipeline.

Usage:
    python scripts/prototype_x_followers.py <brand_handle> [max_followers]

Reads APIFY_API_TOKEN from .env. maxFollowers floor is 200 (actor minimum),
so the cheapest possible run returns ~200 records (~$0.03 at $0.15/1k).
"""

import json
import os
import sys
from pathlib import Path

ACTOR_ID = "kaitoeasyapi/premium-x-follower-scraper-following-data"


def _load_token() -> str:
    # Prefer real env; fall back to .env so this runs without extra setup.
    token = os.environ.get("APIFY_API_TOKEN")
    if token:
        return token
    env = Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text().splitlines():
        if line.startswith("APIFY_API_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("APIFY_API_TOKEN not found in env or .env")


def main() -> None:
    handle = sys.argv[1] if len(sys.argv) > 1 else "Fanatics"
    max_followers = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    from apify_client import ApifyClient
    client = ApifyClient(_load_token())

    run_input = {
        "user_names": [handle],
        "getFollowers": True,
        "getFollowing": False,      # followers only — half the cost for a probe
        "maxFollowers": max_followers,
        "maxFollowings": 200,       # actor validates >=200 even when getFollowing is off
    }
    print(f"Running {ACTOR_ID} for @{handle} (maxFollowers={max_followers}) ...")
    run = client.actor(ACTOR_ID).call(run_input=run_input, timeout_secs=300)
    if not run:
        raise SystemExit("Actor run returned nothing")

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    print(f"\nGot {len(items)} items. Run status: {run.get('status')}\n")
    if not items:
        return

    # Full shape of the first record so we can see every available field.
    print("=== FIRST ITEM (full JSON) ===")
    print(json.dumps(items[0], indent=2, default=str))

    print("\n=== TOP-LEVEL KEYS ===")
    print(sorted(items[0].keys()))

    # Quick signal on the fields enrichment cares about, across the sample.
    fields = ["name", "screen_name", "username", "description", "bio",
              "url", "website", "location", "email"]
    print("\n=== NON-EMPTY COUNTS (of", len(items), "records) ===")
    for f in fields:
        n = sum(1 for it in items if it.get(f))
        if n:
            print(f"  {f:12s}: {n}")


if __name__ == "__main__":
    main()
