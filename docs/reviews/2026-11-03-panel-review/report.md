# Panel review: EVE Indy App — whole project (master @ 497cee2)

Panel: Staff Engineer / Architect, EVE Industry Mechanics SME, Security, QA / Test, Data / Database, ESI Integration & Operations, UX / Frontend. Findings in `findings/`, context brief in `context.md`. Consolidated by a PM step; citations spot-checked by the orchestrator (planner.py:197-211, gamedata.py:150, schedule.py:71-74, sync.py:133-158, the token key derivation, docker-compose.dev.yml ports, base.py:13).

## Bottom line
Nothing is fundamentally wrong with the design. The engine/Django split, computed reservations, engine dataclasses used as API types, and the client-checked formulas should stay as they are. The most serious problem is a correctness bug: the engine plans Tungsten Carbide from an unpublished "Test Reaction Blueprint" (EVE-1, verified in the SDE), so every Amarr T2 plan that builds its own reactions has the wrong inputs and its jobs go untracked. The second problem is the most-reported one: the plan page never says how old or how healthy the ESI data behind the shopping list is. Three lanes found this independently (UX-1, DATA-3, OPS-3), and a token-refresh error can stop a sync without recording the failure (OPS-1). A reproduced sync race can also double the asset and blueprint counts (DATA-1/OPS-2). No test compares engine output with real SDE data or in-game numbers (QA-1); that is why EVE-1 went unnoticed. Most fixes are S. The ones that need an in-game check by the owner are grouped under D1.

## Decisions for the owner

### D1: Will you do one in-game verification session to settle the mechanics questions the code can't answer?
- **Context:** Several items depend on facts only the game can confirm. QA-1 needs in-game job window numbers (materials, time, fee) for a manufacturing, a reaction, an invention and a copy job at your structures; `docs/redesign.md:155` says "Not yet compared with in-game job windows". ARCH-1 needs to know whether corp jobs count against the installer's personal slots and whether a "ready" job holds a slot; no reviewer confirmed either. DATA-2 needs to know whether an item keeps its `item_id` when moved between a personal and a corp hangar. Two items from the EVE reviewer's "Concerns" also need it: whether the rig security multiplier applies to rig cost bonuses, and how attempts compare with the expected value.
- **Options:**
  - A: one session. Read 4 job windows (record skills, rigs, system index), move one BPC to the corp hangar and run `sync_esi --account`, and check the slot count with corp jobs running. It costs your time in game and unblocks QA-1 (golden values), ARCH-1 and DATA-2.
  - B: skip it. QA-1 then pins the engine to its own current output on real SDE records. That still catches SDE drift and mapping bugs like EVE-1, but not formula errors. ARCH-1 ships on the inferred rule, and DATA-2 is dropped or built speculatively.
- **PM recommendation:** A. Correctness of plan output is the top goal in the brief, and these checks are the only way to move the remaining "inferred" mechanics to "verified". Now items N1–N9 don't depend on it.

### D2: How should invention be planned with alts of different skill?
- **Context:** EVE-2 (verified): attempts are computed from the best inventor's chance (`planner.py:942-1000`), but `schedule._place` puts each invention job on whichever eligible character finishes it first, so the datacore and decryptor quantities are optimistic. The EVE "Concerns" section adds that attempts are the expected value `ceil(bpcs/p)`, so about half of all batches need a second round.
- **Options:**
  - A: pin invention jobs to the characters whose chance equals the chance used (S). The quantities become correct, but the schedule is longer when those characters have few science slots.
  - B: compute attempts from the chance of whichever character is scheduled. This needs a second planning pass (M). The schedule stays as short as possible, but the code is more complex.
  - Separately: add an optional confidence margin (for example 90%), or keep the expected value.
- **PM recommendation:** A, with the reason text saying the jobs are pinned. Keep the expected value as the default, and add the margin later as a plan setting if one round with a margin matches how you buy. Whether to add the margin is your call, not an engineering one.

