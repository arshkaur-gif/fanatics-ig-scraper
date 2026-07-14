# Reach

Reach scrapes the audience of any public **Instagram** or **Twitter/X** profile —
its followers or following — into a sortable, filterable table you can export to
CSV or JSON for outreach. It also includes client-side DM helpers (per-recipient
DM Launcher and shared-message Bulk DM) that open profile tabs and copy your
message to the clipboard.

It is a **static front-end app** (HTML + CSS + vanilla JS) hosted on alveus. It
has no scraping logic of its own: it is a thin client that calls a hosted backend
which does the actual Apify scraping and returns already-normalized results.

## Architecture

- **Front-end (this app):** static HTML/CSS/JS on alveus. Renders the form,
  results table, filters, exports, and DM helpers. It makes exactly two network
  calls, both to the backend:
  - `POST https://fanatics-ig-scraper-ecru.vercel.app/api/scrape`
  - `POST https://fanatics-ig-scraper-ecru.vercel.app/api/profile-details`
- **Backend:** a hosted Flask service at
  `https://fanatics-ig-scraper-ecru.vercel.app`. It holds the **Apify token
  server-side**, orchestrates the Apify actors, and returns normalized records.
  CORS is enabled (any origin), so the browser can call it directly.

There is **no login and no token in the browser.** The old "bring your own Apify
token" flow and the alveus per-user auth/private-store are gone — the token lives
only on the backend. This is an internal-only tool with no access gate.

## Scope

**Included:** Instagram/Twitter follower & following scraping, a second-pass
"Get profile details" for Instagram (bio, follower/post counts, links), the
results table (avatars, sorting, filtering, selection), CSV/JSON export, and the
client-side DM/bulk-open helpers.

**Not included:** the Hendon Mob / Leaderboards tab and the contact-enrichment
("Enrich Contacts") features from the original internal tool.

## Cost reference (per result — client-side estimate only)

| Actor                              | Rate       |
|------------------------------------|------------|
| Instagram followers                | $0.0020    |
| Instagram profile details          | $0.0023    |
| Twitter followers (per seed)       | $0.00015   |

Reach shows a live cost estimate before you run and warns when an estimate
exceeds the ~$5 free tier. The Twitter actor floors its result count at 200 and
is billed per seed handle. The estimate is informational only — the backend
chooses the actual actor and bears the Apify cost.
