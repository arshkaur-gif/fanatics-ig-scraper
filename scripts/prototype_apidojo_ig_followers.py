#!/usr/bin/env python3
"""
One-off prototype: single call to apidojo/instagram-user-scraper for IG followers.

Goal: before swapping the discovery actor, confirm on a real run (1) the per-item
cost (~$0.0005/follower → $0.50/1k) and (2) the follower-item field shape. The
Apify store says follower items are SHALLOW (username/id/fullName/isPrivate/
isVerified, no bio/website) — this proves it on live data so we know the
$2.80/1k mixed plan holds (cheap apidojo discovery + apify/instagram-profile-
scraper enrichment second pass). NOT wired into the app.

Input keys (from the actor's input schema):
    handles        list of @usernames
    getFollowers   bool — emit each follower as a dataset item
    maxItems       TOTAL output cap (profile + followers COMBINED), so for N
                   followers pass N+1.

Usage:
    python scripts/prototype_apidojo_ig_followers.py <handle> [num_followers]
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

ACTOR_ID = "apidojo/instagram-user-scraper"
COST_PER_FOLLOWER = 0.0005   # $0.50 / 1k follower items (per actor pricing)
COST_PER_HANDLE = 0.01       # $0.01 per seed handle (profile item)


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
    handle = sys.argv[1] if len(sys.argv) > 1 else "fanatics"
    num_followers = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    from apify_client import ApifyClient
    client = ApifyClient(_load_token())

    run_input = {
        "handles": [handle],
        "getFollowers": True,
        "getFollowings": False,
        "maxItems": num_followers + 1,   # +1 for the seed profile item itself
    }
    print(f"Running {ACTOR_ID} for @{handle} (maxItems={run_input['maxItems']}) ...")
    run = client.actor(ACTOR_ID).call(run_input=run_input, timeout_secs=300)
    if not run:
        raise SystemExit("Actor run returned nothing")

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    print(f"\nGot {len(items)} items. Run status: {run.get('status')}\n")
    if not items:
        return

    # Separate the seed profile (has a bio/website) from shallow follower items.
    # Followers carry a `related` back-reference to the parent profile.
    followers = [it for it in items if it.get("related") or it.get("type") == "user"
                 and not it.get("biography")]
    seed = [it for it in items if it not in followers]

    print("=== FIRST FOLLOWER ITEM (full JSON) ===")
    sample = followers[0] if followers else items[0]
    print(json.dumps(sample, indent=2, default=str))

    print("\n=== TOP-LEVEL KEYS (first follower) ===")
    print(sorted(sample.keys()))

    # The decisive check: do follower items carry the enrichment fields inline,
    # or must we run the apify/instagram-profile-scraper second pass?
    enrich_fields = ["biography", "bio", "externalUrl", "external_url", "website",
                     "publicEmail", "businessEmail", "followerCount", "followersCount"]
    print(f"\n=== ENRICHMENT FIELDS PRESENT (of {len(followers)} follower items) ===")
    any_present = False
    for f in enrich_fields:
        n = sum(1 for it in followers if it.get(f))
        if n:
            any_present = True
            print(f"  {f:16s}: {n}")
    if not any_present:
        print("  (none — follower items are SHALLOW; second enrichment pass needed)")

    # Field-coverage on the identity fields we DO expect.
    id_fields = ["username", "fullName", "full_name", "id", "isPrivate", "isVerified"]
    print(f"\n=== IDENTITY FIELDS PRESENT (of {len(followers)}) ===")
    for f in id_fields:
        n = sum(1 for it in followers if it.get(f) not in (None, ""))
        if n:
            print(f"  {f:12s}: {n}")

    cost = len(seed) * COST_PER_HANDLE + len(followers) * COST_PER_FOLLOWER
    print(f"\n=== COST ===")
    print(f"  {len(seed)} seed profile(s) @ ${COST_PER_HANDLE}  + "
          f"{len(followers)} followers @ ${COST_PER_FOLLOWER}")
    print(f"  this run: ${cost:.4f}   →   extrapolated $/1k followers: "
          f"${len(followers) and (cost / len(followers) * 1000):.2f}")


if __name__ == "__main__":
    main()