### D3: Should multi-user and deploy hardening be done now, or wait until a deploy is decided?
- **Context:** The brief says localhost-only and lists no deploy. These items only matter with other users or a public host:
  - SEC-4: corp read access survives a revoked token or a character transfer.
  - SEC-5: Caddy publishes `/admin`.
  - QA-3: the link-share redaction branch is untested.
  - SEC out-of-lane: open signup lets any EVE account spend the app's ESI budget.
  - Two unowned notes: uvicorn runs with `--forwarded-allow-ips="*"`, and `edit_plan` doesn't validate `extra_location_ids`/`hangar_flags`.

  Signup is open in code, but the design says "for me and anyone with the same use case".
- **Options:**
  - A: do them now. All are S, but they take effort from correctness work.
  - B: wait. Record them in a "before deploy" checklist in `docs/redesign.md` and do them as a block if you deploy.
  - C: close signup now (an allowlist of account or character ids), which removes most of the multi-user risk, and wait on the rest.
- **PM recommendation:** B, and also remove `/admin/*` from the Caddyfile now (SEC-5, a one-line change). Whether signup should stay open is a product scope question, so I'm not deciding C. If you never intend other accounts to use it, C is cheaper than hardening.

### D4: Re-key the stored ESI tokens, and back up the dev database?
- **Context:** SEC-1, verified by the reviewer: `backend/.env` sets no `SECRET_KEY` or `TOKEN_ENCRYPTION_KEY` (`crypto.py:17-21`), so your real Director tokens are encrypted with a key derived from `dev-insecure-secret-key`, which is in the repo. OPS-8: your real data lives in the dev volume `pgdata_dev`, a `pg_dump` is useless without the key, and `docker compose ... down -v` deletes everything. "No backup job" is already a known open item.
- **Options:**
  - A: generate a `TOKEN_ENCRYPTION_KEY` and a random `SECRET_KEY` into `backend/.env`, re-encrypt the existing tokens with a one-off script (old derived key → new key), and add a dev-DB backup that also copies `backend/.env`. This touches your real token rows.
  - B: the same as A, but re-link the three characters instead of running the script. No script, but three SSO logins.
  - C: accept the risk once SEC-2 (loopback binding) closes the main access path.
- **PM recommendation:** A. Once SEC-2 lands, the remaining exposure is anyone holding a copy of the DB. A backup is exactly such a copy, so the key and the backup belong together. A changes your real data, so it needs your go-ahead.

## Prioritized plan

### Now
| # | Item | Severity | Effort | Sources | Depends on |
|---|------|----------|--------|---------|------------|
| N1 | Choose producers deterministically: published blueprints first, then lowest type id; engine test with an unpublished duplicate | P1 | S | EVE-1 (EVE-5 partly) | — |
| N2 | Add `assert_consistent(result)` invariants to every planner test | P2 | S | QA-2 | — (do before or with N1) |
| N3 | Serialize per-owner snapshot writes with `pg_advisory_xact_lock`; add a unique `(owner_kind, owner_id, item_id)` constraint on `Asset` and `BlueprintItem`; catch `IntegrityError` in `_record` | P1 (raised) | S | DATA-1, OPS-2 | — |
| N4 | Turn non-rejection `SsoError` from refresh into a transient `TokenUnavailable` subclass so the feed failure is recorded | P2 | S | OPS-1 | — |
| N5 | Feed freshness and health: "data as of" and failed feeds in `PlanResultOut` and the plan header; stale-feed lines on the dashboard; refetch plans/library/dashboard when a sync finishes | P1 | M | UX-1, DATA-3, OPS-3 | N4 |
| N6 | Disable copy buttons and dim the main column while the result or ore mix is refetching | P2 | S | UX-2 | — |
| N7 | Compute line edits from a local copy and write the `PUT /lines` response into the cache (same for `PurchasePanel.save`) | P2 | S | UX-3 | — |
| N8 | Publish dev Postgres and Redis on `127.0.0.1` only | P2 | S | SEC-2 | — |
| N9 | Restrict `/auth/dev-login` to 900000001–099 in dev and ignore an empty `owner`; assert the reserved-id bound in Playwright `_open` | P2 | S | SEC-3, QA-6 | — |

