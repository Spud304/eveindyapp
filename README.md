# EVE Industry App

A web application for tracking and planning manufacturing in EVE Online. Authenticates via EVE SSO and pulls character data from the ESI API. Note: this is a personal project for learning purposes and is not affiliated with CCP Games. Also I used claude to design the frontend, I'm a backend dev

## Features

- **Blueprint Library** -- View all blueprints owned by your character, with type names and location names resolved automatically. Data is cached for 24 hours with a manual refresh option.
- **Material Calculator** -- Select a manufacturable item and quantity, then get a full recursive bill of materials broken down to raw materials. Supports per-blueprint Material Efficiency (ME) overrides and BPC run planning.
- **Blueprint Ownership Status** -- The calculator cross-references your cached blueprints to show which BPOs/BPCs you own, which are missing, and how many copy jobs you need.
- **Industry Jobs** -- View your character's active industry jobs from ESI.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (package manager)
- An EVE Online developer application (for SSO credentials)
- The EVE Static Data Export (SDE) as a SQLite database (`sqlite-latest.sqlite`)

## ESI Scopes
The app requires the following ESI scopes to function properly, some of these are just allocated atm but not fully utilized yet, i just kinda grabbed anything indy related to pull as much data as possible for future features:
- `publicData` (for type and location names)
- `esi-wallet.read_character_wallet.v1` (for character wallet balance)
- `esi-wallet.read_corporation_wallet.v1` (for corporation wallet balance, if applicable)
- `esi-search.search_structures.v1` (to resolve blueprint locations in player-owned structures)
- `esi-assets.read_assets.v1` (to pull character-owned blueprints and assets)
- `esi-corporations.read_structures.v1` (to resolve blueprint locations in corporation-owned structures)
- `esi-industry.read_character_jobs.v1` (to show active industry jobs on the dashboard)
- `esi-characters.read_blueprints.v1` (to pull character-owned blueprints and their ME levels)
- `esi-wallet.read_corporation_wallets.v1` (to pull corporation wallet balance, if applicable)
- `esi-corporations.read_divisions.v1` (to pull corporation wallet balance, if applicable)
- `esi-corporations.read_contacts.v1` (to resolve corporation-owned blueprint locations)
- `esi-assets.read_corporation_assets.v1` (to pull corporation-owned blueprints and assets, if applicable)
- `esi-corporations.read_blueprints.v1` (to pull corporation-owned blueprints and their ME levels, if applicable)
- `esi-corporations.read_starbases.v1` (to resolve blueprint locations in starbases, if applicable)
- `esi-industry.read_corporation_jobs.v1` (to show corporation industry jobs on the dashboard, if applicable)
- `esi-industry.read_character_mining.v1` (to show active mining jobs on the dashboard)
- `esi-industry.read_corporation_mining.v1` (to show corporation mining jobs on the dashboard, if applicable)

## Setup

1. Clone the repo.

2. Copy the example env file and fill in your values:

```
cp .env.example .env
```

| Variable | Description |
|---|---|
| `CLIENT_ID` | EVE SSO application client ID |
| `CLIENT_SECRET` | EVE SSO application client secret |
| `CALLBACK_URL` | OAuth callback URL (default `http://localhost:5050/callback`) |
| `DB_NAME` | App database name without extension (default `test`) |
| `STATIC_DB` | SDE database name without extension (default `sqlite-latest`) |
| `SECRET_KEY` | Flask secret key for session signing |
| `SCOPES` | JSON array of ESI scopes to request |

3. Place the SDE SQLite file at `src/instance/sqlite-latest.sqlite`. The app database (`localuser.sqlite`) is created automatically on first run.

4. Install dependencies:

```
uv sync
```

## Running

### Local development

```
uv run python src/main.py
```

The app starts on `http://localhost:5050`.

### Tests

```
uv run pytest tests/unit/ -v          # unit only
uv run pytest tests/integration/ -v   # integration only
uv run pytest -v                      # all 108 tests
```

### Docker

```
docker compose up --build
```

The `src/instance/` directory is mounted as a volume so database files persist across container restarts. The container runs gunicorn with 4 workers.

## Project Structure

```
src/
  main.py             -- App factory, config, blueprint registration
  auth.py             -- EVE SSO login/callback/logout
  user.py             -- Character info page
  industry.py         -- Blueprints, materials DFS, calculator, jobs
  utils.py            -- ESI request helpers, token generation
  constants.py        -- ESI base URL
  application.py      -- Flask Application subclass
  models/
    models.py         -- All ORM models (User, CachedBlueprint, SDE tables)
  templates/          -- Jinja2 HTML templates
  instance/           -- SQLite database files (not committed)
```

## TODO

- Token refresh -- access tokens expire after ~20 minutes; the app should automatically refresh them using the stored refresh token before making ESI calls
- Invention support -- handle T2 blueprint invention chains (datacores, decryptors, probability)
- Multi-character support -- allow users to link multiple characters and aggregate blueprint ownership
- Job notifications -- alert when industry jobs complete
- Search improvements -- support partial matching and category filtering on the calculator search
- Test suite -- add unit and integration tests for the DFS logic and ESI helpers
- Project planner -- allow users to save and share build plans with specific items, quantities, and ME levels, and track progress as they acquire materials and complete jobs
- Reactions support -- add a section for chemical reactions in refineries, with similar DFS material breakdowns and job planning
- Corporation support -- allow users to link corporation accounts and view corporation-owned blueprints and jobs, with appropriate permission checks
- maybe at some point ill rewrite the frontend in react
