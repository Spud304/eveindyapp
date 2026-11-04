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

## Status (2026-11-03)
Build order steps 0–7 are done, and step 8's compressed ore calculator; each has a "Step N progress" section in `docs/redesign.md` with what was built, verified and left open. **Next:** real buy prices (Janice API needs a key from the user; ESI regional orders need none), and checking the Shopping list's copy format against a real Janice / multibuy paste.

Open from steps 6–7:
- Copies attributed to a plan lose that attribution once delivered; a picked BPC that disappears is skipped without a warning.
- The split search is greedy; `_search_parallel` in `backend/engine/planner.py` documents its rules.
- Plan editors (others changing a plan) are deferred.
- Browser tests make test BPCs with `manage.py playwright_blueprint` and put test characters in a made-up corp with `login(corp=...)` (reserved ids only).
- No Prettier config exists; do not run Prettier on frontend files (it reformats them with its defaults).

Reference sources (prefer these over memory for game mechanics):
- Decompiled game client: `/mnt/g/eve projects/src` (`industry/` for job cost, time, materials, max runs; `eve/common/script/util/industryCommon.py` for how modifiers are built). Findings are recorded under "Client code" in `docs/redesign.md`.
- SDE: imported in the dev DB; `apps/sde/gamedata.py` builds engine inputs. `industryModifierSources` and `industryTargetFilters` drive structure and rig bonuses.
- ESI: the live OpenAPI spec at `https://esi.evetech.net/meta/openapi.json` for routes, scopes and fields.
- The AT Tool repo (`/mnt/g/SpudsATTool`) for stack patterns.

Dev data: the account with id 1 is the user's real account (main Starch Man, plus Potato Ricer and Industrial Fryer; ESI linked as Director of The Fry Cooks). Plans "dreadbatch 1" and "maelstroms" and 8 discovered stations are real dev data. Test with the Playwright reserved ids, not with this account.

## Commits
- Commit directly to `master` (solo project); no feature branches unless asked.
- Before committing code:
  - Flask app: `uv run --group test pytest tests/unit/ -q` from the repo root.
  - Backend: `uv run pytest -q` from `backend/` (needs the dev Postgres up), and `uvx ruff check` + `uvx ruff format` there.
  - Frontend: `npx tsc -b`, `npx eslint .` and `npx vite build` from `frontend/`.
  - UI changes: browser tests with both dev servers running, `uv run pytest playwright_tests --browser chromium --tracing retain-on-failure -q` from `backend/`. They log in as reserved character ids 900000001–900000099 and `playwright_cleanup` wipes those accounts first; real accounts are never touched.
- Playwright is pinned to 1.58.0: newer versions have no Chromium build for this box's Ubuntu 20.04, and `playwright install` deletes browsers no installed version uses.
