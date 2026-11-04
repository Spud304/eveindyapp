# Security Engineer findings

## Summary
The SSO flow, API authorization and the sharing feature are sound: PKCE + state, strict JWT validation, CSRF enforced on every cookie-authenticated unsafe call, every owner endpoint scoped to the requesting account, and link payloads aliased and tested. The weak spots are all on the dev machine, which is the one place the owner's real Director tokens live: the token encryption key is derived from a SECRET_KEY default that is published in the repo, dev Postgres and Redis listen on all interfaces with known/no credentials (Redis feeds a pickle cache), and `/auth/dev-login` is a GET that any page can trigger against a real character id. None is P0/P1 at "localhost only"; each fix is small. The prod stack is in good shape apart from exposing `/admin`.

## What I checked
- `backend/apps/accounts/` (sso.py, views.py, services.py, crypto.py, tokens.py, api.py, admin.py, urls.py, playwright_cleanup.py)
- `backend/config/settings/{base,dev,prod,test}.py`, `config/urls.py`, `config/api.py`, `manage.py`, `config/celery.py`, `config/asgi.py` (default settings modules)
- Authorization in `apps/planning/{plans_api,api,ore_api,sharing}.py`, `apps/esidata/{access,api,overview_api,sync}.py`, `apps/sde/api.py`, `apps/core/api.py` (every `@router` and `auth=None`)
- Link payload contents vs `engine/types.py` (PlanResult, PlannedJob, OwnedBlueprint), `describe_jobs`, `_anonymize`, `tests/planning/test_sharing.py`
- `deploy/` (Caddyfile, both compose files, entrypoint.sh, Dockerfiles, `.env.example`), root `.dockerignore`
- Library behavior from installed source: django-ninja 1.7.3 `security/apikey.py:44-54` (CSRF check in `APIKeyCookie`), Django `core/cache/backends/redis.py:12-28` (pickle serializer)
- Commands: `cut -d= -f1 backend/.env` → `EVE_CLIENT_ID, EVE_CLIENT_SECRET, EVE_CALLBACK_URL` (no SECRET_KEY, no TOKEN_ENCRYPTION_KEY); `docker ps` → `eveindy-dev-db-1 0.0.0.0:5434->5432/tcp`, `eveindy-dev-redis-1 0.0.0.0:6381->6379/tcp`; `ss -ltn` → `*:5434`, `*:6381`, `127.0.0.1:8000`, `127.0.0.1:5050`; `wslinfo --networking-mode` → `nat`
- Frontend: no `dangerouslySetInnerHTML`; `X-CSRFToken` sent from `src/lib/api/client.ts:13-14`; Vite bound to `127.0.0.1` (`frontend/vite.config.ts:17`)

## Findings

### SEC-1: Real ESI tokens in the dev DB are encrypted with a key derived from a public default
- **Severity:** P2
- **Status:** verified
- **Evidence:** `backend/config/settings/base.py:13` `SECRET_KEY = env.str("SECRET_KEY", "dev-insecure-secret-key")`; `base.py:150` `TOKEN_ENCRYPTION_KEY` defaults to `""`; `apps/accounts/crypto.py:17-21` derives the Fernet key as `sha256(b"eveindy-esi-token:" + SECRET_KEY)` when the key setting is empty; `backend/.env` sets only `EVE_CLIENT_ID, EVE_CLIENT_SECRET, EVE_CALLBACK_URL`. The dev compose worker/scheduler use the same settings (`deploy/docker-compose.dev.yml:6-8,22`). `prod.py:13-14` guards SECRET_KEY, dev does not.
- **Problem:** The dev DB is where the owner's real Director tokens are (CLAUDE.md "Dev data"). Anyone who gets a copy of that DB (a `pg_dump`, the `pgdata_dev` volume, or a connection per SEC-2) can decrypt every stored access token (valid ~20 min, usable directly against ESI for corp assets/blueprints/jobs) and refresh token with a key computable from the repo. Encryption at rest gives no protection in the only environment that holds real tokens. The refresh tokens additionally need `EVE_CLIENT_SECRET`, which sits in `backend/.env` on the same disk.
- **Recommendation:** Generate a Fernet key into `backend/.env` as `TOKEN_ENCRYPTION_KEY` (and a random `SECRET_KEY`), then re-link the three real characters (or run a one-off re-encrypt with the old derived key). Optionally make `dev.py` log a warning when `TOKEN_ENCRYPTION_KEY` is empty and `EsiToken` rows exist.
- **Effort:** S
- **Tradeoffs / dependencies:** Changing the key makes existing tokens undecryptable (`TokenDecryptError`), so it needs either three re-links or a small re-encrypt script. The worker/scheduler pick up the new `backend/.env` through the mount.

