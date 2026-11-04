# QA / Test Engineer findings

## Summary
The backend suite is fast (327 tests, 14.5 s), runs on Postgres in CI and locally, mocks ESI at the transport layer, and pins many formula details to the decompiled client. Its main gap is that the numbers the user buys from and installs from are never checked against real game data: engine tests run on hand-built `GameData`, the SDE→engine path is exercised only with a one-blueprint tiny SDE, and the design doc says output was "not yet compared with in-game job windows". The second-tier gaps are no result-level invariants, an untested aliasing branch in link sharing, and untested ESI rate-limit/breaker and failed-resync paths.

## What I checked
- Read: `backend/tests/**` (all conftests, `tests/engine/data.py`, test names in every file), `backend/playwright_tests/**`, `.github/workflows/test.yml`, `backend/pyproject.toml` pytest config, `config/settings/test.py`, `apps/esi/client.py`, `apps/esidata/sync.py` (write paths), `apps/esidata/market.py`, `apps/planning/sharing.py`, `apps/accounts/management/commands/playwright_*.py`, `apps/accounts/views.py` (dev-login), `deploy/crontab`, `docs/redesign.md` (verification notes).
- Ran `uv run pytest -q` in `backend/`: `327 passed in 14.53s`.
- Ran every test file in isolation (loop over `tests/**/test_*.py`): all pass; one transient failure noted under Concerns.
- Ran an engine mass-balance probe on 4 plans built with `tests/engine/data.py` (stdin script, no files written): all balanced (QA-2).
- Read-only SQL on the dev DB: SDE present (`sde_build` 1 row, 53,306 types, 5,100 blueprints); reaction formula `max_production_limit` distribution.
- Exported the OpenAPI schema offline with `manage.py export_openapi_schema --api config.api.api`, generated types with `npx openapi-typescript` into a scratch dir (since deleted), diffed against `frontend/src/lib/api/schema.d.ts`: identical today (QA-5).
- Did not run Playwright (per brief); reviewed it statically.

## Findings

### QA-1: No test pins engine output to real SDE data or in-game numbers
- **Severity:** P1
- **Status:** verified
- **Evidence:**
  - `backend/tests/engine/data.py:1-4`: "Item and blueprint IDs are made up"; engine tests build `GameData` directly (`game()`, line 136) and never go through `apps/sde/gamedata.py`.
  - The only SDE→`gamedata`→engine path in tests uses `tiny_records()` (`backend/tests/sde/conftest.py:39-113`): one blueprint (Rifter, one material), one structure modifier. Invention, reactions, rigs with security multipliers, decryptors and skill time bonuses go through `gamedata.py` only in `tests/sde/test_gamedata.py`, with hand-written records shaped like the SDE as the author understood it; their output never feeds an engine test.
  - Fake data has already drifted from real values: `data.py:107-108` gives reaction formulas `max_production_limit` 1; the dev SDE has `reaction|1000|107`, `reaction|100|12`, `reaction|1000000|1` (SQL on `sde_blueprint` join `sde_blueprint_activity`).
  - `docs/redesign.md:155`: "Not yet compared with in-game job windows."
  - Real SDE is available locally (53,306 types, 5,100 blueprints) but nothing reads it in tests; CI's Postgres is empty and `test.yml` excludes browser tests; Playwright only checks names for Rifter/Tritanium/Azbel (`playwright_tests/conftest.py:107-111`).
  - The SDE changes under the user without a test run: `deploy/crontab` `0 4 * * * import_sde --check-latest`, and `SDE_AUTO_DOWNLOAD` defaults to `True` (`config/settings/base.py:158`).
