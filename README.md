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

First time:

```bash
# backend/.env with EVE_CLIENT_ID, EVE_CLIENT_SECRET and EVE_CALLBACK_URL (not deploy/.env,
# which is for the production server and would be read by the dev backend too)
make services                                  # Postgres, Redis, sync worker, scheduler (Docker)
cd backend && uv sync && cd ../frontend && npm ci && cd ..
make migrate
make sde                                       # download and import CCP's static data
```

Then `make run` starts Django (127.0.0.1:8000) and Vite (http://localhost:5050) in one terminal;
Ctrl+C stops both. `make help` lists the rest: `make check` runs the lint and tests asked for
before a commit (needs the services), `make playwright` the browser tests (with `make run` going),
`make gen-api` regenerates the frontend's API types, `make logs` follows the worker and
scheduler, `make services-recreate` fixes containers whose mounts went stale after a Docker
Desktop restart.

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