### SEC-2: Dev Postgres and Redis listen on all interfaces; Redis is unauthenticated and backs a pickle cache and the SSO discovery doc
- **Severity:** P2
- **Status:** verified (binding and code paths); inferred (who can reach the ports)
- **Evidence:** `deploy/docker-compose.dev.yml:37-38` `"5434:5432"` with `POSTGRES_PASSWORD: eveindy` (`:42`), `:53-54` `"6381:6379"` with no `requirepass`; `docker ps` shows `0.0.0.0:5434` and `0.0.0.0:6381`. Django's `RedisCache` uses `pickle.loads` on read (`.venv/.../django/core/cache/backends/redis.py:24-28`). The SSO discovery document is cached there (`apps/accounts/sso.py:35-47`) and its `token_endpoint` receives the client id/secret and refresh tokens (`sso.py:104-112`).
- **Problem:** Anything that can reach 6381 can write a cache key and get code execution in runserver or the worker on the next read (both hold SECRET_KEY, the client secret and decrypted tokens), or replace `sso:discovery` so the next refresh sends the client secret and a refresh token to another host. Port 5434 gives full DB read/write with a password in the repo, which combined with SEC-1 yields the tokens. WSL is in NAT mode (verified), so LAN reachability is not the default, but Windows-side processes reach these ports through WSL localhost forwarding (inferred; confirm with `Test-NetConnection localhost -Port 6381` from Windows). The app servers themselves were deliberately bound to loopback (`vite.config.ts:16-17`, README runserver `127.0.0.1:8000`); the services around them were not.
- **Recommendation:** Publish both on loopback: `"127.0.0.1:5434:5432"` and `"127.0.0.1:6381:6379"`.
- **Effort:** S
- **Tradeoffs / dependencies:** None for the documented setup (runserver and tests connect to `localhost`). The prod compose already keeps both unpublished.

### SEC-3: `/auth/dev-login` is a GET that detaches a real character's token and splits its account, from any page
- **Severity:** P2
- **Status:** verified (code path); inferred (browser reachability)
- **Evidence:** `apps/accounts/views.py:137-161` (`@require_http_methods(["GET"])`, no CSRF, any `character_id`, `owner` defaults to `"dev-owner"`); `services.py:44-54` deletes the `EsiToken` and detaches the character when the owner hash differs; `services.py:79-82` renames the existing `char:<id>` account to `char:<id>:was:<pk>` and creates a new one. `dev.py:4` enables it for every dev run (`manage.py:7` defaults to dev settings). Passing `owner=` (empty) makes `identity.owner_hash` empty, so `transferred` is false (`services.py:44-46`) and `ensure_user` returns the existing account: a login as any existing account without the token loss.
- **Problem:** CLAUDE.md warns against pointing dev-login at a real id, but nothing enforces it. While the dev servers run, a page the owner visits can request `http://localhost:5050/auth/dev-login?character_id=<Starch Man's public id>` (an `<img>`, or a clicked link): the main's Director token is deleted, the main leaves account 1, account 1 loses its main, and the next SSO login lands in a new empty account. Recovery is manual DB work. The `owner=` variant lets any local process log in as the owner. Modern Chrome may prompt or block public-to-localhost subresource requests (Local Network Access); a top-level link click and other browsers are not covered by that (inferred).
- **Recommendation:** Limit dev-login to the reserved range in dev: e.g. `DEV_LOGIN_CHARACTER_RANGE = (900000001, 900000099)` in `dev.py`, `None` in `test.py` (unit tests use 90000001/90000002/90000999), and return 403 outside it. Also drop the `owner` query parameter or ignore an empty value.
- **Effort:** S
- **Tradeoffs / dependencies:** Manual dev testing must use reserved ids, which is already the stated rule. Playwright tests already comply (`playwright_tests/conftest.py:5-7`).

### SEC-4: Corp read access survives a rejected/revoked token or a character transfer
- **Severity:** P3
- **Status:** verified (code); inferred (transfer scenario in-game)
- **Evidence:** `apps/esidata/access.py:245-250` grants corp feeds from any `CharacterRoles` row of the account's characters whose stored corp matches the character's corp; it does not look at the token. `sync.py:268-282` only writes roles after a successful call; on `TokenUnavailable` `_record` (`sync.py:90-94`) leaves the old row. Nothing deletes `CharacterRoles` (`grep "CharacterRoles.objects.*delete"` → no hits), including on transfer (`services.py:50` deletes only `EsiToken`).
- **Problem:** A corpmate account whose character had Director/Accountant roles keeps reading the corp's assets, blueprints and jobs (refreshed by the owner's token) after revoking the app or after the roles were removed in-game while its token was broken; affiliation is still refreshed (`sync.py:448-450`), so only leaving the corp ends it. After a character transfer, the new owner's fresh account inherits the previous owner's roles row. Only matters once other accounts use a deployed instance.
- **Recommendation:** In `readable_corp_feeds`, require the character to have an `EsiToken` with `refresh_failed_at IS NULL`; delete the character's `CharacterRoles` alongside its token in `upsert_character` (transfer) and `unlink_character`.
- **Effort:** S
- **Tradeoffs / dependencies:** A temporarily rejected token hides corp data until re-link, which matches what the sync can actually vouch for.

