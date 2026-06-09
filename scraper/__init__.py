"""
Leaderboard / ranking data access.

On this branch (`main`, the Vercel-deployable UI) the only module is the
Airtable reader — the runtime source of truth for the UI's "Hendon Mob
database" tab:

    airtable_store.py  reads the curated Hendon Mob US player dataset from
                       Airtable (filters pushed into the Airtable query).

The live browser-based scrapers (headed-Chrome Cloudflare bypass, the resumable
SQLite harvest engine, and the `python3 -m scraper.harvest` CLI) live on the
`hendon-scraper` branch — they require a real desktop browser and a writable
disk, so they can't run on serverless and are kept out of the deploy.
"""
