# Switching the Twitter scraper back to `apidojo/twitter-user-scraper`

## Why this is parked
`apidojo/twitter-user-scraper` is the best Twitter followers actor we found:

| | data-slayer (current/interim) | **apidojo/twitter-user-scraper** |
|---|---|---|
| Full follower lists | ✗ (~2k cap via `maxPages` ≤ 100, no resume) | **✓ (`maxItems`, no page cap)** |
| Website / external URL | ✓ (`website`) | ✓ (`entities.url.urls[].expanded_url`) |
| Name + bio + location | ✓ | ✓ |
| Following (not just followers) | ✗ (followers only) | ✓ (`getFollowing`) |
| Login required | No | No |
| Price | ~$1.50/1k | ~$0.40/1k |

**Blocker:** apidojo gates **API usage behind a paid Apify plan**. On the Free Plan a
run returns ~0 items with:
> Users with the Free Plan can retrieve a maximum of 10 items.
> You cannot use the API with the Free Plan.

Once the Apify account is on a paid plan (cheapest tier ~$39/mo incl. credits), apply the
changes below and Twitter gets full lists + website at lower per-result cost.

## Actor schema (verified from Apify, 2026-06)
**Input** (`apidojo/twitter-user-scraper`):
- `twitterHandles`: array of handles (also accepts `startUrls`, `twitterUserIds`, `searchTerms`)
- `getFollowers`: bool (default true) — scrape the followers list
- `getFollowing`: bool (default true) — scrape the following list
- `getRetweeters`: bool — set false (we don't want retweeters)
- `maxItems`: int — total result cap; **omit/large = full list**

**Output** (per user; field names mapped defensively, confirm one raw item on first run):
- `userName` — handle
- `name` — display name
- `description` (or `rawDescription`) — bio
- `location`
- website → nested at `entities.url.urls[].expanded_url` (pick `expanded_url`, not the `t.co` shortlink)
- `followers` / `followersCount`
- `isVerified` / `isBlueVerified`
- `isPrivate`

## Code changes to re-apply (all in `app.py` unless noted)

### 1. Actor constant (near the other `_ACTOR` constants)
Replace the data-slayer constant + `TWITTER_FOLLOWERS_PER_PAGE` with:
```python
TWITTER_FOLLOWERS_ACTOR = "apidojo/twitter-user-scraper"
```

### 2. The scrape helper — replace `_scrape_twitter_followers` (and add `_twitter_website`)
```python
def _twitter_website(d: dict) -> str:
    """apidojo returns the profile website nested at entities.url.urls[].expanded_url."""
    ent = (d.get("entities") or {}).get("url") or {}
    for u in (ent.get("urls") or []):
        ex = (u or {}).get("expanded_url") or (u or {}).get("url")
        if ex:
            return ex
    return d.get("url") or d.get("website") or ""


def _scrape_twitter_followers(token, usernames, limit, direction="Followers"):
    """
    Twitter/X followers (or following) via apidojo/twitter-user-scraper (no login).

    Takes `twitterHandles` (array) + `maxItems` and returns the FULL list up to
    maxItems (no page cap). Output carries name, bio, location, and the website
    (nested under entities.url), so we enrich here — no profile-details pass.
    """
    want_following = direction == "Followings"
    run_input = {
        "twitterHandles": usernames,
        "getFollowers": not want_following,
        "getFollowing": want_following,
        "getRetweeters": False,
        "maxItems": limit,
    }

    client = ApifyClient(token)
    start = time.time()
    try:
        run = client.actor(TWITTER_FOLLOWERS_ACTOR).call(run_input=run_input)
    except Exception as e:
        return jsonify(error=str(e)), 500

    elapsed = round(time.time() - start, 1)
    raw = list(client.dataset(run["defaultDatasetId"]).iterate_items())[:limit]

    results = []
    for d in raw:
        record = {
            "username": d.get("userName") or d.get("screen_name") or d.get("username") or "",
            "full_name": d.get("name") or "",
            "biography": d.get("description") or d.get("rawDescription") or "",
            "external_url": _twitter_website(d),
            "location": d.get("location") or "",
            "followers_count": d.get("followers") or d.get("followersCount") or 0,
            "is_verified": d.get("isVerified") or d.get("isBlueVerified") or d.get("verified") or False,
            # Twitter's "protected" account == Instagram's is_private.
            "is_private": d.get("isPrivate") or d.get("protected") or False,
        }
        results.append(enrich_follower(record))

    return jsonify(results=results, elapsed=elapsed, count=len(results))
```

### 3. Call site in `api_scrape` — pass the direction (apidojo supports following)
```python
    data_type = body.get("type", "Followers")
    if data_type not in ("Followers", "Followings"):
        data_type = "Followers"

    if platform == "twitter":
        return _scrape_twitter_followers(token, usernames, limit, data_type)

    client = ApifyClient(token)
```

### 4. Front-end (`HTML` string)
- In `onPlatformChange()`, **remove** the line that hides the Direction selector for Twitter
  (apidojo supports both followers and following):
  ```js
  // delete this line:
  document.getElementById('type').closest('.field').style.display = isTw ? 'none' : '';
  ```
- Update the Twitter cost rate:
  ```js
  const COST_PER_FOLLOWER_TW = 0.0004;  // apidojo/twitter-user-scraper, ~$0.40/1k
  ```

## Verify after switching
1. `python3 -c "import ast; ast.parse(open('app.py').read())"` — syntax OK.
2. Scrape a small handle on the Twitter platform; confirm followers come back with
   first/last name, bio, location, and Links (website should be the real site, not a `t.co` link).
3. Inspect one raw dataset item in the Apify run to confirm field names match the mapping
   (`userName`, `description`, `entities.url...`); adjust aliases if the actor's shape changed.
4. Confirm the Followers/Following dropdown works for Twitter.
