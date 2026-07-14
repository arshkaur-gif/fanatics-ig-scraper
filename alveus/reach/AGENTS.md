# AGENTS.md — Reach

## What this app is

Reach is a static front-end app (no server, no build step, no Node/Python
runtime) for scraping Instagram/Twitter follower & following lists. It is a
**thin client** of a hosted backend that does the actual scraping; the Apify
token stays server-side on that backend. It is a port of the IG/Twitter scraping
tab of an internal Flask tool; the backend-dependent Leaderboards (Hendon Mob)
and contact-enrichment features were intentionally dropped.

Files:
- `index.html` — markup (main app + modals). Links `styles.css` and `app.js`.
  Inline SVG favicon. No auth/token/settings markup.
- `styles.css` — extracted styles.
- `app.js` — all logic: two backend calls, table/filter/sort/export, cost
  estimate, DM helpers.
- `app.yaml` — alveus manifest (`description`, `tags`).

## Architecture

- **Front-end only.** Everything is vanilla JS + fetch, dependency-free (only the
  Google Fonts CDN link, which degrades gracefully).
- **No login, no real secret in the browser.** There is no alveus auth and no
  per-user private store.
- **Backend client.** All scraping is delegated to a hosted Flask backend:
  ```
  const API_BASE = 'https://fanatics-ig-scraper-ecru.vercel.app';
  ```
  The backend holds the Apify token server-side, runs the actors, and returns
  already-normalized records.
- **Access gate.** The backend only accepts `/api/*` calls that (1) come from an
  allowlisted Origin (alveus host + localhost dev — others get 403), (2) carry an
  `X-Reach-Client` header matching its `REACH_CLIENT_TAG` env var (else 401), and
  (3) stay under a light per-IP rate limit (~20 calls/10 min, else 429). The tag
  is defined as `CLIENT_TAG` in `app.js` and sent by `apiHeaders()` — every new
  backend call MUST use `apiHeaders()`. The tag is not a true secret (Twingate is
  the real boundary); to rotate it, change the Vercel env var and `app.js`
  together.

## Backend endpoints

- `POST ${API_BASE}/api/scrape`
  - request: `{ usernames: "<raw input string>", limit, type: "Followers"|"Followings", platform: "instagram"|"twitter" }`.
    Send the raw input string as-typed — the **backend** parses handles/URLs.
  - response: `{ results: [...normalized records...], elapsed, count }`.
- `POST ${API_BASE}/api/profile-details`
  - request: `{ usernames: ["handle1", ...] }`.
  - response: `{ results: [...profile records...], elapsed, count }`.
    Merged into `currentData` by username; reads bio/biography, followers_count,
    follows_count, posts_count, external_url/externalUrl, links/externalUrls,
    location.

The result shape matches what the table renders (username, full_name,
first_name, last_name, is_private, is_verified, id, profile_pic_url,
username_scrape; Twitter adds biography/followers_count/location/external_url).

## Cost preview

Client-side estimate only (`updateCostTag`). Rates: IG followers `0.002`, IG
profile-details `0.0023`, Twitter `0.00015` (Twitter limit floored at 200,
billed per seed). The backend picks the actor and bears the real cost, so there
is no client actor toggle.

## Editing scope

Work only inside `alveus/reach/`. Do not add a bundler, framework, or server.
