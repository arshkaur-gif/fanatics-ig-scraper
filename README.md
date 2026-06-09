# Reach — Instagram / Leaderboard outreach UI

A Flask web app for poker-player outreach. Everything here is backed by **hosted
APIs only** (Apify, Airtable, OpenAI) — there is no local browser automation, so
this branch is **deployable to Vercel**.

> **Branches.** This is `main`, the deployable UI. The full browser-based Hendon
> Mob scraper — the headed-Chrome Cloudflare bypass and the resumable
> `python3 -m scraper.harvest` CLI that builds the local SQLite dataset — lives
> on the **`hendon-scraper`** branch. It needs a real desktop Chrome and a
> writable disk, so it can't run on serverless and is kept off `main`. The data
> it produces is loaded into Airtable, which is what this UI reads.

---

## What the UI does

The app has two tabs:

- **Instagram** — pull followers/following and profile details for any public
  handle (via Apify). Export to CSV/JSON, plus DM-launcher helpers.
- **Leaderboards → Hendon Mob database** — query the curated US player dataset
  already loaded into **Airtable** (~$10k–$1M total earnings). Filter by total
  earnings, recent earnings, last-active window, and state, then export to CSV.

Both tabs share a **Contact enrichment** action (email/socials lookup via Apify
social scraping + DuckDuckGo/OpenAI web-search fallback — no browser).

---

## Configuration (env vars)

Set these in a local `.env` (see `.env.example`) for local runs, or in the
**Vercel project settings** for the deploy:

```
APIFY_API_TOKEN=...        # Instagram scraping + social enrichment
AIRTABLE_API_KEY=pat...    # personal access token, scope: data.records:read
AIRTABLE_BASE_ID=app...    # the base holding the players table
AIRTABLE_TABLE_NAME=hendonmob   # table name or id
OPENAI_API_KEY=...         # optional — web-search enrichment fallback
```

Airtable column names are mapped in `scraper/airtable_store.py` (`FIELDS`) — edit
that dict if your columns are named differently. Filtering is pushed into
Airtable's `filterByFormula`, so only matching rows are fetched.

---

## Run locally

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

Then open **http://localhost:3002**.

---

## Deploy to Vercel

The repo already has the serverless scaffolding (`api/index.py` re-exports the
Flask app, `vercel.json` routes all traffic to it). To deploy:

1. Set the env vars above in the Vercel project settings.
2. Point the project at this branch (`main`) and deploy.

**Timeout note.** Vercel functions cap at 10s (Hobby) / 60s default, 300s max
(Pro). Instagram and Airtable calls are usually fine; large contact-enrichment
batches run synchronously (~5s/person) and can exceed the limit — keep batches
small, and raise `maxDuration` on Vercel Pro if needed.

---

## What's in here

| Path | What it is |
|---|---|
| `app.py` | Flask web UI — Instagram + Leaderboards (Airtable) + enrichment. Single file: HTML/JS frontend + JSON API routes |
| `scraper/airtable_store.py` | Reads the curated Hendon Mob dataset from Airtable (the UI's "Hendon Mob database" mode) |
| `enrichment/` | Contact enrichment (email/socials) — Apify social scraping + web-search fallback |
| `api/index.py` | Vercel serverless entry point — re-exports the Flask app |
| `vercel.json` | Vercel build/route config |
