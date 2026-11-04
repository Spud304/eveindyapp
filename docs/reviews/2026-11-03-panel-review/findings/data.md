# Data / Database Engineer findings

## Summary
The data layer is small, consistent and mostly well-constrained: snapshot replaces are atomic, the SDE import is one transaction, jobs upsert on their natural key, and migrations match the models. The main gap is that the per-owner asset/blueprint snapshots have no protection against two writers for the same owner (on-demand Celery sync vs. the hourly cron), and no uniqueness on `(owner, item_id)` to catch it, so a race silently doubles stock or blueprints until the next sync. Secondary issues are cross-owner duplicates when an item moves between personal and corp hangars, plan views that never show how old the snapshots behind them are, and a SDE cache key that does not change on a same-build re-import. Volume is tiny (largest ESI table: 3,454 asset rows; 48 jobs), so growth and indexing are non-issues at this stage.

## What I checked
- Models and all migrations: `backend/apps/{accounts,esidata,planning,sde}/models.py`, `migrations/`; `uv run python manage.py makemigrations --check --dry-run` → "No changes detected"; `showmigrations` → nothing unapplied.
- ESI sync writers and locking: `apps/esidata/sync.py`, `apps/esidata/tasks.py`, `apps/esidata/management/commands/sync_esi.py`, `apps/core/locks.py`, `deploy/crontab`, `deploy/docker-compose.dev.yml`.
- ETag cache and paging: `apps/esi/client.py`; market cache `apps/esidata/market.py`; share payload cache `apps/planning/sharing.py:111-117`.
- SDE: `apps/sde/loader.py`, `derive.py` (`derive_all`, `_derive_blueprints`), `gamedata.py` cache keys, `SdeBuild.latest()`.
- Planning reads: `apps/planning/{inputs,reservation,tracker}.py`, `plans_api.py` (line writes, activate, link/unlink, picked BPC checks), `apps/esidata/{access,jobs}.py`.
- Lifecycle: `apps/accounts/services.py` (transfer detach, unlink), FK `on_delete` choices.
- Read-only SQL on dev Postgres (5434, `SET TRANSACTION READ ONLY`): table sizes; job status/owner breakdown; FeedStatus rows; duplicate `item_id` checks on `esidata_asset` / `esidata_blueprint` (none today); character vs corp job overlap.

## Findings

### DATA-1: Concurrent syncs of the same owner can duplicate asset and blueprint rows
- **Severity:** P2
- **Status:** verified (code path); Postgres behaviour from the docs, not reproduced (no writes allowed)
- **Evidence:**
  - `apps/esidata/sync.py:135-156` and `:170-191`: `transaction.atomic(); DELETE ... WHERE owner; bulk_create(...)`, no lock.
  - `apps/esidata/models.py:221-246` (`Asset`) and `:249-272` (`BlueprintItem`): no unique constraint on `(owner_kind, owner_id, item_id)`.
  - Writers that can overlap: Celery `sync_account_task` (`apps/esidata/tasks.py:298-315`) has no DB lock, only a per-account cache dedup; worker runs `--concurrency=2` (`deploy/docker-compose.dev.yml:63`). Cron `sync_esi --all` at `:07` (`deploy/crontab`) takes an advisory lock keyed by run mode only (`sync_esi.py:12-15, 40`), which does not exclude Celery. Corp feeds are written once per account that can read the corp (`sync.py:461-462`), so two accounts in one corp also write the same owner.
  - Postgres READ COMMITTED (docs §13.2.1): a `DELETE` only finds rows committed as of the command's start. If T1 and T2 both run delete+insert for the same owner with overlapping transactions, T2's delete cannot see T1's new rows, and both inserts survive.
- **Problem:** When "Refresh now" (or the first sync after linking a character, `accounts/views.py:45-49`) overlaps the hourly full sync, the owner's assets and blueprints are stored twice. `inputs.asset_buckets` sums quantities (`inputs.py:141-145`) and `owned_blueprints` lists each row (`inputs.py:74-91`), so the plan sees double stock and duplicate BPOs/BPCs. The shopping list understates purchases and the schedule plans parallel jobs on blueprints that do not exist, until the next sync of that owner (up to an hour). Nothing flags it. The window is narrow (the delete+insert transaction), which keeps this at P2 for a single user.
- **Recommendation:** At the start of each replace transaction in `_write_assets`, `_write_blueprints` (and `skills()` / divisions, which use the same pattern), take `SELECT pg_advisory_xact_lock(<hash of table, owner_kind, owner_id>)`. That serializes writers per owner, and the second writer then deletes the first one's rows. Add `UniqueConstraint(fields=["owner_kind", "owner_id", "item_id"])` to `Asset` and `BlueprintItem` as a backstop. Without the lock, the constraint alone turns the race into an `IntegrityError` that `_record` does not catch (`sync.py:88-92`).
- **Effort:** S
- **Tradeoffs / dependencies:** Holding the lock only within the short write transaction does not slow the ESI fetches. The constraint needs a migration. Dev data has no duplicates today (checked), so the migration will apply cleanly.

