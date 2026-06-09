"""
Leaderboard / ranking scrapers.

⚠️ Scope today: this package is *only* The Hendon Mob scraper. The package is
named `scraper` (singular), but the plan is to generalize to many sources —
each new source (e.g. WSOP, GPI, PocketFives) will get its own module(s) here,
and the shared machinery (cache, harvest loop, CLI) will be factored out of the
Hendon-Mob-specific code below. Until that happens, "the scraper" *is* the
Hendon Mob scraper.

Current modules (all Hendon-Mob-specific):
    hendon_mob.py      core scraper — drives headed Chrome past Cloudflare,
                       parses the ranking + profile pages. (Also contains a WSOP
                       JSON path and a generic LLM table parser used by the UI.)
    hendon_harvest.py  resumable two-phase (roster → profiles) harvest engine
    hendon_store.py    SQLite cache layer (data/hendon_mob.db)
    harvest.py         batch harvester CLI (python3 -m scraper.harvest)

When adding a new source, prefer a parallel set of `<source>_*.py` modules over
threading conditionals through the Hendon Mob ones — that keeps each source's
quirks (Cloudflare, pagination, profile shape) isolated and is the cleanest path
to the eventual shared base.
"""
