# Twitter/X follower scraping — actor notes

## Current backend: `kaitoeasyapi/premium-x-follower-scraper-following-data`

The `/api/scrape` Twitter path ([`_scrape_twitter_followers`](../app.py)) uses
`kaitoeasyapi/premium-x-follower-scraper-following-data`. One call per handle
returns the follower list **with profile data inline** (name, bio, website,
location) — no login, no `maxPages` pagination, no ~2k/account cap.

| | kaitoeasyapi (current) | apidojo (alternative, see below) |
|---|---|---|
| Full follower lists | ✓ (`maxFollowers`) | ✓ (`maxItems`) |
| Website / external URL | ✓ `entities.url.urls[].expanded_url` | ✓ same nesting |
| Name + bio + location | ✓ | ✓ |
| Following (not just followers) | ✓ via `getFollowing` (we run followers only) | ✓ via `getFollowing` |
| Login required | No | No |
| Paid Apify plan required | No | **Yes** (Free Plan returns ~0 items) |
| Price | ~$0.15/1k | ~$0.40/1k |

### Actor schema (verified from a live probe, 2026-06)
**Input:**
- `user_names`: array of handles (no `@`)
- `getFollowers` / `getFollowing`: bool
- `maxFollowers`: int result cap — **floor 200** (`_X_FOLLOWER_MIN`)
- `maxFollowings`: int — must be **≥200 even when `getFollowing` is off** (validation)

**Output** (per follower — confirmed fields):
- `screen_name` — handle · `name` — display name · `description` — bio
- `location` · `followers_count` · `verified` (bool) · `protected` (== IG private)
- `email` — present but rarely populated
- website → top-level `url` is a **t.co shortlink**; the real site is
  `entities.url.urls[].expanded_url` — resolved by
  [`_x_profile_website`](../enrichment/social_scraper.py).

Shared constants/helpers live in `enrichment/social_scraper.py`:
`_X_FOLLOWER_ACTOR`, `_X_FOLLOWER_MIN`, `_X_COST_PER_USER`, `_x_profile_website`.
The programmatic enrichment path (`scrape_followers` / `enrich_followers`) uses
the same actor; the UI does not route through it.

---

## Alternative: `apidojo/twitter-user-scraper` (if you need the Following direction)

apidojo also returns full follower/following lists with the same website
nesting, at a higher per-result price, and **requires a paid Apify plan** (the
Free Plan caps API runs at ~10 items). Switch only if you need to scrape an
account's *following* list as well as its followers (kaitoeasyapi is wired for
followers only here).

**Input:** `twitterHandles` (array), `getFollowers`/`getFollowing` (bool),
`getRetweeters: false`, `maxItems` (total cap, omit for full list).
**Output:** `userName`, `name`, `description`/`rawDescription`, `location`,
`entities.url.urls[].expanded_url`, `followers`/`followersCount`,
`isVerified`/`isBlueVerified`, `isPrivate`.

To switch: point `TWITTER_FOLLOWERS_ACTOR` at `apidojo/twitter-user-scraper`,
send `{twitterHandles, getFollowers, getFollowing, getRetweeters:False, maxItems:limit}`,
map the field names above, re-show the Direction selector in `onPlatformChange()`,
and set `COST_PER_FOLLOWER_TW = 0.0004`.

## Verify after any actor switch
1. `python3 -c "import ast; ast.parse(open('app.py').read())"` — syntax OK.
2. Scrape a small handle on the Twitter platform; confirm followers come back
   with first/last name, bio, location, and a real website (not a `t.co` link).
3. Inspect one raw dataset item from the Apify run to confirm field names match
   the mapping; adjust aliases if the actor's shape changed.