### DATA-2: An item that moves between a character and its corp can be counted in both snapshots
- **Severity:** P2
- **Status:** inferred
- **Evidence:** Snapshots are per owner and replaced independently (`sync.py:133-192`). Character feeds run before corp feeds (`sync.py:459-462`), and each ESI route has its own cache of up to 1 h for assets and blueprints (`deploy/crontab` comment, "live headers, 2026-11-03"). `owner_q` unions character and corp rows with no de-duplication by `item_id` (`access.py:112-123`; consumers `inputs.py:74, 138`). `incoming_copies` looks up originals by `item_id` across all owners (`inputs.py:105-108`).
- **Problem:** The owner works mostly out of corp hangars and moves blueprints and materials between personal and corp hangars. If an item keeps its `item_id` when it changes owner (inferred, not confirmed for EVE), then during the cache window after a move, one snapshot is stale and the other is fresh. The same BPO/BPC or stack appears under both owners, and the engine counts two. The reverse move leaves it in neither, so the plan buys or copies what is already owned. Stacks split on a partial move get new ids, so they can only be undercounted, not doubled.
- **Recommendation:** After building the readable rows in `owned_blueprints` and `asset_buckets`, keep one row per `item_id`: the one whose owner's `FeedStatus.fetched_at` for that feed is newest. Add a plan warning when a duplicate was dropped.
- **Effort:** S
- **Tradeoffs / dependencies:** To confirm, move a BPC from a personal hangar to a corp hangar, run `sync_esi --account <id>`, then run `select item_id from esidata_blueprint group by item_id having count(*) > 1`. If item ids change on owner change, drop this finding.

### DATA-3: Plan results do not show how old the snapshots behind them are, or that a feed is failing
- **Severity:** P2
- **Status:** verified
- **Evidence:** `FeedStatus` holds `ok` and `fetched_at` per owner and feed (`esidata/models.py:148-172`). Plan inputs never read it: `grep -rn "fetched_at\|FeedStatus" apps/planning` only matches `ore_api.py:158` (market time). In the frontend, sync time appears only in `features/setup/SetupPage.tsx` and `features/dashboard/DashboardPage.tsx`, not under `features/plans`. A character whose token refresh failed stays in `owner_q` (`access.py:119`), so its last snapshot keeps feeding plans indefinitely. When a director's token or role is lost, corp data stops refreshing but is still read by owners who keep access.
- **Problem:** The owner buys materials and installs jobs from the plan page. If the corp assets feed has been failing for a day, the shopping list is computed from day-old stock, and nothing on the plan page says so. This works against the project's goal that every derived value carries a reason.
- **Recommendation:** In `reservation.load`, collect `min(fetched_at)` and any `ok=False` rows from `FeedStatus` for the owners and feeds that `owner_q` reads (assets, blueprints, jobs). Return them with the plan result, either as a "data as of" field plus a warning per failed feed, or as an engine `PlanWarning`, and show it on the plan page.
- **Effort:** S
- **Tradeoffs / dependencies:** UX owns the presentation. This finding covers only the data the plan result needs to carry.

### DATA-4: JobLinks keep counting jobs the account can no longer read, with a frozen status
- **Severity:** P3
- **Status:** verified
- **Evidence:** `tracker.progress_inputs` reads `IndustryJob.objects.filter(links__plan=p)` with no `owner_q` (`tracker.py:316`), while matching and candidates do apply it (`tracker.py:294`, `plans_api.py` candidates). Job rows are updated only by syncs of their owner (`sync.py:195-231`). Unlinking a character drops it from `owner_q` (`services.py:225-233`, `access.py:119`). Losing Director or Factory_Manager drops the corp from `owner_q` (`access.py:100-109`).
- **Problem:** After a character is unlinked, or corp job access is lost, a linked job that was `active` stays `active` in the database forever. `effective_status` then calls it "ready" (`jobs.py:336-341`), and its output keeps counting as started units (`tracker.py:324-325`). The plan under-demands that item for good. The job stays visible in the plan's job list, so the user can unlink it by hand.
- **Recommendation:** In `progress_inputs`, either filter with `owner_q(p.user, Feed.JOBS)`, or keep the job and add a plan warning when a linked job's owner feed has not synced it since `last_seen_at` older than the owner's last successful jobs fetch.
- **Effort:** S
- **Tradeoffs / dependencies:** Filtering silently drops progress the user may want kept. The warning is safer.

