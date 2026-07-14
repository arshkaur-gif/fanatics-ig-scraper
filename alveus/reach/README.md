# Reach

Reach scrapes the audience of any public **Instagram** or **Twitter/X** profile —
its followers or following — into a sortable, filterable table you can export to
CSV or JSON for outreach. It also includes client-side DM helpers (per-recipient
DM Launcher and shared-message Bulk DM) that open profile tabs and copy your
message to the clipboard.

It is a **pure static front-end app** (HTML + CSS + vanilla JS). There is no
backend of its own: it talks directly to the [Apify](https://apify.com) REST API
from your browser, and stores your credentials in alveus's per-user private store.

## Bring your own Apify token

Each user needs their own free Apify token.

1. Create a free account at <https://console.apify.com/sign-up> (~$5/month of free
   platform usage).
2. Copy your token from **Settings → Integrations → Personal API tokens**.
3. Paste it into Reach the first time you log in (or later via **Settings**).

The scrapers run as Apify "actors" (paid per result). Reach shows a live cost
estimate before you run, and warns when an estimate exceeds the ~$5 free tier.

## Login

Reach is gated per user via alveus auth:

- **Register** a username + password the first time, then **log in**.
- Your session lasts ~24 hours; after it expires you'll be sent back to the login
  screen.
- **Log out** from the top bar.

Your Apify token is saved under your account in the alveus private store and read
back fresh before each scrape.

## Scope

**Included:** Instagram/Twitter follower & following scraping, a second-pass
"Get profile details" for Instagram (bio, follower/post counts, links), the
results table (avatars, sorting, filtering, selection), CSV/JSON export, and the
client-side DM/bulk-open helpers.

**Not included:** the Hendon Mob / Leaderboards tab and the contact-enrichment
("Enrich Contacts") features from the original internal tool — those depended on
a server and are out of scope here.

## Cost reference (per result)

| Actor                              | Rate       |
|------------------------------------|------------|
| Instagram followers (standard)     | $0.0020    |
| Instagram followers (apidojo, opt) | $0.0005    |
| Instagram profile details          | $0.0023    |
| Twitter followers (per seed)       | $0.00015   |

The Twitter actor floors its result count at 200 and is billed per seed handle.
The apidojo Instagram actor is cheaper and available via a toggle (off by
default).

## Security note

Your Apify token is stored in Reach's **per-user private store** — scoped to your
alveus account. Because Reach calls Apify from the browser, the token is present
in your browser at runtime and **visible to anyone with access to your browser
devtools/network tab**. Treat it accordingly:

- Don't reuse a high-value or organization-wide token here.
- Prefer a dedicated, low-scope Apify token you can rotate or revoke.
- The token is never written to `localStorage` or the URL.