### SEC-5: Production Caddy publishes Django admin
- **Severity:** P3
- **Status:** verified
- **Evidence:** `deploy/Caddyfile:15` `@backend path /api/* /auth/* /callback /admin/* /static/*`; `config/urls.py:8`. SSO accounts are created without a password (`services.py:83`, `create_user` with no password → unusable), so admin is only useful for a `createsuperuser` account; `web` is already on `127.0.0.1:8000` for host-side access (`docker-compose.yml:121-122`).
- **Problem:** If deployed, a password login form for an account that can read every user's data is on the public internet with no rate limit, while the app itself never needs it.
- **Recommendation:** Remove `/admin/*` from the Caddy matcher; use admin through `127.0.0.1:8000` on the host (SSH tunnel when remote).
- **Effort:** S
- **Tradeoffs / dependencies:** Admin is not reachable from a browser elsewhere without a tunnel. `/static/*` still needs proxying for the admin's assets on the host port (it is served by whitenoise from `web` either way).

## Keep
- SSO: PKCE S256 with a 32-byte verifier and a random state stored in the session and popped once (`views.py:67-74,91-93`); JWT pinned to RS256 with audience, issuer, `exp`/`sub`/`iss` required and subject format checked (`sso.py:143-175`).
- Refresh under a row lock, and the refreshed token's character id is checked against the stored one (`tokens.py:27-29,65-67`).
- Owner-hash change drops the token and detaches the character (`services.py:44-54`); linking refuses a character on another account (`services.py:92-93`).
- Open-redirect guard on `next` (`views.py:30-35`); logout is POST-only (`views.py:131`).
- CSRF: `NinjaAPI(auth=django_auth)` runs `check_csrf` on unsafe methods (ninja 1.7.3 `apikey.py:44-54`); the only `auth=None` routes are GETs (`/me`, `/health`, `/shared/{token}`).
- Every owner endpoint resolves the plan/station through `user=` (`plans_api.py:107-108`, `api.py:173,188`, `ore_api.py:63`); job links and BPC picks go through `owner_q` (`plans_api.py:170-171,565`); plan station ids and share corp are validated against the owner (`plans_api.py:273-286`).
- Corp feeds gated by the role ESI would require, and roles from a corp the character left are ignored (`access.py:242-251`).
- Sharing: 24-byte link tokens, renewable; non-viewers get 404 so plan existence does not leak (`plans_api.py:618-625`); link payloads alias stations, characters, installers and facilities and scrub names in text, covered by `test_link_view_needs_no_login_and_hides_names`; candidates, reservations and settings are left out; payload cached 60 s per plan.
- Corp membership re-checked against ESI when older than 24 h (`sharing.py:56-75`).
- Prod: `DEBUG=False`, SECRET_KEY guard, secure cookies, `X_FRAME_OPTIONS=DENY`, dev-login off in base/prod, `.dockerignore` excludes `backend/.env` and `deploy/.env`, `web` published on loopback only, Redis/Postgres unpublished, HSTS in Caddy, admin never shows token fields (`admin.py`).
- Dev: Vite deliberately bound to `127.0.0.1` with a comment explaining dev-login exposure (`vite.config.ts:16-17`); no token logging in the ESI client.

## Concerns to investigate
- Caddy `trusted_proxies static private_ranges` (`Caddyfile:5`): if Docker's userland proxy is used (IPv6 clients, rootless Docker), client IPs appear as the Docker gateway and client-sent `X-Forwarded-*` would be trusted; with `USE_X_FORWARDED_HOST` the impact is limited by `ALLOWED_HOSTS`. Confirm by checking the remote address Caddy logs for an external request.
- `playwright_cleanup` deletes every `User` owning any reserved-range character (`playwright_cleanup.py:17-21`); harmless unless a reserved id is ever linked onto a real account. Confirm no test helper links reserved ids to an existing account.
- Whether a character can be transferred while in a player corp with roles (affects SEC-4's transfer case); confirm against CCP's Character Bazaar/transfer rules.

## Out of lane
- Open signup lets any EVE account queue syncs through the app's ESI client and rate-limit budget (`esidata/api.py:38-41`); ESI integration reviewer.
