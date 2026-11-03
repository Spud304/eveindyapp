# EVE Indy App

Flask + Celery app for EVE Online industry planning. A plan-centric redesign is in progress: read `docs/redesign.md` before making design or structural changes, and keep it updated when decisions change. Frontend style: `docs/ui-design.md`.

## Commits
- Commit directly to `master` (solo project); no feature branches unless asked.
- Before committing code: `uv run --group test pytest tests/unit/ -q` and `ruff format` on changed files.
