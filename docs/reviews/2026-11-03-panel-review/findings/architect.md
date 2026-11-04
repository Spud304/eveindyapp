# Staff Engineer / Architect findings

## Summary
The engine/Django split is clean: the engine imports nothing from Django, the API returns engine dataclasses directly, and the frontend renders reasons rather than deriving values. The main design gap is in the inputs: `PlanInput` has no idea which character slots are already busy, and reservation covers items but not blueprints, so each plan's schedule and BPC usage are computed as if it were the only work on the account. The "one result feeds every view" goal also has a known hole, because Jita repricing happens after planning: decryptor choice, some reason texts, a warning and the buy options stay at CCP average prices. The size of `planner.py` matters less than the 320-line `plan_blueprint`, which is where most recent features have landed.

## What I checked
- `backend/engine/{types,planner,pricing,options,schedule}.py`, `engine/__init__.py`; `backend/apps/planning/{inputs,reservation,tracker,plans_api,sharing,prices,api}.py`; `apps/sde/gamedata.py` (caching).
- `frontend/src/features/plans/{PlanPage,tabs,progress}.tsx`, `frontend/src/lib/api/hooks.ts` (query keys and invalidation).
- `docs/redesign.md` sections on reservation, tracker, repricing (line 388), BPC lines (356), auto-copy (352–364).
- `grep` for engine imports in `apps/` and non-stdlib imports in `engine/` (none outside numpy/scipy, which are lazy-loaded in `reprocess.py:166`); `grep` for callers of `inputs.plan_input` / `/api/plan/preview`.
- `git log -- backend/engine/planner.py` (15 commits, +2057/−411).
- `uv run pytest -q tests/engine`: 123 passed in 1.76 s.

## Findings

### ARCH-1: The schedule treats every character slot as free at t=0; running jobs are not an engine input
- **Severity:** P1
- **Status:** verified (code path). Impact on real plans: inferred.
- **Evidence:** `engine/schedule.py:71-74` seeds every slot with `[0.0] * f.slots(ch, activity)`. `Character` (`engine/types.py:269-275`) and `PlanInput` (`types.py:352-371`) have no field for slot occupancy, and `inputs.characters` (`apps/planning/inputs.py:57-67`) passes only skills. The only "busy" input is per blueprint item (`OwnedBlueprint.job_ends_in` → `planner.py:213-218` `self.busy` → schedule `locks`), which covers blueprints but not slots. Running jobs reach the engine only as `started` units (`tracker.py:374-391`): they lower demand but take no slot time.
- **Problem:** Once a plan is under way (the normal state for the active plan), its remaining jobs are scheduled to start now on slots that its own running jobs, other plans' jobs or unplanned jobs are using. Start times, `total_seconds`, and every finish-time decision built on them are optimistic. Those decisions are the auto-copy and BPC-spread search (`_search_parallel`, `MIN_SPLIT_GAIN`) and `seconds_saved` in buy options. The design calls slots "the real constraint" (`redesign.md:63`), but the engine cannot see which ones are taken.
- **Recommendation:** Add `busy_slots: Mapping[int, Mapping[str, tuple[float, ...]]]` to `PlanInput` (character id → slot kind → seconds until each busy slot frees). Build it in `reservation.load` from open `IndustryJob` rows by `installer_id` (`owner_q(user, Feed.JOBS)`, statuses active/paused, matching the dashboard rule at `redesign.md:332`). Have `schedule()` seed `free` from it, clamping to the slot count. Then add one engine test where a busy slot delays a job.
- **Effort:** M
- **Tradeoffs / dependencies:** Two things here are unconfirmed and belong to the game-mechanics reviewer. First, whether corp jobs count against the installer's personal slots (inferred yes; confirm in the client's `industry/` slot counting). Second, whether `ready` jobs hold a slot, which the docs already say is unknown. The split search reads the same schedule, so its results will change.

### ARCH-2: Reservation covers items only; plans share unpicked BPCs and BPO time
- **Severity:** P2
- **Status:** verified
- **Evidence:** `reservation.py:190-193`: a plan's blueprints are every owned blueprint except BPCs picked by *another* plan's line. Claims come only from `ItemPlan.on_hand_used` (`reservation.py:258-263`). `PlannedJob` (`types.py:486-503`) has no blueprint item id: `freeze` (`planner.py:1302-1326`) drops `WorkJob.lock` (`item:<id>`, `planner.py:1610`), so the result never says which BPC a job uses.
- **Problem:** Two reserving plans that need the same blueprint both count the same BPC runs, for example the 11 Maelstrom BPCs at `redesign.md:355`, and both schedule the same BPO from t=0. That is the double count reservation exists to prevent for materials, and it affects the higher-priority plan's view of what the lower one can do. Separately, the user installing jobs cannot see which BPC item each job assumes. That makes a planned BPC that has since disappeared hard to notice, which is already a known open item.
- **Recommendation:** Add `blueprint_item_id: int | None` to `PlannedJob`, set from the `item:` lock in `freeze`. In `run_plans`, after each reserving plan, subtract the BPC runs its jobs use from a per-item runs pool, and pass later plans `OwnedBlueprint`s with the remaining runs (dropping those with none left). Leave BPO time-sharing unmodelled and say so in a warning when two reserving plans use the same BPO.
- **Effort:** M
- **Tradeoffs / dependencies:** Exposing the item id also helps the UI ("install with BPC #…"). BPO time-sharing across plans would need cross-plan scheduling, which is out of proportion for now.

