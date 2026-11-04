# ESI Integration & Operations Engineer findings

## Summary
The ESI integration is mostly correct for this stage. The compatibility date is the newest one ESI offers, cron intervals match the spec's cache times, ETags are keyed per character, and a feed that fails with an ESI error is recorded while the rest still run. The real gaps are in failure paths. An SSO hiccup during token refresh raises an exception that no handler catches, so the whole sync run aborts and leaves no FeedStatus record. An on-demand sync that overlaps a cron sync can double the corp asset and blueprint rows. Nothing in the UI flags data that has stopped refreshing, which matters because plans silently use whatever was last synced. I found no P0 or P1 issues in my lane.

## What I checked
- `backend/apps/esi/client.py` (headers, ETag/304, 420/429, 5xx breaker, paging), `backend/apps/esidata/{sync,market,tasks,jobs,api,overview_api}.py`, `management/commands/sync_esi.py`, `apps/core/locks.py`, `apps/accounts/{tokens,sso,services}.py`, `apps/planning/stations.py` (structure lookups), `apps/planning/tracker.py:121` (match_after_sync).
- `deploy/crontab`, `entrypoint.sh`, `docker-compose.yml`, `docker-compose.dev.yml`, `Dockerfile.backend`; `backend/config/settings/{base,dev,prod}.py`.
- Live ESI spec (public GET): `/meta/openapi.json` with no compat header and with `X-Compatibility-Date: 2026-08-18`, plus `/meta/compatibility-dates`. I compared each used route's `x-cache-age`, `x-rate-limit` group, `X-Pages` header and response fields against the code.
- Django/asgiref source in `backend/.venv` (ASGI sync-view threading).
- Probe tests I wrote in the scratchpad (`/tmp/claude-1000/-home-spud304-python-eveindyapp/a41ec20f-9548-4413-8119-2be160ab868f/scratchpad/ops-tests/test_ops_probe.py`), run with `uv run pytest` against the test DB. pytest-django reported that `test_eveindy` already existed and recreated it. Both probes passed (output quoted below).
- `docs/redesign.md` ESI / deploy / step-progress sections; `grep` for license or terms notes in `docs/` and `README.md` (none recorded).
- I made no authenticated ESI calls.

## Findings

### OPS-1: An SSO error during token refresh aborts the whole sync run and records nothing
- **Severity:** P2
- **Status:** verified
- **Evidence:**
  - `apps/accounts/tokens.py:48-59` catches only `sso.SsoTokenRejected`.
  - `sso.refresh_tokens` raises plain `SsoError` for network errors, SSO 5xx, a non-JSON body (`sso.py:113-130`), discovery failure (`sso.py:42-43`) and JWKS or JWT failures (`sso.py:155-156`). `tokens.py:67` raises it for a character mismatch.
  - `apps/esidata/sync.py:90` catches only `(EsiError, TokenUnavailable, FeedUnavailable)`, and `SsoError` subclasses neither.
  - Probe `test_sso_outage_during_refresh_aborts_whole_account_sync`: with `refresh_tokens` raising `SsoError("HTTP 502")`, `sync.sync_account` raised. The only FeedStatus row was `(90000002, 'skills', False)` with an empty error, and ESI calls made were `[('/characters/affiliation/', None)]`, so no other character or corp feed ran. `apps/planning/stations.py:155` has the same gap, so an SSO hiccup during station discovery returns a 500.
- **Problem:** Access tokens are refreshed whenever the cron jobs line or the full sync needs one, so an SSO blip (for example around the daily downtime) recurs. When it happens:
  - `sync_esi --all` stops for every remaining character, corp and account in that run.
  - The Celery task fails.
  - An existing FeedStatus row keeps its old "ok" state, because `status.save()` is never reached, so the dashboard's "failing feeds" list (`overview_api.py:318`) shows nothing.

  Data silently stays as old as the last good run.
- **Recommendation:** In `tokens.access_token`, wrap the non-rejection `SsoError` from `_refresh` in a new transient `TokenUnavailable` subclass (for example `TokenRefreshFailed`) that does not set `refresh_failed_at`. `_record` and `stations.py` then handle it like any other feed failure. Add a test with the FakeEsi harness.
- **Effort:** S
- **Tradeoffs / dependencies:** none

