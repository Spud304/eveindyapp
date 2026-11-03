# EVE Indy App

EVE Online industry planning. A plan-centric redesign is in progress: read `docs/redesign.md` before making design or structural changes, and keep it updated when decisions change. Frontend style: `docs/ui-design.md`.

Two codebases live here until the new stack replaces the old one:
- `src/`: the old Flask + Celery app (still runnable).
- `backend/`: the new Django + django-ninja project. `backend/engine/` is the pure planning engine (no Django imports), imported as `engine`. Dev Postgres and Redis: `docker compose -f deploy/docker-compose.dev.yml up -d` (ports 5434 / 6381).

## Commits
- Commit directly to `master` (solo project); no feature branches unless asked.
- Before committing code:
  - Flask app: `uv run --group test pytest tests/unit/ -q` from the repo root.
  - Backend: `uv run pytest -q` from `backend/` (needs the dev Postgres up), and `uvx ruff check` + `uvx ruff format` there.