### ARCH-3: Jita repricing after planning leaves average-priced values inside the result
- **Severity:** P2
- **Status:** verified
- **Evidence:** `engine/pricing.py:469-506` replaces the shopping list and `CostSummary` only. Values that stay at CCP average:
  - The automatic decryptor choice and its reason text quoting ISK figures (`planner.py:1062-1072`), plus `DecryptorOption.*_cost`.
  - The auto-copy note "more units of materials (N ISK)" (`planner.py:959-962`).
  - The engine's warning "N shopping item(s) have no price and are left out of totals" (`planner.py:1428-1432`). `reprice` copies it unchanged (`pricing.py:495`) even when Jita books priced those items.
  - Buy options' `cost_change`, BPO `purchase_cost` and their reason text (`options.py:64-74`, `117-127`). The endpoint (`plans_api.py:400-408`) never reprices them, while the same extra BPO on the shopping list is shown at Jita.
  - `redesign.md:388` acknowledges the decryptor and buy-option parts. The stale warning and the reason texts are not mentioned there.
- **Problem:** This contradicts the stated goal that every view reads one result, so tabs cannot disagree. The Cost tab shows Jita totals while the Blueprints tab explains the decryptor and buy options in average ISK. The decryptor is a purchase decision, so choosing it on a different price than the one shown can pick the wrong decryptor.
- **Recommendation:** Price before planning instead of after, in two passes:
  - Do the first pass at average prices.
  - Fetch Jita books for its shopping types plus all decryptors and datacores of invented blueprints.
  - Set `Price.unit_price` per type to `book_cost(qty)/qty` at the first-pass quantity (best ask for types not bought).
  - Run the plan again with those prices, and pass the same prices to `purchase_options`.
  - `reprice` then becomes a consistency check.
  - Smallest interim fix (S): in `reprice`, drop the engine's "no price" warning when `unpriced` is empty or shorter, and run `jita_priced` over the option results' purchase cost.
- **Effort:** M (S for the interim fix)
- **Tradeoffs / dependencies:** One more engine run per result request and a wider book fetch (decryptor types are cached the same way). The `prices=average` switch keeps working by skipping the price step.

### ARCH-4: A second, divergent PlanInput assembly path (`/api/plan/preview`) is unused
- **Severity:** P3
- **Status:** verified
- **Evidence:** `apps/planning/inputs.py:190-210` (`plan_input`) and `inputs.py:149-153` (`available_assets`) are called only from `api.py:210-221` (`POST /api/plan/preview`) and tests (`tests/planning/test_planning.py:98-112,232-247`). The frontend never calls it: the only match is in generated `schema.d.ts`. Compared with `reservation.plan_input`, it has no reservation, no progress, no incoming copies, no per-plan station or hangar scope, and no picked-BPC exclusion. It also accepts only 3 of `BlueprintChoice`'s 11 fields. The module docstring is stale: "Asset reservation between plans is step 3; until then every plan sees all of them." (`inputs.py:9-10`).
- **Problem:** Two ways to build `PlanInput` that give different answers for the same account. Any future caller, such as a quick calculator, would silently get the less complete one.
- **Recommendation:** Delete the preview endpoint, `inputs.plan_input` and `available_assets` and their tests, fix the docstring, and run `npm run gen:api`. If a no-plan preview is wanted later, build it from `reservation.load` and an unsaved `Plan`.
- **Effort:** S
- **Tradeoffs / dependencies:** none

### ARCH-5: `plan_blueprint` is a 320-line method that every blueprint-source feature modifies
- **Severity:** P3
- **Status:** verified
- **Evidence:** `engine/planner.py:471-790`. Source selection (picked BPCs, bought BPCs, BPC pool, BPO and extra BPOs, invention, missing) runs at about 486-631. It is mixed with auto-copy layout setup (633-672), job creation (697-750) and note text (674-788). 7 of the last 10 commits touching `planner.py` changed this block: `886e1c7`, `c9c0293`, `f970aaf`, `d7b5a0a`, `12b6ecb`, `85d7189`, `4316e21`. The file length itself (1646 lines) is less of a problem: `_search_parallel` and `plan_invention` are separable and documented.
- **Problem:** Source order is the rule users most need to predict ("which blueprint is used for which runs"), and it is only testable through whole-plan runs. Each new source adds closure state (`nonlocal` counters, `use_bpc`) to the same method.
- **Recommendation:** Extract source selection into a function `_choose_sources(owned, choice, picked, runs, is_reaction, bp_data) -> (prefix specs, pool, pool_need, suffix specs, notes)` and give it its own unit tests. Leave job creation where it is. Don't split the file just because it is long.
- **Effort:** M
- **Tradeoffs / dependencies:** It is a pure refactor and the 123 engine tests cover it. Do it before the next source rule is added rather than on its own.