### OPS-2: Overlapping syncs can duplicate asset and blueprint rows
- **Severity:** P2
- **Status:** verified
- **Evidence:**
  - `_write_assets` / `_write_blueprints` (`sync.py:133-192`) delete and then bulk-insert in one transaction, with no unique constraint on `(owner_kind, owner_id, item_id)` (`models.py:119-126, 146-152`).
  - The cron path takes an advisory lock per mode (`sync_esi.py:40`), but the Celery path (`tasks.py:300-317`, triggered by "refresh now" in `api.py:41` and by first link in `accounts/views.py:49`) takes none.
  - The cron modes `accounts:jobs` and `accounts:all` are deliberately allowed to overlap.
  - Probe `test_overlapping_asset_writes_duplicate_rows`: a second `_write_assets` started while the first transaction was open left 10 rows for 5 items (`rows after overlapping writes: 10 errors: []`). This is Postgres READ COMMITTED behaviour: the second DELETE skips rows the first one already deleted and cannot see the first one's inserts.
- **Problem:** If the user clicks "refresh now" (or links a character) while the :07 full cron sync is writing the same corp's assets, stock doubles until the next hourly sync. The plan then shows materials on hand that do not exist and the shopping list buys too little. Celery `--concurrency=2` with two accounts in one corp hits the same window. The window is short, so this is rare, but the error is silent.
- **Recommendation:** Inside the `transaction.atomic()` in `_write_assets` and `_write_blueprints`, take `pg_advisory_xact_lock(crc32(f"{feed}:{kind}:{owner_id}"))` before the delete. Writers then serialize and the second one replaces the first one's rows. Optionally add a unique constraint on `(owner_kind, owner_id, item_id)` as a backstop. That turns a missed race into a recorded failure rather than doubled stock, but it needs a check that ESI never repeats an item_id within one snapshot (see OPS-5).
- **Effort:** S
- **Tradeoffs / dependencies:** A unique constraint makes OPS-5's mid-fetch duplicates fail the feed loudly instead of doubling rows, which is arguably the better outcome.

### OPS-3: Data that stopped refreshing is not flagged anywhere the user plans from
- **Severity:** P2
- **Status:** verified
- **Evidence:**
  - Dashboard problems list only `FeedStatus.ok=False` rows (`overview_api.py:318`).
  - Feed age (`fetched_at`) appears only on the Setup page (`frontend/src/features/setup/SetupPage.tsx:166-167`). Planning code never reads it (`grep fetched_at apps/planning` only hits `ore_api.py:158`, market time).
  - `/api/health` reports DB and SDE only (`apps/core/api.py:23-36`).
  - OPS-1 shows a sync can fail without updating FeedStatus at all.
- **Problem:** The app runs unattended on localhost, using the dev compose scheduler. If the scheduler container is stopped, Docker or WSL isn't running, a run crashes (OPS-1), or the DB is migrated ahead of the containers, plans keep computing from assets, blueprints and jobs that may be days old, with no warning on the dashboard or plan.
- **Recommendation:** In the dashboard problems, add one "warn" line per owner and feed whose `fetched_at` is older than about 3× its cron interval (jobs: 30 min; others: 3 h), for example "corporation X assets last synced 2 days ago".
- **Effort:** S
- **Tradeoffs / dependencies:** Thresholds duplicate the crontab intervals. Keep them as constants next to `CORP_FEEDS` with a comment pointing at `deploy/crontab`.

### OPS-4: Any HTTP 401 from SSO marks the token permanently rejected
- **Severity:** P3
- **Status:** verified (code); inferred (that EVE SSO answers a bad client secret with 401 `invalid_client`, per RFC 6749 §5.2. A refresh with a wrong `EVE_CLIENT_SECRET` against SSO would confirm it.)
- **Evidence:** `sso.py:115-121`: `if error in ("invalid_grant", "invalid_token") or resp.status_code == 401: raise SsoTokenRejected`. `tokens.py:50-56` then sets `refresh_failed_at`, which `access_token` and `corp_source` (`sync.py:326`) treat as final.
- **Problem:** A client-side credential problem flags every character's token as rejected even though the refresh tokens are still valid. Examples are a rotated app secret on developers.eveonline.com or a typo in `deploy/.env` or `backend/.env`. Recovery means re-linking every character or clearing `refresh_failed_at` by SQL.
- **Recommendation:** Treat only `invalid_grant` / `invalid_token` as token rejection. Raise plain `SsoError` for a 401 whose error is `invalid_client` or missing. With OPS-1's fix, that is recorded as a transient feed failure.
- **Effort:** S
- **Tradeoffs / dependencies:** depends on OPS-1 so the plain `SsoError` doesn't crash the run.