### DATA-5: SDE caches do not refresh after re-importing the same build
- **Severity:** P3
- **Status:** verified
- **Evidence:** `gamedata._build_key()` returns `SdeBuild.latest().pk` (`gamedata.py:71-73`), and every `lru_cache` is keyed on it (`gamedata.py:101, 215, 229, 240, 304, 342`). `derive_all` uses `SdeBuild.objects.update_or_create(build=build, ...)` (`derive.py:84-94`), so a `--force` re-import of the same build, or a re-import with a changed `SDE_INCLUDED_FILES`, keeps the same pk. A forced downgrade to a build imported earlier also reuses that build's pk.
- **Problem:** Long-lived processes (runserver, gunicorn web, Celery worker) keep serving the old `GameData`, structures and rigs until they restart. This contradicts the docstring "a new import is picked up without a restart" (`gamedata.py:7-8`). It only matters when re-importing to fix a derivation bug, but that is exactly when stale output is misleading.
- **Recommendation:** Key the caches on `(pk, imported_at)`. `_build_key` can return `hash((latest.pk, latest.imported_at))`.
- **Effort:** S
- **Tradeoffs / dependencies:** none

## Keep
- One SDE import is one transaction, raw files plus derivation (`loader.py:45-54`), and the cache key changes only after commit, so readers never see a mix of two builds.
- Snapshot replaces are atomic per owner (`sync.py:135, 170`), so readers mid-replace see the old or the new set, never an empty one. A failed paged fetch raises before the transaction, so the old data and the failure in `FeedStatus` are kept (`sync.py:88-98`).
- Jobs upsert on the ESI job id (`sync.py:227-230`) and are never deleted. Volume is negligible (48 rows; character and corp jobs do not overlap: char feed `rows=0` for a character with 11 corp jobs).
- Partial unique constraints: one active plan per user (`planning/models.py:466-472`), one station per location per user (`:388-395`), and one link per user and job (`JobLink`, `:514-518`).
- `JobLink.plan` null as a tombstone for a manual unlink, so the matcher never re-links it (`tracker.py:292-296`).
- The ETag cache key includes the character id, so authenticated bodies are never shared across characters (`esi/client.py:34-40`).
- Market books are cached per type for 300 s, failures are not cached, and `fetched_at` reports the oldest book (`market.py:55-81`).
- The shared payload cache key includes `updated_at`, and line edits bump it (`plans_api.py:302-304`).
- Owner-hash change deletes the token and detaches the character atomically under `select_for_update` (`services.py:161-191`).
- Models and migrations are in sync (`makemigrations --check` clean).

## Concerns to investigate
- Paged corp routes mix 304 (cached) pages and 200 (fresh) pages per page (`esi/client.py:93, 133-151`). If ESI's cache expires part way through a multi-page fetch, items can shift between pages, giving duplicate or missing rows. To confirm: log `Last-Modified`/`Expires` per page and check that they match. DATA-1's unique constraint would turn the duplicate case into an error.
- Picked-BPC exclusivity across plans is checked only in application code (`plans_api.py:186-195`). Two concurrent `PUT /lines` calls could both pick one BPC, and `picked_blueprints` then gives it to whichever plan comes first (`reservation.py:101-110`). Single user, so low; a DB-side check would need a join table instead of JSON.
- `reservation.load` runs about 8 separate autocommit queries (`reservation.py:84-98`), so a sync committing between them can yield jobs and blueprints from different moments. Not observed; would show as a blueprint marked busy by a job that is already delivered.

## Out of lane
- ESI page-consistency checks (`X-Pages` with a mixed `Last-Modified`) belong to the ESI integration reviewer.
- The corp feed is fetched once per account in `sync_esi --all` (`sync.py:461`). That spends ESI budget for multiple accounts in one corp, an ops concern.
