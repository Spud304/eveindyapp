.PHONY: help run dev services services-recreate services-down dev-backend dev-frontend stop logs \
        migrate sync sde gen-api test test-backend test-frontend lint format check playwright \
        backup prod-build prod-up prod-logs

SHELL := /bin/bash
COMPOSE_DEV  = docker compose -f deploy/docker-compose.dev.yml
COMPOSE_PROD = docker compose -f deploy/docker-compose.yml
# Dev servers, as CLAUDE.md runs them. 5050 is the port the EVE application's callback uses.
BACKEND  = cd backend && uv run python manage.py runserver 127.0.0.1:8000
FRONTEND = cd frontend && npm run dev
DEV_PORTS = 8000 5050

help:              ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | expand -t 20

## ---- development ----

services:          ## start Postgres, Redis, the sync worker and the scheduler (Docker)
	$(COMPOSE_DEV) up -d

services-recreate: ## recreate the containers (after a Docker Desktop restart left a mount stale)
	$(COMPOSE_DEV) up -d --force-recreate

services-down:     ## stop the containers (the database volume is kept)
	$(COMPOSE_DEV) down

dev-backend:       ## Django on 127.0.0.1:8000 (reloads on change)
	$(BACKEND)

dev-frontend:      ## Vite on http://localhost:5050 (proxies /api, /auth, /callback to Django)
	$(FRONTEND)

# Each server runs in its own process group (setsid), and the trap stops exactly those groups, so
# servers started elsewhere are never touched. Background jobs of a non-interactive shell ignore
# Ctrl+C, hence the trap; if either server exits, the other is stopped too.
run: services      ## everything for local development in one terminal; Ctrl+C stops both servers
	@for port in $(DEV_PORTS); do \
	  if (exec 3<>/dev/tcp/127.0.0.1/$$port) 2>/dev/null; then \
	    echo "port $$port is in use: a dev server is already running (make stop ends leftovers)"; exit 1; \
	  fi; \
	done; \
	trap 'trap - INT TERM EXIT; kill -- -$$api -$$web 2>/dev/null; true' INT TERM EXIT; \
	  setsid bash -c '$(BACKEND)' & api=$$!; \
	  setsid bash -c '$(FRONTEND)' & web=$$!; \
	  wait -n

dev: run

# The [m] / [f] keep the patterns from matching the shell that runs pkill (its command line holds them).
STOP_SERVERS = pkill -f "[m]anage.py runserver 127.0.0.1:8000"; pkill -f "$(CURDIR)/[f]rontend/node_modules/.bin/vite"; true

stop:              ## kill dev servers left behind (this checkout's runserver and Vite only)
	@$(STOP_SERVERS)

logs:              ## follow the worker and scheduler logs
	$(COMPOSE_DEV) logs -f --tail=100 worker scheduler

migrate:           ## apply Django migrations to the dev database
	cd backend && uv run python manage.py migrate

sync:              ## sync ESI now for every account (as the hourly cron does)
	cd backend && uv run python manage.py sync_esi --all

sde:               ## download and import CCP's latest SDE build if it is newer
	cd backend && uv run python manage.py import_sde --check-latest

gen-api:           ## regenerate the frontend API types (Django must be running)
	cd frontend && npm run gen:api

backup:            ## dump the dev database together with backend/.env (deploy/backup-dev.sh)
	deploy/backup-dev.sh

## ---- checks (CLAUDE.md, before committing) ----

test: test-backend test-frontend

test-backend:      ## pytest; needs `make services` (tests use Postgres on :5434)
	cd backend && uv run pytest -q

test-frontend:     ## type check, lint and production build
	cd frontend && npx tsc -b && npx eslint . && npx vite build

lint:              ## ruff check and format check (backend), eslint (frontend)
	cd backend && uvx ruff check && uvx ruff format --check
	cd frontend && npx eslint .

format:            ## ruff format the backend (no Prettier on the frontend: see CLAUDE.md)
	cd backend && uvx ruff format

check: lint test   ## everything CLAUDE.md asks for before a commit, except the browser tests

playwright:        ## browser tests against the running dev servers (`make run` in another terminal)
	cd backend && uv run python manage.py playwright_cleanup
	cd backend && uv run pytest playwright_tests --browser chromium --tracing retain-on-failure -q

## ---- production stack (not deployed; README "Production") ----

prod-build:        ## build the production images
	$(if $(wildcard deploy/.env),,$(error deploy/.env not found: create it on the server only, never on a dev machine))
	$(COMPOSE_PROD) build

prod-up:           ## start or update the production stack
	$(if $(wildcard deploy/.env),,$(error deploy/.env not found: create it on the server only, never on a dev machine))
	$(COMPOSE_PROD) up -d --build --remove-orphans

prod-logs:         ## follow the production logs
	$(COMPOSE_PROD) logs -f --tail=200
