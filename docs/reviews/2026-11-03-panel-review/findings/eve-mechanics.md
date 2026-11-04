# EVE Industry Mechanics SME findings

## Summary
The engine's formulas for materials, time, max runs, fees, invention chance, decryptor output and skills match the decompiled V24.01 client and the SDE in every place I traced. The serious problem is in choosing which blueprint makes an item. `_Planner.__init__` maps each product to the last blueprint it sees, and it includes unpublished blueprints. In the current SDE, Tungsten Carbide gets planned from the unpublished "Test Reaction Blueprint": a different recipe, owned formulas aren't recognised, and its reaction jobs are never tracked. That affects every Amarr T2 hull, Amarr T2 component and T2 laser crystal plan that builds its own reactions. The other findings are smaller: invention chance is computed for the best inventor while the jobs can be scheduled on weaker alts; rig bonuses that live in non-standard attributes are dropped; and a few client rules (the 30-day limit on copies, reprocessing tax, T3 reverse engineering) aren't modelled.

## What I checked
- `backend/engine/formulas.py`, `constants.py`, `schedule.py`, `planner.py` (producers, station choice, blueprint sources, 30-day split, `_bpo_layout`, invention, fees), `reprocess.py`, `apps/sde/gamedata.py`, `apps/planning/tracker.py`, `apps/planning/inputs.py` (cost index mapping), `apps/esidata/sync.py:486-504`.
- Client: `industry/job.py` (materials, time, cost, tax, SCC, safe-sec tax, RUN_LENGTH validation), `industry/activity.py`, `industry/activities/{manufacturing,copying,invention,reaction}.py`, `industry/const.py`, `eve/common/script/util/industryCommon.py` (Facility, GetDecryptors, GetJobModifiers, GetBlueprintPrice/JobPrices), `eveuniverse/security.py`, `reprocessing/util.py`, `clonegrade/const.py`, `security/common/const.py`, `inventorycommon/const.py` (attribute and group ids).
- SDE (dev DB, SELECT only): skill dogma for 3380/3388/3402/45746 and the slot skills; every `industryModifierSources` entry compared with the attribute the code reads (script `scratchpad/eve/rigs.py`); duplicate producers for one product (script `scratchpad/eve/prod.py`, which builds `game_data()` and repeats the planner's producer mapping); reaction formula groups; manufacturing BPCs whose max runs can exceed 30 days; relic invention data; reprocessing rig groups; ESI cost-index activity names.
- Owner's station rows (aggregate SELECT, to set severity): nullsec (-0.22), Raitaru/Azbel/Tatara/Fortizar, only M-Set Large Ship ME/TE rigs and an L-Set Reprocessing Monitor.
- `uv run pytest -q tests/engine` → 123 passed.

## Findings

### EVE-1: Unpublished "Test Reaction Blueprint" is the producer of Tungsten Carbide; the producer map picks the last blueprint it sees, published or not
- **Severity:** P1
- **Status:** verified
- **Evidence:** `backend/engine/planner.py:197-211` assigns `self.producers[product] = …` for every blueprint (manufacturing: the last one wins; reaction: the first one wins). `backend/apps/sde/gamedata.py:150` loads every `Blueprint` with `removed=False`, without checking `published`. SDE: Tungsten Carbide has two reaction blueprints: 45732 "Test Reaction Blueprint" (unpublished, 360 s, 16657×100 + 16661×100 → 20 units) and 46207 "Tungsten Carbide Reaction Formula" (published, 10800 s, adds 4051×5 fuel blocks, → 10000 units). Running the planner's mapping on the live `game_data()` gives `Tungsten Carbide producer: (45732, 'reaction') Test Reaction Blueprint`. Tungsten Carbide is in the tree of Zealot, Damnation, Purifier and Sacrilege, and is an input of Amarr T2 components (Nanoelectrical Microprocessor, Tesseract Capacitor Unit, EM Pulse Generator, Radar Sensor Cluster, Antimatter Reactor Unit, Fusion Thruster, Laser Focusing Crystals) and T2 laser crystals. The same mapping also picks an unpublished producer for 'Firewall' Signal Amplifier (RADAR Firewall Blueprint) and 'Bootleg' Remote Sensor Booster ('Entrepreneur' … Blueprint).
- **Problem:** Any such plan that builds its intermediate reactions gets the wrong recipe for Tungsten Carbide. Inputs, run count, reaction time and fees are all wrong, and fuel blocks are missing. The owner's real 46207 formula is never matched to that item, so the plan reports "no owned blueprint". The tracker's `plan_keys` holds (45732, reaction), so real Tungsten Carbide jobs are never linked to the plan. The choice also depends on database row order, so a later SDE import could change it silently.
- **Recommendation:** In `gamedata._game_data`, mark each blueprint as published or not, either from its `EveType` or by leaving unpublished blueprint types out of `blueprints`. When building `producers` and `invented_from`, prefer a published blueprint and break ties deterministically by lowest type id. Add an engine test with two producers for one product, one of them unpublished.
- **Effort:** S
- **Tradeoffs / dependencies:** An owned blueprint of an unpublished type (rare) would no longer act as a producer. Leaving it as a fallback, used only when no published blueprint exists, avoids that.

### EVE-2: Invention chance is computed for the best inventor, but the scheduler can put the invention jobs on any eligible character
- **Severity:** P2
- **Status:** verified
- **Evidence:** `planner.py:942-971` (`best_inventor` takes the highest-chance character), and `planner.py:986-1000` sets attempts = `ceil(bpcs / p)` from that chance. The invention `WorkJob` (`planner.py:1180-1192`) carries only `skills=inv.skills`. `schedule.py:105-117` (`_place`) gives the job to whichever character meets the minimum skills and finishes it soonest, so chance never enters that choice.
- **Problem:** With several alts at different science and encryption levels (the owner runs three), some invention jobs land on weaker characters. Their real chance is lower, so the planned number of attempts, the datacores and decryptors on the shopping list, and the T2 BPC count are all optimistic. The tracker corrects this only after delivery, as another round of invention.
- **Recommendation:** Smallest fix: add an optional `characters` restriction to `WorkJob`, set it on invention jobs to the characters whose chance equals the chance used, and have `_place` honour it. The alternative, computing attempts from the chance of whoever is scheduled, needs another planning pass after scheduling and is larger.
- **Effort:** S
- **Tradeoffs / dependencies:** Pinning invention to the best inventors can lengthen the schedule when they have few science slots. The reason text should say so.

### EVE-3: Rig bonus is read from fixed attributes 2593/2594/2595 (2713/2714 for reactions); Thukker and Upwell Outpost rigs keep theirs elsewhere, so it is dropped or understated
- **Severity:** P3
- **Status:** verified (the code path and SDE values); the attribute the server actually applies is inferred
- **Evidence:** `gamedata.py:247-254` uses `ATTR_ENGINEERING_RIG[kind]` and skips the bonus when that attribute is missing or 0. SDE: "Standup M-Set Thukker Basic Capital Component Manufacturing Material Efficiency" and the L-Set version have no attr 2594. Their material bonus is attr 2653 `attributeThukkerEngRigMatBonus` "Thukker Enhanced Capital Component Material Reduction Bonus" (-3.7), so the code applies 0 %. The Thukker Advanced Component rigs have 2594 = -2.0 and 2653 = -3.7, with separate entries for filter 14 (advanced components) and filter 15 (advanced capital components, attr 2658). The code applies 2.0 % to both. "Upwell A1F/A2FP/A3PFO/C1L Outpost Rig" have no 2593. Their time and science bonuses are in 2773/2774/2778-2783 (-40 to -60 %), so the code drops them. Of the 462 rig entries, 149 time and 2 material entries resolve to a missing attribute; the rest are rigs that have no bonus for that kind.
- **Problem:** A station with these rigs is planned with no bonus, or a smaller one, for capital components and outpost activities. The owner's stations have none of these rigs (nullsec, Large Ship M-Set rigs only), so nothing is wrong for them today.
- **Recommendation:** Map rig bonus attributes per (rig, target structure attribute), e.g. Thukker: filter 13/15 entries → 2653, others → 2594. Otherwise, when a rig has a non-zero modifier entry and the standard attribute is absent, emit a warning so a silent 0 % becomes visible. Confirming the mapping needs `dogmaEffects` (not imported) or an in-game check.
- **Effort:** S (warning) / M (mapping)
- **Tradeoffs / dependencies:** none

### EVE-4: The 30-day job length check applies to jobs on copies too; the engine assumes copies are limited only by their runs
- **Severity:** P3
- **Status:** verified
- **Evidence:** Client `industry/job.py:590-594`: `time_previous = time - time / runs; if time_previous > MAX_RUN_LENGTH: add_error(RUN_LENGTH)`, run for every job regardless of blueprint type. `planner.py:868-885` `split_long` splits only BPO/MISSING specs, and its docstring says "copies are limited only by their runs". `docs/redesign.md` "Client code" records the same RUN_LENGTH rule without that exception. SDE: Capital Flex Shield Hardener I (100 runs × 36000 s = 41.7 days at TE 0) and Odysseus (10 × 300000 s = 34.7 days) can exceed it. Bought BPCs default to max runs (`planner.py:543`).
- **Problem:** With low skills, a planned job on a full-run copy of those items would be refused in game. It affects few items.
- **Recommendation:** Apply the same cap in `split_long` to BPC/BOUGHT/INVENTION/COPY specs: split one copy's runs into consecutive jobs on the same lock. Fix the docstring.
- **Effort:** S
- **Tradeoffs / dependencies:** none

### EVE-5: T3 reverse engineering is planned as T2 invention from whichever relic the dict holds last
- **Severity:** P3
- **Status:** verified (code + SDE); in-game consequence inferred
- **Evidence:** `planner.py:204-206` `self.invented_from[product] = (bp.type_id, inv)`, last one wins. SDE: each T3 subsystem/hull blueprint is invented from Intact (p 0.26, 20 runs), Malfunctioning (0.21, 10) or Wrecked (0.14, 3) relics; 79 T3 products have several sources. Relics have only an invention activity, no copying, so `plan_invention` (`planner.py:1106-1162`) always warns "needs N more T1 copy runs… no T1 BPO to copy" and never puts relics on the shopping list.
- **Problem:** T3 plans get an arbitrary chance and run count, plus a misleading warning. This is outside the owner's stated batches.
- **Recommendation:** Until relics are modelled as consumed inputs, treat relic-sourced blueprints as "missing" with a "T3 reverse engineering not modelled" warning.
- **Effort:** S
- **Tradeoffs / dependencies:** Fixing EVE-1's deterministic tie-break covers the arbitrary choice but not the mechanics.

### EVE-6: Compressed ore calculator ignores the structure's reprocessing tax
- **Severity:** P3
- **Status:** verified (client); impact inferred
- **Evidence:** Client `reprocessing/util.py` `_GetRecoverablesFromFixedMaterials`: `station = recoverable * stationsTake; iskCost = round(adjusted price * station, 2)`. The tax is charged in ISK on the output's adjusted value. `engine/reprocess.py` and `apps/planning/ore_api.py` have no tax term (grep for tax/take finds nothing).
- **Problem:** In someone else's refinery, ore cost is understated compared with buying minerals, which can tip the ore-or-minerals comparison. In the owner's own Tatara the tax is likely 0.
- **Recommendation:** Add an optional reprocessing tax percent to `Refinery` and add `tax × Σ adjusted price × produced` to each ore's cost in the objective.
- **Effort:** S
- **Tradeoffs / dependencies:** needs adjusted prices passed into the calculator

### EVE-7: The docs say EIV can't be checked in client code; the client does compute it
- **Severity:** P3
- **Status:** verified
- **Evidence:** `eve/common/script/util/industryCommon.py:521-555` `GetBlueprintPrice(typeID, activityID)` = Σ over the blueprint's activity materials of quantity × adjusted price; science activities use the MANUFACTURING materials; set as `job.prices = JobPrices(activityID)` in `eve/client/script/industry/industrySvc.py:97`. The server checks the client's cost against its own (`job.py:596`, MISMATCH_COST). `docs/redesign.md` lines 160 and 226 say EIV "comes from the server… can't be checked in client code" and tag it [community].
- **Problem:** The engine (`formulas.estimated_item_value`, `eiv_materials` choices at `planner.py:717,746,1141,1201`) already matches the client, but the docs mark a verified formula as unverified.
- **Recommendation:** Change the tag to [client] and cite `GetBlueprintPrice`.
- **Effort:** S
- **Tradeoffs / dependencies:** none

## Keep
- Materials per job: `max(runs, ceil(round(base×runs×mods, 2)))` is the same as `job.py:470-479`; Python 2 vs 3 `round` can't differ here, because no exact binary half at 2 decimals crosses an integer.
- Fee breakdown (`formulas.job_fee`): unrounded base into the job cost, rounded base for tax/SCC/safe-sec, alpha additive at 0.25 %, SCC 4 %, safe-sec ≥ 0.95. Matches `job.py:127-172,310-320,450-456` and the constants in `industry/const.py:147-150`, `clonegrade/const.py:33`, `security/common/const.py:8`.
- Blueprint attr 1954 applied to every activity using the job's own blueprint (T1 for copy/invention): `industryCommon.BLUEPRINT_MODIFIERS` activity None, `planner.py:645,1086`.
- Copy and invention costs (licensed runs × copies × 2 % × T1 EIV; attempts × 2 % × T2 EIV): `activities/copying.py`, `activities/invention.py`.
- Invention chance, encryption skills at 1/40, ME 2 / TE 4 + decryptor, runs = base + decryptor, decryptor attrs 1112-1114/1124, group 1304: client `invention.py`, `const.py:153-156`, `inventorycommon/const.py:1030`.
- Skill bonuses (Industry -4, Adv Industry -3, Science -5, Reactions -4) and slot skills: SDE typeDogma attrs 440/1961/452/2660/450/471/2661 on the listed skills.
- Max runs on originals computed without skills (`formulas.max_runs`): always within the client's `job_max_runs`/RUN_LENGTH, so a planned job is valid whoever installs it.
- Security classes: same as `eveuniverse/security.py:21-29`. Rig security multipliers come from SDE 2355-2357 (null 2.1 checked on the owner's rig).
- Station and rig bonuses come from `industryModifierSources`/`industryTargetFilters`, not hard-coded maps; lab and invention rigs resolve correctly (2593/2595 present).
- Reprocessing yield `min(1, station × Π(1+level×attr379/100))`, floor per material on whole batches: `reprocessing/util.py` `GetRefiningYieldPercentageForType`, `_GetEfficiency`, `_GetRecoverablesFromFixedMaterials`.
- Tracker: invention attempts count until delivery; delivered T2 copies then arrive as owned BPCs, so each one is counted once (`tracker.py:106-118` with `planner.py:986-990`).

## Concerns to investigate
- Invention attempts are the expected value `ceil(bpcs/p)`, so about half of all runs fall short and need a second round. An optional margin (e.g. attempts for 90 % confidence) would help batch builders. Confirm whether the owner prefers one round with a margin.
- Rig security multiplier is also applied to rig cost bonuses (`formulas.py:152`). The server-side rule isn't visible in client code; an in-game job window with a lab rig in null/low would confirm it.
- Remote install range (Supply Chain Management / Scientific Networking, `industry/const.py:130-140` and `job.py` FACILITY_DISTANCE) is not checked when scheduling characters. It only matters if alts sit far from the build station.
- The new "X-Grade" ores (groups 5083-5086) are classified as asteroid ore for M-Set rigs; whether the Asteroid Ore Grading Processor covers them is unverified.
- Engine output has not been compared with an in-game job window (docs say so). One manufacturing, one reaction and one invention window from the owner's structures would close this.

## Out of lane
- none