### Next
| # | Item | Severity | Effort | Sources | Depends on |
|---|------|----------|--------|---------|------------|
| X1 | Golden tests on real SDE records (committed JSONL fixture through the real importer), asserting in-game numbers | P1 | M | QA-1 | D1 (in-game values); N1 |
| X2 | Busy character slots as an engine input (`busy_slots` from open `IndustryJob` rows) | P1 | M | ARCH-1 | D1 (slot rule); N2 |
| X3 | Restrict invention jobs to the characters whose chance was used | P2 | S | EVE-2 | D2 |
| X4 | Interim repricing fix: drop the stale "no price" warning and Jita-price the buy-option purchase costs | P2 | S | ARCH-3 | — |
| X5 | Warning count badge in the plan header; warnings panel above settings | P2 | S | UX-5 | — |
| X6 | Pool BPC runs across reserving plans; expose `blueprint_item_id` on `PlannedJob` | P2 | M | ARCH-2 | N2 |
| X7 | Keep one row per `item_id` across owners (newest feed wins), with a warning | P2 | S | DATA-2 | D1 (confirm item ids survive a move) |
| X8 | Explicit token key, re-encrypt, dev-DB backup including `backend/.env`; document the `down -v` hazard | P2 | S | SEC-1, OPS-8 | D4 |
| X9 | Tests for ESI 429/breaker and a failed resync keeping previous assets (including a page-2 failure) | P2 | S | QA-4 | N3, N4 |
| X10 | Items tab (decision, Why, surplus, per-plan buy/build flip) and ME/TE/decryptor overrides in the Blueprints tab | P2 | M | UX-4 | — |
| X11 | Treat only `invalid_grant`/`invalid_token` as a rejected token | P3 | S | OPS-4 | N4 |

### Later / optional
| # | Item | Severity | Effort | Sources | Depends on |
|---|------|----------|--------|---------|------------|
| L1 | Full two-pass pricing (Jita prices fed into the plan, decryptor choice included) | P2 | M | ARCH-3 | X4 |
| L2 | Extract `_choose_sources` from `plan_blueprint`, with unit tests | P3 | M | ARCH-5 | N2; do it before the next blueprint-source rule |
| L3 | Delete the unused `/api/plan/preview` path; move progress assembly out of `plans_api`; break the tracker↔reservation cycle | P3 | S | ARCH-4, ARCH-6 | — |
| L4 | Reuse the base result in `/progress`; stop the reserving loop early | P3 | S | ARCH-7 | measure first |
| L5 | Warn on non-standard rig bonus attributes (Thukker, Upwell outpost); mapping later | P3 | S/M | EVE-3 | — |
| L6 | 30-day RUN_LENGTH split for copies | P3 | S | EVE-4 | — |
| L7 | Treat relic-sourced T3 as "not modelled" | P3 | S | EVE-5 | N1 |
| L8 | Reprocessing tax in the ore calculator | P3 | S | EVE-6 | — |
| L9 | Doc fixes: EIV tag [client] (`redesign.md:160,226`), the cron "token refresh" drift (`redesign.md:248`), the stale `inputs.py` docstring | P3 | S | EVE-7, OPS out-of-lane, ARCH-4 | — |
| L10 | Warn on linked jobs whose owner the account can no longer read | P3 | S | DATA-4 | — |
| L11 | Key the SDE caches on `(pk, imported_at)` | P3 | S | DATA-5 | — |
| L12 | Check that all pages of a paged fetch share one `Last-Modified` | P3 | S | OPS-5 | N3 |
| L13 | ESI error-limit headers, 420 wait, `Retry-After` parse | P3 | S | OPS-6 | — |
| L14 | Contact info in the User-Agent, also for SSO calls | P3 | S | OPS-7 | — |
| L15 | Release the `edit` mutation queue once the PATCH returns | P3 | S | UX-6 | N7 |
| L16 | Tab in the URL, loading state, 404-vs-error on the shared view | P3 | S | UX-7 | — |
| L17 | Small UX gaps (ore price source, owner names in feeds, countdown tick, confirm before line removal, Why on Schedule) | P3 | S | UX-8 | — |
| L18 | CI check that `schema.d.ts` matches the exported schema | P3 | S | QA-5 | — |
| L19 | Deploy/multi-user block: SEC-4, QA-3, signup scope, forwarded-allow-ips, `edit_plan` field validation (SEC-5 done now) | P2–P3 | S each | SEC-4, SEC-5, QA-3, SEC/OPS/ARCH out-of-lane | D3 |

