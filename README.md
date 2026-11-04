# EVE Indy App

Industry planning for EVE Online, built around plans: "I have these characters, skills, stations and
assets (personal and corp); I want to build these things. What's the plan, and where are we on it?"
Logs in with EVE SSO and reads characters and corporations through ESI. A personal project, not
affiliated with CCP Games.

## What it does

- **Plans**: lines of items to build, merged into one build tree. Shopping list (priced from Jita 4-4
  sell orders, with volumes), blueprints and where each job's blueprint comes from, schedule across
  your characters' slots, progress from live industry jobs, and costs.
- **Blueprints**: owned BPOs and BPCs (character and corp), copies being made, invention for T2,
  automatic copying or spreading runs over BPCs when that finishes the plan sooner, BPC lines that
  pick specific BPCs, and opt-in buy options for BPCs or an extra BPO with their time and cost.
- **Compressed ore**: the cheapest compressed ore for a plan's minerals, with your reprocessing skills,
  the refinery's rigs and Jita order depth.
- **Sharing**: a plan can be shown to your corporation (they log in) or to anyone with a link (station
  and character names hidden).
- **Library and dashboard**: every blueprint your characters and corps hold, and every job, idle slot
  and sync problem at a glance.

Design and decisions: [`docs/redesign.md`](docs/redesign.md). Frontend style:
[`docs/ui-design.md`](docs/ui-design.md).

## Stack

- `backend/`: Django 5.2 + django-ninja (OpenAPI), Postgres 16, Redis, Celery. `backend/engine/` is
  the planning engine: pure Python, no Django imports.
- `frontend/`: React + TypeScript + Vite; API types generated from the backend's OpenAPI schema.
- `deploy/`: Docker images, compose files and the cron schedule for syncs.

## Development

You need [uv](https://github.com/astral-sh/uv), Node 24, Docker and an
[EVE developer application](https://developers.eveonline.com/) whose callback is
`http://localhost:5050/callback`.

```bash
docker compose -f deploy/docker-compose.dev.yml up -d     # Postgres, Redis, sync worker, scheduler
cp deploy/.env.example deploy/.env                         # fill in the EVE_* values
cd backend && uv sync && uv run python manage.py migrate
uv run python manage.py import_sde --check-latest          # download and import CCP's static data
uv run python manage.py runserver 127.0.0.1:8000
cd frontend && npm ci && npm run dev                       # http://localhost:5050
```

Tests: `uv run pytest -q` in `backend/` (needs the dev Postgres), `npx tsc -b`, `npx eslint .` and
`npx vite build` in `frontend/`, and browser tests with both dev servers running:
`uv run pytest playwright_tests --browser chromium -q` in `backend/`.

## Production

`deploy/docker-compose.yml` runs Caddy (the built frontend, TLS from Let's Encrypt, and a proxy for
`/api`, `/auth`, `/callback` and `/static`), the Django app, a Celery worker, the cron
scheduler (`deploy/crontab`), Postgres and Redis. Django admin is not proxied; reach it on the
host at `http://127.0.0.1:8000/admin/` (through an SSH tunnel on a server).

1. Point a domain at the server and register an EVE application with the callback
   `https://<domain>/callback`.
2. `cp deploy/.env.example deploy/.env` and fill it in (`ACME_EMAIL` is required).
3. `docker compose -f deploy/docker-compose.yml up -d --build`
4. Import the static data once (afterwards the scheduler checks for new builds daily):
   `docker compose -f deploy/docker-compose.yml exec web python manage.py import_sde --check-latest`

With another reverse proxy already on 80/443, set `SITE_ADDRESS=:80` and let that proxy forward to
Caddy.

## ESI scopes

Login asks for `publicData` only. Linking a character for planning asks for: skills, assets,
blueprints, industry jobs, corporation roles, corporation assets, blueprints, industry jobs and
divisions (read with whichever character has the role), and structures (names of structures you can
dock at). The list is `EVE_CHARACTER_SCOPES` in `backend/config/settings/base.py`.