### OPS-5: Paged fetches can mix two ESI snapshots
- **Severity:** P3
- **Status:** inferred. That ESI can roll a route's cache between page requests is not stated in the OpenAPI spec. The spec confirms each page has its own `ETag`/`Last-Modified` (`/corporations/{id}/assets` 200 headers: `ETag`, `Last-Modified`, `X-Pages`). Comparing `Last-Modified` across pages during a real corp asset sync would confirm it.
- **Evidence:** `client.py:133-151` (`paged`) and `market.py:35-45` fetch pages 2..N without checking that they share page 1's `Last-Modified`, and use page 1's `X-Pages` even if the page count changed.
- **Problem:** If the hourly cache expires between page 1 and page N of corp assets or blueprints, items that moved pages appear twice or not at all. Stock is then wrong until the next sync. This only affects multi-page owners (large corp hangars).
- **Recommendation:** In `paged`, have `request(..., with_pages=True)` also return `Last-Modified`. If any later page's value differs from page 1's, refetch once from page 1. If it differs again, raise `EsiError` so the feed is recorded as failed instead of written.
- **Effort:** S
- **Tradeoffs / dependencies:** one extra round of requests in the rare case

### OPS-6: Gaps in error-limit and Retry-After handling
- **Severity:** P3
- **Status:** verified (code and headers); inferred (420 semantics)
- **Evidence:**
  - The live spec response exposes `X-Esi-Error-Limit-Remain` / `X-Esi-Error-Limit-Reset` (`access-control-expose-headers`), and routes without an `x-rate-limit` group still fall under the legacy error limit (`/markets/prices`, `/characters/affiliation`, `/universe/structures/{id}`, `/characters/{id}`, `/corporations/{id}` have none in the spec). `client.py:122-131` logs only `X-Ratelimit-*`.
  - `client.py:95-100` treats 420 like 429 and reads `Retry-After` (default 5). A 420 carries `X-Esi-Error-Limit-Reset` instead (inferred).
  - `int(resp.headers.get("Retry-After"))` raises `ValueError` on an HTTP-date value, and nothing catches it.
  - `stations.py:147-160` tries `/universe/structures/{id}` with every character, so each one without docking access adds a 4xx.
- **Problem:** Low volume today, but the client is blind to the one limit that applies to its unmigrated routes, so the first warning would be a 420.
- **Recommendation:** Log a warning when `X-Esi-Error-Limit-Remain` < 20. On 420, use `X-Esi-Error-Limit-Reset` for the wait. Parse `Retry-After` with a try/except that falls back to 5.
- **Effort:** S
- **Tradeoffs / dependencies:** none