- **Problem:** Materials, runs, times and fees are what the user buys and installs from. Every current assertion compares the engine against the author's own reading of the client and the SDE. A wrong field mapping in `gamedata.py` (e.g. a rig attribute, a modifier source shape, a skill bonus), or a format change in a new SDE build, produces wrong plans with every test green.
- **Recommendation:** Add a golden test module fed by real SDE records, not hand-written ones:
  1. A small script that copies the raw records for 3–5 chosen jobs from `sde_raw_record` (types, groups, blueprints, typeDogma, industryModifierSources, industryTargetFilters, the system) into a committed JSONL fixture.
  2. A test that imports the fixture through the existing `make_sde_zip` → `import_source` path, builds inputs through `gamedata`, runs the engine, and asserts exact materials, job time and fee against numbers read from the in-game industry window for the same setup (e.g. one Maelstrom at the user's rigged Azbel, one composite reaction at a rigged Tatara/Athanor, one T2 invention with a decryptor, one copy job).
  This runs in CI. Re-running the extraction script after an SDE import and diffing the fixture shows format drift.
- **Effort:** M
- **Tradeoffs / dependencies:** Needs the user to read numbers off in-game windows once (skills, structure, rigs, system index recorded with them). Cost index and adjusted price must be fixed in the test, so the fee check is against the formula with in-game inputs, not live values. Overlaps the game-mechanics reviewer's "verify against client" lane; this finding is about having a regression test, not about any specific formula.

### QA-2: No result-level invariants; every engine test checks only targeted values
- **Severity:** P2
- **Status:** verified
- **Evidence:** `tests/engine/test_planner.py` (1,051 lines, ~70 tests) asserts specific fields via `item()`, `bp()`, `jobs_for()` helpers (lines 68-80); `grep -n "invariant\|hypothesis\|def check" tests/engine/*.py` → nothing. `ItemPlan` (`engine/types.py:391-407`) carries enough to check per-item balance. Probe run on four plans (multi-level hull with assets and a rig, two-step reaction, T2 invention with decryptor, BPCs + BPO + `started`): for every item, `line_quantity + input_quantity == on_hand_used + started + produced - surplus + to_buy`, `input_quantity == Σ job materials of that type`, and `produced == Σ manufacturing/reaction job output` all held ("hull 5 jobs; ok", "reaction 2 jobs; ok", "t2 7 jobs; ok", "bpcs+started 5 jobs; ok").
- **Problem:** `planner.py` is 1,646 lines with a greedy split search that re-plans in full. A regression that, for example, double-counts an input in one branch, drops a job after a split, or schedules a job before its dependency only fails a test if that exact case has a targeted assertion. Item/job/shopping-list consistency is the "views can't disagree" goal stated in the brief.
- **Recommendation:** Add `assert_consistent(result)` in `tests/engine/` checking: the per-item balance above; shopping list `quantity == to_buy` per type; each job starts after every `depends_on` job ends; no two jobs overlap on the same character's slot beyond its slot count; manufacturing/reaction job durations ≤ 30 days where the planner splits; `costs.total` equals the sum of its parts. Call it from the existing `plan()` calls (wrap `engine.plan` in a fixture or helper) so all ~70 planner tests check it, and from QA-1's golden tests.
- **Effort:** S
- **Tradeoffs / dependencies:** Some checks (slot overlap, 30-day cap) need the exact rules from `engine/schedule.py`; start with the balance and dependency checks, which the probe shows hold today.

### QA-3: Link-share redaction is untested for progress jobs (other installers, facilities)
- **Severity:** P2
- **Status:** verified
- **Evidence:** `apps/planning/sharing.py:186-198` aliases installers not in the owner's characters to "Corp member N" and facilities to "Structure N"; `ID_KEYS` (`sharing.py:35`) replaces `facility_id` with 0. `grep -n "job(\|IndustryJob\|JobLink\|Corp member\|Structure " tests/planning/test_sharing.py playwright_tests/test_sharing.py` → no matches. The link test (`tests/planning/test_sharing.py:55-70`) checks only the station name "Secret Keep" and `MAIN`, with no linked jobs, so `progress.jobs` is empty and lines 186-198 never run. It does not assert that `AZBEL_ID` (the real structure id) is absent.
- **Problem:** Hiding the owner's structures and characters from link viewers is the one promise the link feature makes. The branch that handles corpmates' jobs and unknown facilities (`facility_name` falls back to `f"Structure {j.facility_id}"`, `overview_api.py:227`, which contains the real structure id) can regress without any test failing.
- **Recommendation:** Extend `test_link_view_needs_no_login_and_hides_names`: before sharing, create a corp job by `OTHER_CHAR` at `AZBEL_ID` and one at an unknown facility with `job(...)`, link both to the plan, then assert on the JSON text: no `"Mate"`, `str(OTHER_CHAR)`, `str(AZBEL_ID)`, `str(NO_ACCESS)`, `"Secret Keep"`; installer names match `Corp member \d+`; facility names match `Structure \d+`.
- **Effort:** S
- **Tradeoffs / dependencies:** Lower urgency while the app is localhost-only (no outside viewer can reach a link). The security reviewer owns whether the aliasing is complete; this finding is that no test protects it.

### QA-4: ESI failure paths that change what the user sees are untested (rate limit, breaker, failed resync)
- **Severity:** P2
- **Status:** verified
- **Evidence:**
  - `apps/esi/client.py:95-107`: 420/429 sleep-and-retry once, then `EsiRateLimited`; three 5xx within 120 s open a breaker (`BREAKER_KEY`) that makes every later ESI call raise `EsiUnavailable` for `BREAKER_SECONDS`, including Jita pricing (`market.py` fans out 8 threads, `WORKERS = 8`). `grep -rn "429\|420\|breaker\|RateLimited" tests` → no ESI-client matches (only a 500 in `test_market.py:27` and 503 in SDE download tests).
  - `tests/esidata/test_sync.py:283-291` (`test_failed_feed_is_recorded_and_others_still_run`) runs on a first sync, so it cannot show that a failed resync keeps the previous assets. The code does fetch before delete (`sync.py:133-136`, `paged()` raises on any page failure, `client.py:133-151`), but no test pins that order, and no test fails page 2 of a paged corp feed.
- **Problem:** If a refactor moves the delete before the fetch, or makes `paged()` return what it has on a page failure, a single ESI hiccup wipes corp assets and blueprints from every plan; reservation and the shopping list then silently change until the next good sync. The breaker path decides whether a short ESI outage degrades to "average prices" or blocks syncs for its whole window; neither is asserted.
- **Recommendation:** Add to `tests/esi/test_client.py`: 429 with `Retry-After: 1` then 200 → body returned (monkeypatch `time.sleep`); 429 twice → `EsiRateLimited`; three 503s → breaker set, fourth call raises without a request, a 200 after expiry clears `esi:5xx`. Add to `tests/esidata/test_sync.py`: sync once, then resync with the assets route 500 (and a variant where corp assets page 2 of 2 fails) → previous `Asset` rows unchanged and the feed status records the error.
- **Effort:** S
- **Tradeoffs / dependencies:** none

### QA-5: CI does not check that generated API types match the backend schema
- **Severity:** P3
- **Status:** verified
- **Evidence:** `.github/workflows/test.yml` frontend job runs `tsc -b`, `eslint`, `vite build` against the committed `frontend/src/lib/api/schema.d.ts`; `gen:api` (`frontend/package.json`) needs a running Django. `manage.py export_openapi_schema --api config.api.api` works offline (ran it with test settings); generating types from that output and diffing gave no difference today.
- **Problem:** A backend schema change committed without `npm run gen:api` leaves the frontend type-checking against the old shape; CI stays green and the mismatch shows only at runtime (or in Playwright, which CI does not run).
- **Recommendation:** In the backend CI job (it has Postgres and uv), export the schema to a file and upload it as an artifact, or simpler, add a frontend step after `npm ci` that installs uv, runs the export, runs `npx openapi-typescript <file> -o /tmp/schema.d.ts` and `diff` against the committed file.
- **Effort:** S
- **Tradeoffs / dependencies:** Diff can be noisy if openapi-typescript's version changes; it is pinned through `package-lock.json`.

### QA-6: Playwright login ids can leave the reserved range without failing
- **Severity:** P3
- **Status:** verified
- **Evidence:** `playwright_tests/conftest.py:122-126` increments `_next_id` from 900000001 with no upper bound; `playwright_cleanup` deletes only `900_000_001..900_000_099` (`apps/accounts/management/commands/playwright_cleanup.py:9`); `dev_login_view` accepts any id (`apps/accounts/views.py:138-161`). The suite currently makes about 28 `login(` calls (`grep -c`), so it is under the limit. `make_job`/`make_bpc` are protected because `playwright_job` refuses ids outside the range (`playwright_job.py:28`).
- **Problem:** Once the suite passes 98 logins in one run, accounts 900000100+ are created in the dev DB, which holds the real account, and are never cleaned; later runs then see leftover data in those accounts.
- **Recommendation:** In `_open`, `assert cid <= 900_000_099, "reserved test ids exhausted"`.
- **Effort:** S
- **Tradeoffs / dependencies:** none

## Keep
- Postgres for tests and CI, with the reason recorded (`config/settings/test.py:11-12`; `test.yml` postgres service): JSONB, upserts and advisory locks are tested for real.
- ESI mocked at the transport layer with `httpx.MockTransport` (`tests/planning/conftest.py:100-109`, `tests/esi/test_client.py`), so the real client code (ETags, paging, errors) runs in tests.
- Autouse `no_market` fixture (`tests/planning/conftest.py:70-76`) makes accidental live Jita calls from tests impossible.
- Formula tests named and written against the client (`tests/engine/test_formulas.py`: `test_job_fee_parts_as_in_the_client`, `test_each_fee_part_rounds_half_up`, `test_job_materials_ignores_float_noise`).
- Planning tests import their tiny SDE through the real importer (`sde` fixture: `make_sde_zip` → `import_source`, then clear `gamedata` caches), so the import→gamedata→engine→API path runs end to end, if narrowly.
- Every backend test file passes in isolation (per-file loop), so there is no hidden order dependency today.
- Playwright: web-first `expect` throughout, no `wait_for_timeout`/sleeps (grep), a session check that servers, dev-login and SDE are present before any spec runs (`conftest.py:90-113`), reserved-id cleanup with its own unit test (`tests/accounts/test_playwright_cleanup.py`), and value assertions that tolerate per-job rounding (`test_plans.py:33-38`) instead of hard-coding live data.

## Concerns to investigate
- One run of `tests/planning/test_tracker.py` alone gave `15 errors in 1.70s`; six reruns passed. Likely another pytest process (another reviewer) creating/dropping the shared `test_eveindy` database at the same time. Confirm by running two `uv run pytest -q` at once; if so, concurrent runs (two terminals, a worktree, an agent) collide, and `TEST_DATABASE_URL` or a per-run test DB name would fix it.
- `paged()` returns the cached `X-Pages` when page 1 answers 304 (`client.py:93-94`, `133-151`); if page 1 is unchanged but the page count grew, later pages are never fetched. Confirm whether ESI's 304 carries `X-Pages` and whether corp asset page 1 can stay unchanged while pages are added. (ESI-integration reviewer's area for the fix; a test belongs in QA-4's set.)
- The Playwright suite prices through live Jita via the dev servers (e.g. ore "Refresh prices", `playwright_tests/test_plans.py:267-271`). Assertions avoid prices, but an ESI outage may change the flow. Confirm by running the ore spec with outbound network blocked.
- `bpc()` in `tests/engine/data.py:231-232` derives `item_id` as `type_id * 10 + runs`, so two BPCs of the same blueprint and runs get the same item id unless `item_id` is passed; a test could pass or fail for that reason rather than the behaviour under test. Check tests that create several BPCs of one type.

## Out of lane
- `dev_login_view` has no reserved-range guard; the CLAUDE.md warning about real ids is enforced only by convention (`apps/accounts/views.py:138-161`). Security.
- Link-share scrubbing replaces character names as substrings in every string (`sharing.py:208-216`); a short character name could rewrite item names or reasons. Security / UX.
- Frontend recomputes a few totals from the result (`tabs.tsx:29`, `tabs.tsx:360`, `ore.tsx:52`); `vitest` is configured (`package.json` `"test": "vitest run"`) but has no test files. Architecture (single-result principle).
