# AGENTS.md — Reach

## What this app is

Reach is a static front-end app (no server, no build step, no Node/Python
runtime) for scraping Instagram/Twitter follower & following lists via the
**Apify REST API, called directly from the browser**. It is a port of the
IG/Twitter scraping tab of an internal Flask tool; the backend-dependent
Leaderboards (Hendon Mob) and contact-enrichment features were intentionally
dropped.

Files:
- `index.html` — markup (auth gate, token gate, main app, modals). Links
  `styles.css` and `app.js`. Inline SVG favicon.
- `styles.css` — extracted styles + auth/settings/token additions.
- `app.js` — all logic: alveus auth + private store, Apify REST client,
  actor payloads, normalization, table/filter/sort/export, DM helpers.
- `app.yaml` — alveus manifest (`description`, `tags`).

## alveus constraints followed

- **Front-end only.** No backend of its own; everything is vanilla JS + fetch,
  dependency-free (only the Google Fonts CDN link, which degrades gracefully).
- **Per-user auth + private store.** API base is derived at runtime:
  `'/' + location.pathname.split('/').filter(Boolean).slice(0,2).join('/') + '/api'`.
  Auth via `POST /auth/{register,login,logout}` with `cookie:true`. Config
  (the Apify token) lives in `GET/POST/PATCH /private` under
  `collection: 'config'`, `data.apifyToken`. Any 401 returns the user to the
  auth screen.
- **Token handling.** The Apify token is read fresh from `/private` right before
  each scrape and **never** written to `localStorage` or the URL/query string.
  Apify is authenticated with the `Authorization: Bearer` header (not a query
  param), which Apify permits over CORS.

## Apify integration notes

- Async pattern: `POST /acts/{actorId}/runs` → poll `GET /actor-runs/{runId}`
  every ~3s until terminal (5-min max wait) → `GET /datasets/{id}/items?clean=true`.
- Actor IDs put `~` where the id has `/`.
- Actors + payloads live in `app.js` (`scrapeInstagram`, `scrapeTwitter`,
  `fetchProfileDetails`). apidojo IG results are filtered to rows with a
  `related` back-ref (seed profiles dropped). Twitter is called once per seed
  and aggregated; its limit floors at 200.
- `splitName` and `extractLinks` are JS ports of `enrichment/follower_fields.py`;
  `xProfileWebsite` ports `_x_profile_website` from `enrichment/social_scraper.py`.
- Result shape matches the original Flask output so the table renders unchanged.

## Editing scope

Work only inside `alveus/reach/`. Do not add a bundler, framework, or server.