### OPS-7: ESI User-Agent has no contact info where the app actually runs
- **Severity:** P3
- **Status:** verified (config); inferred (CCP's ESI guidance asks for contact details in the User-Agent; I did not fetch developers.eveonline.com)
- **Evidence:** `settings/base.py:146-147` adds the email only if `ESI_CONTACT_EMAIL` is set. `grep -c "^ESI_CONTACT_EMAIL=.\+" backend/.env` returns 0, and `deploy/.env.example:13` leaves it blank. SSO calls (`sso.py:39,75,107`) send httpx's default UA.
- **Problem:** The dev stack is the live install (cron every 10 min against the owner's Director tokens). If CCP needs to contact the operator about traffic, the requests only say `eveindy/dev`.
- **Recommendation:** Set `ESI_CONTACT_EMAIL` (or a character name) in `backend/.env`. Pass the same `User-Agent` to the SSO httpx calls.
- **Effort:** S
- **Tradeoffs / dependencies:** none

### OPS-8: The real data lives in the dev volume, and its tokens are keyed to the dev SECRET_KEY
- **Severity:** P3
- **Status:** verified
- **Evidence:**
  - The owner's real account, plans and tokens are in the dev Postgres volume `pgdata_dev` (`docker-compose.dev.yml:145-146,174-175`; CLAUDE.md "Dev data").
  - `TOKEN_ENCRYPTION_KEY` is unset in `backend/.env` (grep count 0), so tokens are encrypted with a key derived from `SECRET_KEY` (`settings/base.py:148-150`).
- **Problem:** This adds to the known "no backup job" item. The backup that matters is the dev one, not the prod stack's. A `pg_dump` alone restores tokens that cannot be decrypted unless `backend/.env` is kept with it. `docker compose -f deploy/docker-compose.dev.yml down -v` deletes everything.
- **Recommendation:** When a backup job is added, point it at the dev DB and copy `backend/.env` (or set an explicit `TOKEN_ENCRYPTION_KEY` and record where it is kept). Until then, document the `down -v` hazard in the README dev setup.
- **Effort:** S
- **Tradeoffs / dependencies:** builds on the known backup item

## Keep
- `X-Compatibility-Date: 2026-08-18` is the newest date (`/meta/compatibility-dates` returns `["2026-08-18", ...]`). Each used route's 200 schema is identical under 2020-01-01 and 2026-08-18, and the response fields used in `sync.py` match the spec (char jobs `station_id`, corp jobs `location_id`, both handled at `sync.py:204`).
- The crontab intervals match the spec's `x-cache-age`: jobs 300 s, assets, blueprints, roles, divisions, prices and systems 3600 s, skills 60 s (`deploy/crontab:2-6`).
- `market.py` cites the `market-order` 12,000/15m group, which the spec confirms. Requests made at 8 in parallel and cached for 300 s line up with ESI's 300 s cache. A failed fetch falls back to the CCP average with a count rather than failing the plan (`market.py:55-75`).
- The ETag cache key includes the character id (`client.py:34-40`), so authenticated bodies never cross characters.
- The 5xx breaker (3 within 120 s opens it for 300 s) raises `EsiUnavailable`, an `EsiError`, so each feed records it instead of crashing (`client.py:101-107`, `sync.py:90`).
- Tokens refresh on demand under a row lock (`tokens.py:27-29`). A rejected token is flagged, and `corp_source` falls through to the next linked Director (`sync.py:322-334`).
- Jobs are upserted and never deleted (`sync.py:228-230`). `match_after_sync` swallows its own errors, and `JobLink` has a unique `(user, job)` constraint, so overlapping job syncs cannot double-link.
- Prod Redis uses `volatile-lru` without persistence. Only TTL'd cache keys are evicted, and Celery queue keys never are (`docker-compose.yml:94-96`).
- Under ASGI, Django runs each request's sync view on its own thread via `ThreadSensitiveContext` (`django/core/handlers/asgi.py:165`), so a slow Jita fetch or a `Retry-After` sleep does not block other requests in the uvicorn worker.
- Each `sync_esi` mode takes its own advisory lock, so a slow cron line skips rather than stacking (`sync_esi.py:12-44`, `core/locks.py`).

## Concerns to investigate
- Whether `/markets/10000002/orders?type_id=` returns a 4xx (counted against the error limit) for non-market types that can end up on a shopping list. Calling it once with a known non-market type id would confirm or rule this out.
- In dev, `watchfiles` restarts the worker on any backend `.py` change and kills an in-flight sync. With `acks_late`, the task is redelivered only after the Redis visibility timeout (1 h by default), and the dedup key blocks "refresh now" for 10 min. Editing a file during a sync and then watching the worker log would confirm it.
- If a new migration exists, the dev scheduler and worker run mounted code against an unmigrated DB until `migrate` is run by hand. Cron runs fail until then, and OPS-3 means nothing in the UI shows it.
- I assumed supercronic's default is to skip an overlapping run of the same line. The advisory lock covers this case either way, so it matters only for log noise.
- I assumed `httpx.Client` is safe to share across the 8 market threads. The httpcore connection pool is documented as thread-safe, but I did not read the source.

## Out of lane
- `docs/redesign.md:248` says cron runs "token refresh", but there is no such cron line because tokens refresh on demand (`tokens.py:1-6`). This is doc drift.
- `entrypoint.sh:34` runs uvicorn with `--forwarded-allow-ips="*"`, which trusts any proxy's forwarded headers (security lane).
