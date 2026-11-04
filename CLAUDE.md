# EVE Indy App

EVE Online industry planning. A plan-centric redesign is in progress: read `docs/redesign.md` before making design or structural changes, and keep it updated when decisions change. Frontend style: `docs/ui-design.md`.

Two codebases live here until the new stack replaces the old one:
- `src/`: the old Flask + Celery app (still runnable).
- `backend/`: the new Django + django-ninja project. `backend/engine/` is the pure planning engine (no Django imports), imported as `engine`.
- `frontend/`: React + TypeScript + Vite app for the new backend.

Dev setup:
- Postgres and Redis: `docker compose -f deploy/docker-compose.dev.yml up -d` (ports 5434 / 6381).
- Django: `uv run python manage.py runserver 127.0.0.1:8000` from `backend/`.
- Frontend: `npm run dev` from `frontend/`. Vite serves the app on http://localhost:5050 and proxies `/api`, `/auth` and `/callback` to Django. 5050 is the port the EVE application's registered callback uses, so open the app there.
- On-demand syncs need a worker: `uv run celery -A config worker -l INFO` from `backend/`.
- After changing API schemas: `npm run gen:api` from `frontend/` (Django must be running).
- Vite's watcher can miss a second quick edit to the same file (seen 2026-11-03: a served module lacked a new import). If the browser shows code you already changed, restart `npm run dev`.
- Never use `/auth/dev-login` with a real character id: it upserts the character with a dev owner hash, which counts as a transfer and deletes its ESI token.
- Production stack: `deploy/docker-compose.yml`.

## Commits
- Commit directly to `master` (solo project); no feature branches unless asked.
- Before committing code:
  - Flask app: `uv run --group test pytest tests/unit/ -q` from the repo root.
  - Backend: `uv run pytest -q` from `backend/` (needs the dev Postgres up), and `uvx ruff check` + `uvx ruff format` there.
  - Frontend: `npx tsc -b`, `npx eslint .` and `npx vite build` from `frontend/`.
  - UI changes: browser tests with both dev servers running, `uv run pytest playwright_tests --browser chromium --tracing retain-on-failure -q` from `backend/`. They log in as reserved character ids 900000001–900000099 and `playwright_cleanup` wipes those accounts first; real accounts are never touched.
- Playwright is pinned to 1.58.0: newer versions have no Chromium build for this box's Ubuntu 20.04, and `playwright install` deletes browsers no installed version uses.
