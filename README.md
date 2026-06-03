# Hendon Mob / Leaderboard Scraper

A local tool for scraping poker leaderboard data — primarily [The Hendon Mob](https://thehendonmob.com)
all-time money lists. It has two ways to run:

1. **Web UI** — paste a Hendon Mob URL, scrape a bounded page range, view the
   results in a table, and download CSV/JSON. Good for quick, one-off pulls.
2. **Batch harvester (CLI)** — a resumable, multi-page crawler that caches every
   player into a local SQLite database and can export the whole roster to CSV.
   Good for building a complete dataset over time.

The Hendon Mob scraping needs **no API keys**. (The repo also contains an
Instagram scraper and a contact-enrichment feature on other UI tabs — those need
API keys and can be ignored if you only want leaderboard data.)

---

## Prerequisites

- **Python 3.9+**
- **Google Chrome** installed on the machine. The scraper drives a real, visible
  Chrome window to get past The Hendon Mob's Cloudflare protection — a headless
  browser gets blocked, so **a Chrome window will pop open while it runs. That is
  expected — don't close it.**

## Setup

```bash
# from the project root
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

That's it — no `.env` or API keys are required for Hendon Mob scraping.

---

## Option 1 — Web UI

```bash
source venv/bin/activate          # if not already active
python3 app.py
```

Then open **http://localhost:3002** in your browser.

1. Go to the **Leaderboards** tab.
2. Paste a Hendon Mob money-list URL
   (e.g. `https://pokerdb.thehendonmob.com/ranking/all-time-money-list/`).
3. Set the number of pages (capped at 10 in the UI), optionally toggle "US only"
   and "fetch full profiles," and run it.
4. A Chrome window opens and solves the Cloudflare check (this takes a few seconds
   the first time). Results appear in a table.
5. Use the **Download CSV / JSON** buttons to save the results.

The UI does **not** write to the database — it just shows results and lets you
download them. For a full dataset, use the batch harvester below.

> To stop the server, press `Ctrl+C` in the terminal.

---

## Option 2 — Batch harvester (CLI)

The harvester walks the full money list across many pages, optionally enriches
each player's profile (location, socials, recent earnings), and caches everything
in a local SQLite database at `data/hendon_mob.db`. It is **resumable** — stop it
with `Ctrl+C` and re-run the same command to pick up where it left off.

Run all commands with the venv active (`source venv/bin/activate`).

```bash
# Harvest the roster and enrich profiles (resumable; safe to stop and re-run)
python3 -m scraper.harvest run

# Useful variations:
python3 -m scraper.harvest run --pages 20        # only walk the first 20 roster pages
python3 -m scraper.harvest run --us-only         # only enrich US players
python3 -m scraper.harvest run --limit 100       # only enrich 100 profiles this run
python3 -m scraper.harvest run --no-profiles     # roster only, skip profile enrichment

# Show how many players / enriched profiles are cached
python3 -m scraper.harvest status

# Export the cached data to CSV
python3 -m scraper.harvest export -o players.csv
python3 -m scraper.harvest export --us-only --scraped-only -o us_players.csv
```

### About the database

- It lives at `data/hendon_mob.db` and is **local-only** — it is intentionally
  *not* committed to git (it's in `.gitignore`). Each person builds their own
  cache by running the harvester.
- **Do not run `git checkout`/`git clean` in a way that would delete `data/`** —
  that wipes your harvested cache.
- To start fresh, just delete `data/hendon_mob.db` and re-run.

---

## Troubleshooting

- **"undetected-chromedriver" / version mismatch errors after Chrome updates.**
  Chrome auto-updates and can outpace the driver. Fix:
  ```bash
  pip install -U undetected-chromedriver
  ```
- **The scrape returns no rows / a blank page.** Usually Cloudflare didn't clear.
  Make sure the Chrome window that pops up isn't being closed, and try again. If
  it persists, The Hendon Mob may have changed its layout or challenge.
- **No Chrome window appears / "cannot find Chrome."** Install Google Chrome (not
  just Chromium) and re-run.
- **Working with Claude.** This repo works well with Claude Code — you can open the
  folder and ask it to set up the venv, run the scraper, or fix the Chrome/driver
  errors above.

---

## What's in here

| Path | What it is |
|---|---|
| `app.py` | Flask web UI (Leaderboards tab is the Hendon Mob scraper) |
| `scraper/hendon_mob.py` | Core scraper — drives headed Chrome, parses the tables |
| `scraper/harvest.py` | Batch harvester CLI (`run` / `status` / `export` / `backfill`) |
| `scraper/hendon_store.py` | SQLite cache layer (`data/hendon_mob.db`) |
| `data/` | Local SQLite cache (gitignored) |