**N1 — Producer selection (EVE-1).** `planner.py:197-211` overwrites `producers[product]` for manufacturing (the last blueprint wins) and keeps the first one for reactions. `gamedata.py:150` loads every `Blueprint` with `removed=False` and never checks `published`. Verified in the dev SDE (read-only): 45732 "Test Reaction Blueprint" (published = f, 360 s, 20 units) and 46207 "Tungsten Carbide Reaction Formula" (published = t, 10800 s, 10000 units) both produce type 16672. Which one wins depends on database row order; the reviewer's run of the mapping picked 45732. The effect: wrong materials, missing fuel blocks, "no owned blueprint" for the real formula, and real jobs never matched by the tracker. Fix: carry `published` into `BlueprintData`, prefer published blueprints, break ties by lowest type id, and apply the same rule to `invented_from`. Keep unpublished blueprints only as a fallback.

**N2 — Result invariants (QA-2).** No planner test checks the balance of the whole result. The reviewer's probe shows the balance and job-material sums hold today, so adding them is cheap. They guard N1, X2, X6 and L2. Start with the balance, shopping-list and dependency checks; add slot overlap after X2.

**N3 — Sync write race (DATA-1, OPS-2).** Verified: `_write_assets` (`sync.py:133-158`) does delete then `bulk_create` inside a transaction with no lock. `Asset` and `BlueprintItem` (`models.py:101`, `:129`) have no unique constraint on `item_id`. The Celery path has only a cache dedup per account, and the worker runs `--concurrency=2` (`docker-compose.dev.yml:63`). OPS reproduced it (10 rows for 5 items). Raised to P1: two lanes found it independently, it silently doubles stock that the shopping list subtracts, and the fix is S. Fix: an advisory xact lock per (table, owner) for assets, blueprints, skills and divisions, plus the unique constraint, with `IntegrityError` recorded as a feed failure.

**N4 — SSO errors abort syncs (OPS-1).** `tokens.py:48-59` catches only `SsoTokenRejected`, and `sync.py:90` doesn't catch `SsoError`, so an SSO blip aborts the whole `sync_esi --all` run without updating `FeedStatus`. N5 needs this fix to be accurate. `stations.py:155` has the same gap. Not verified by the PM (P2).

**N5 — Data freshness where the user acts (UX-1, DATA-3, OPS-3).** Verified: `PlanResultOut` (`plans_api.py:359-366`) has no freshness field. `apps/planning` reads `fetched_at` only for the ore market time (`ore_api.py:158`). `useRefreshNow` (`hooks.ts:65-72`) invalidates only sync status, and `refetchOnWindowFocus: false` (`main.tsx:13`). Stale or failed corp asset data means the user buys what is already owned, with no hint on the page they copy from. Fix: one backend staleness function returning `fetched_at`, `ok` and a stale flag per (owner, feed), with thresholds about 3× the crontab interval kept as constants next to `CORP_FEEDS`. Use it in the plan result, the plan header and the dashboard problems. Invalidate `plans`, `library` and `dashboard` when a sync finishes.

**N6 — Copy during recompute (UX-2).** `keepPreviousData` plus an always-enabled "Copy list" means a user who edits and then copies at once copies the list from before the edit. Not verified by the PM (P2).