### ARCH-6: Progress assembly lives in the API module and is reached through import cycles
- **Severity:** P3
- **Status:** verified
- **Evidence:** `plans_api.progress_data` (`plans_api.py:456-557`) and `_products` are domain logic that `sharing._build` reaches with a function-level import, commented "the API module imports this one" (`sharing.py:331`). `tracker` and `reservation` import each other: `reservation.py:39` at module level, and `tracker.py:332,345` inside functions.
- **Problem:** The shared view's progress depends on an HTTP module. Each new consumer of progress (dashboard, exports) inherits the cycle.
- **Recommendation:** Move `progress_data` and `_products` into `apps/planning/tracker.py` (or a new `progress.py`). Move `plan_input`, `plan_scope` and `effective_rules` from `reservation.py` into `inputs.py`, so `tracker` depends on `inputs` and not on `reservation`.
- **Effort:** S
- **Tradeoffs / dependencies:** Combine with ARCH-4, which also touches `inputs.py`.

### ARCH-7: Redundant engine runs within one request
- **Severity:** P3
- **Status:** verified (code path). Cost not measured.
- **Evidence:** `GET /plans/{id}/progress` runs `base_result` twice: once in `tracker.match` (`tracker.py:351`) and again in `progress_data` (`plans_api.py:459`). `run_plans` runs every reserving plan (`reservation.py:254-265`) even when the requested plan is itself reserving and earlier in priority, so later plans cannot affect it. Opening a plan page fires both `/result` and `/progress`, so reserving plans run twice per page load. `plan()` may run `_Planner` twice plus the split search (`planner.py:69-79`).
- **Problem:** This is waste on top of the known "no cache" item, not a new class of problem. It matters only as plans and reserving plans multiply.
- **Recommendation:** Have `match` accept and return the base result so `plan_progress` reuses it. In `run_plans`, stop the reserving loop after the last wanted plan when no non-reserving plan is wanted.
- **Effort:** S
- **Tradeoffs / dependencies:** none

## Keep
- Engine purity: no Django imports in `engine/`, and scipy/numpy are imported lazily (`reprocess.py:166`). Apps call the engine only through `plan`, `purchase_options`, `formulas`, `reprocess` and `pricing`.
- Engine dataclasses are the API response types (`plans_api.py:364`, `PlanResult`), so the generated TS types cannot drift from the engine.
- Reservations are computed, not stored, and claims shrink through `started` (`reservation.py:1-16`, `redesign.md:74,82`). This avoids stale claims at the cost of reruns, which is the right trade for one account.
- `purchase_options` reruns the whole plan instead of using a side formula (`options.py:1-6`), so time saved and cost change come from the same scheduler and cost code.
- Market fetching is in `apps/planning/prices.py` and the arithmetic is in pure `engine/pricing.py`, which is tested in `tests/engine/test_pricing.py`.
- `gamedata.game_data()` is cached per process, keyed by SDE build (`gamedata.py:72-102`).
- The frontend is a thin reader: it renders `reason.text` and engine totals. Its only client-side sums are display-only (`tabs.tsx:29,360`). It invalidates every plan result when job links change (`hooks.ts:357-360`).
- The shared view builds result and progress from one `run_plans` call in one payload (`sharing.py:333-357`).

## Concerns to investigate
- Link anonymization replaces owner names inside free-text reasons by string substitution (`sharing.py:416-427`), because `Reason` has no structured references. Any reason that formats a name differently (truncated, possessive, joined) would leak it. The security reviewer should grep every f-string in `planner.py` and `schedule.py` that embeds `ch.name` or a station name.
- Wall time of `/progress` and `/result` on the dev account with several reserving plans is unmeasured. Timing both endpoints with the Playwright reserved accounts plus 3–4 reserving plans would show whether ARCH-7 matters.
- Whether `PlanInput.started` from running jobs and assets from the next sync can overlap during the window between a job's delivery and the next asset sync (`tracker.py:287-291` argues they cannot for non-line products). A test with a delivered intermediate whose asset sync has not run yet would confirm it.

## Out of lane
- `sharing.viewer_corporations` calls ESI's affiliation endpoint inside a GET request path (`sharing.py:270-282`) (ESI/ops).
- `edit_plan` stores `extra_location_ids` and `hangar_flags` without validating them against the account's locations or known flags (`plans_api.py:66-67,293-295`) (security/QA).
- `price_item` prices the units short at the dearest order or the average, whichever is higher (`pricing.py:457-459`): whether that is a sensible buy price is a market/UX call.