**N7 — Lost line edits (UX-3).** `LinesPanel` builds each new list from server props, so a second quick edit undoes the first, and both saves show the "Lines saved" toast. Edits that disappear without any error are a data-integrity problem in the user's own input. Not verified by the PM (P2).

**N8 — Dev service binding (SEC-2).** Postgres (password in the repo) and unauthenticated Redis (a pickle cache, and the cached SSO discovery doc) are published on `0.0.0.0`. This is a two-line change and closes the main path to the real tokens. Not verified by the PM (P2).

**N9 — Dev-login guard (SEC-3, QA-6).** The CLAUDE.md rule has no code enforcing it, and a GET from any page can detach the main's Director token. Restrict dev-login to the reserved range in `dev.py` (`None` in `test.py`), and add the matching assert in Playwright `_open`. Not verified by the PM (P2).

**X1 — Golden SDE tests (QA-1).** Verified: `tests/engine/data.py:1-4` uses made-up ids, `redesign.md:155` says "Not yet compared with in-game job windows", `SDE_AUTO_DOWNLOAD` defaults to True (`base.py:158`), and `import_sde --check-latest` runs daily. EVE-1 is the kind of bug this would have caught. The fixture part (real records for the owner's batch items, plus a Tungsten Carbide reaction) can start now and pin the current output. The in-game values need D1.

**X2 — Busy slots (ARCH-1).** Verified: `schedule.py:71-74` seeds all slots as free at t=0, and `Character` (`types.py:268-275`) and `inputs.characters` carry no occupancy. Start times, the split search and `seconds_saved` are optimistic for any plan under way. It is in Next because it is M and the slot rule is unconfirmed (D1).

**X3 (EVE-2):** see D2.

**X4 (ARCH-3 interim):** removes the visible contradictions. The decryptor choice stays on average prices until L1; record that in `redesign.md:388`.

**X5 (UX-5):** warnings that change what gets bought sit below about 10 settings selects.

**X6 (ARCH-2):** two reserving plans can count the same BPC runs. The item id also helps with the known "picked BPC disappears" item.

**X7 (DATA-2):** inferred by the reviewer; do it only if D1 confirms item ids survive a move between owners.

**X8:** see D4.

**X9 (QA-4):** pins the fetch-before-delete order and breaker behaviour that N3 and N4 rely on.

**X10 (UX-4):** the API accepts per-plan blacklist flips and ME/TE/decryptor choices that no UI sends; it delivers `redesign.md:57,317`.

**X11 (OPS-4):** a bad client secret currently marks every token as permanently rejected.

## Conflicts resolved
- **Staleness location (UX-1 header vs OPS-3 dashboard vs DATA-3 warning).** All three protect the same goal. Resolution: one backend function feeds both views, so they can't disagree, and thresholds come from the crontab (OPS-3). Nothing is lost.
- **Unique constraint optional (OPS-2) vs required alongside the lock (DATA-1).** Resolution: lock plus constraint, with `IntegrityError` recorded as a feed failure; OPS's own tradeoff prefers failing loudly. Losing position: "constraint optional".
- **DATA-4: filter vs warn.** Resolution: warn, because silently dropping recorded progress is its own correctness problem. This matches the reviewer's preference.
- **ARCH-3 two-pass pricing (+1 engine run) vs ARCH-7 (fewer runs).** Correctness wins over performance by the brief's order; L4 offsets the cost.
- **EVE-2 pinning vs schedule length.** Escalated as D2.
- **UX-6 (release queue early) vs the `scope: 'plan-edit'` Keep.** No conflict: the scope stays. UX-6 is sequenced after N7.
- **SEC-3 range restriction vs unit tests using 90000001/2/999.** Resolved by `None` in `test.py`, as SEC proposed.

## Keep (do not regress)
- Engine purity and lazy scipy; engine dataclasses as API types; computed reservations; `purchase_options` reruns the full plan; market fetch separate from the pure pricing math. (ARCH)
- Client-matched formulas: materials rounding, fees, copy/invention cost, chance, decryptors, skills, max runs, security classes, reprocessing yield; SDE-driven rig and structure bonuses. (EVE)
- SSO: PKCE, single-use state, strict JWT validation; refresh under a row lock with a character check; owner-hash detach; CSRF on unsafe calls; owner scoping on every endpoint; share 404s; link aliasing; prod settings; Vite on loopback. (SEC)
- Atomic snapshot replace; failed fetch keeps old data; jobs upserted; JobLink tombstones; SDE import in one transaction. (DATA, OPS)
- Per-character ETag keys; current compatibility date; crontab matches cache times; market fallback to average; per-mode cron locks. (OPS)
- Postgres tests; ESI mocked at the transport layer; autouse `no_market`; client-named formula tests; Playwright reserved ids, cleanup and web-first expects. (QA)
- One `['plans']` query-key tree; `useLocalCopy` with rollback; scoped edits; pinned ore mix with its age label; `Why` everywhere; shared views reuse owner components; clipboard fallback; destructive confirms. (UX)

## Rejected findings
- None rejected.
- Adjusted: the UX-1 reference is `frontend/src/lib/api/hooks.ts:65-72`, not 115-122. The DATA-1 model references are `apps/esidata/models.py:101/:129`, not 221-272. Neither changes the finding.
- DATA-1/OPS-2 raised from P2 to P1.

## Coverage gaps
- **Slot mechanics (PM-originated):** ARCH-1 handed two questions to the mechanics lane (whether corp jobs use the installer's slots, and whether "ready" jobs hold a slot). EVE didn't answer them. Folded into D1.
- **Link-share substring scrubbing** (`sharing.py:208-216,416-427`; ARCH concern, QA out of lane): no owner. It belongs in the D3 block, and should move earlier if links are shared outside the corp.
- **Unowned out-of-lane notes:**
  - `/progress` is a GET with side effects.
  - `viewer_corporations` calls ESI inside a GET.
  - `price_item` prices the short units at the dearest order (a buy-price policy question).
  - `edit_plan` doesn't validate `extra_location_ids`/`hangar_flags`.
  - uvicorn runs with `--forwarded-allow-ips="*"`.
  - Open signup spends the ESI budget.

  The last three are in D3/L19.
- **Performance is unmeasured:** `/result` and `/progress` with several reserving plans, and rendering a 120-Maelstrom plan. Measure before L4.
- **Concurrent pytest runs share `test_eveindy`.** Unowned; it affects parallel agents and worktrees.
- **Dev worker restart mid-sync** (`acks_late` with a 1 h visibility timeout) and the mounted scheduler running against an unmigrated DB: unconfirmed and unowned.
- **Not reviewed by anyone:** accessibility; the npm/uv dependency audit; the second half of `LibraryPage.tsx`; the ore LP model beyond yield and tax. No reviewer ran Playwright.
- **QA concern:** `bpc()` in `tests/engine/data.py:231-232` can give two BPCs the same item id. Check it during N2.

## Verification status
- **Verified by the PM (read-only):**
  - EVE-1: code at `planner.py:197-211` and `gamedata.py:150`, plus an SDE query showing 45732 unpublished and 46207 published, both producing 16672. Which one wins comes from the reviewer's run; the PM did not rerun it.
  - ARCH-1: `schedule.py:71-74`, `types.py:268-275`, `inputs.py:57-67`.
  - QA-1: `data.py:1-4`, `redesign.md:155`, `base.py:158`, `crontab`.
  - UX-1/DATA-3/OPS-3: `plans_api.py:359-366`, a grep of `apps/planning`, `hooks.ts:65-72`, `main.tsx:13`.
  - DATA-1/OPS-2: `sync.py:133-158`, no unique constraint, concurrency 2, cache-only dedup in `tasks.py`. The OPS probe test was not rerun.
- **Not verified by the PM:** all P2 and P3 items, which rest on the reviewers' evidence. Marked inferred by reviewers: DATA-2, OPS-5, the 420 semantics in OPS-6, the reachability claims in SEC-2 and SEC-3, and EVE-3's server-applied attribute.
- No lane filed a P0.
