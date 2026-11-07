# EVE Indy App — Redesign

Status: draft, agreed direction (2026-11-03). Source of truth for the rewrite; update it when decisions change.

## Goal

Answer one question well, for me and anyone with the same use case:

> I have these characters, these skills, these stations, and these assets (personal **and corp**).
> I want to build these things. What's the plan — and where are we on it?

The app becomes **plan-centric**. Today it is tool-centric (Calculator / Invention / Production pages that each half-answer the question and disagree with each other).

## Users and use case

- Knows what they want to build; does not need a "what's profitable" scanner. Not planned (decided 2026-11-04).
- Runs multiple linked characters, mostly out of **corp hangars and corp industry jobs**.
- Builds in batches of several items ("indy 1": 10 Ishtar + 50 Hulk; "dreadbatch 1": 1 Phoenix, 2 Naglfar, 1 Revelation Navy Issue).
- Takes shopping lists to **Janice**; buys compressed ore.
- Wants corpmates to see plan progress.

## Core concepts

### Plan
A named, saved set of `(item, quantity)` lines. Both a **planner** (what to build, buy, copy, invent, where, by whom) and a **tracker** (what's running, done, delivered).

Plan settings:
- **Active** — exactly one plan at a time is the active plan; the tracker attributes new jobs to it (see Job tracking).
- **Build rules** — account defaults, overridable per plan (see Build rules).
- **Reserve assets** (checkbox) — see Asset reservation.
- **Visibility** — private / corp / anyone with link.
- **Priority** — order among reserving plans.
- **Complete** (added 2026-11-05, `Plan.completed_at`): set by hand and undone with Reopen.
  - A completed plan is not active and can't be made active until reopened.
  - It reserves no stock or BPC runs.
  - It holds no picked BPCs, so another plan can pick them. Reopening is refused if one has been picked since.
  - Its lines, settings and linked jobs stay. The plans list shows it under Completed.
  - Rejected: completing a plan automatically when every job is delivered. Leftovers and partial batches make "done" the owner's call.

No deadlines. A "done by" date isn't useful in practice; the plan just shows how long it will take.

Shared sub-components across lines are merged (one Ishtar/Hulk common component stack, not two).

### Plan view (tabs)

| Tab | Answers |
|---|---|
| **Shopping list** | What to buy after subtracting available assets. Janice export. Compressed-ore option for minerals. |
| **Blueprints** | Owned (all chars + corp), missing, BPO vs copy vs buy-BPC per blueprint, invention for T2 lines. |
| **Schedule** | Which character runs which job, in which station, in what order; estimated wall-clock to completion. |
| **Progress** | Planned jobs matched to live ESI jobs (character + corp): planned → running → ready → delivered. Materials on hand vs needed. |
| **Cost** | Materials, job fees, invention, bought BPCs — per line and total. |

### Build rules (build vs buy)
"I can't be bothered to build this" is a first-class setting. Anything a rule excludes stops the tree there: it goes on the shopping list as a bought item, and nothing below it is planned.

- **Item blacklist** — specific items always bought (today's material blacklist, kept).
- **Tier/category switches**, e.g.:
  - T2 items / T2 components (don't invent or build T2; buy them)
  - Capital components
  - Reactions by level: intermediate, composite, hybrid, biochemical, molecular-forged (today's toggles)
  - Fuel blocks, other common intermediates (exact list to confirm)
- **Account defaults, per-plan overrides.** A plan shows which rules are in effect and lets you flip one for that plan only.
- The Blueprints tab marks rule-excluded items as "buying (rule: T2 components)" so it's clear why something isn't being built.

### BPO vs BPC trade-off
Decided (2026-11-03):

- The real constraint is **slots**, not dates. Copying costs a small job fee and lab slots; it exists to run more manufacturing jobs in parallel.
- **Correction (2026-11-03): copying is not free speed.** Copying takes 0.8x the manufacturing time per run for 4128 of the SDE's blueprints [SDE], and a BPO is in one job at a time, so a BPO that copies is not building. A BPO that could start building at once gains about 10% at best. Copying pays off when the BPO would otherwise wait for its inputs (it copies while the components build) or when there are spare BPOs.
- **Default (decided 2026-11-03): copy only when the plan finishes sooner.** The engine tries splitting each owned BPO into the BPO plus copies it makes first, compares the scheduler's finish time, and keeps a split only if the plan finishes at least an hour sooner. Automatic, shown with the time saved, extra materials and copy fee. Rejected: copying whenever manufacturing slots are idle, which can make a plan slower and always costs fees and per-job rounding.
- **Buying BPCs and extra BPOs cost real ISK**, so they're never automatic. Per blueprint, show the trade-off: "buy 3 BPCs (~15M) → finishes ~2 days sooner" / "extra BPO (~80M) → saves ~1 day per batch, reusable". You opt in.
- No plan-level "cheapest vs fastest" preference for now; the per-blueprint choice is enough. Revisit if it gets tedious on big plans.

### Asset reservation
- Plans with **Reserve assets** checked claim matching assets from the pool in **priority order**.
- Non-reserving plans see only what's left over (and show "X reserved by plan Y").
- Reservations shrink as the plan consumes materials (job started → inputs are gone from assets, so the reservation for them must be released, not double-counted). The tracker drives this.
- Location filter per plan: default = assets at the plan's build stations; user can tick other locations/hangars.
- **To move (2026-11-05).** The engine counts a plan's stock at all of its locations as one pile. So the result also lists what has to be carried before jobs can start (`apps/planning/hauling.py`, `PlanResultOut.moves`). There are two kinds of move:
  - Stock in a hangar away from the station that uses it.
  - Items one station builds and another station's jobs use.
- How each item is placed:
  - A station's jobs are covered first by what that station makes, then by stock already there.
  - Anything still missing comes from what other stations make, then from the biggest stacks elsewhere.
  - Only the quantity taken from stock counts; bought items are not placed.
  - A station with no known location (added by hand) gets built-item moves only.
  - Shared views leave the list out, because it names the owner's hangars.
  - Rejected: flagging every item whose stock sits in two places. joe's has enough Tritanium on its own even though Polite holds some, so that flag would warn when nothing needs moving.
  - Live on maelstroms (first version): Megacyte, Mexallon and Zydrine went from Polite to joe's, where the mineral jobs run. Five PI inputs went from joe's to Polite, where the component jobs were planned.
    - Those components then needed 148,450 m³ carried back to joe's, which the stock-only list did not show.
    - That led to the station rule in Planning engine. The components are now built at joe's.
- **Decided (2026-11-03): computed, not stored.** Each request reruns the account's reserving plans in priority order (lower number first, then id). Each claims what its engine run takes from stock (`on_hand_used`) out of a pool kept per (item, location, hangar), and only from buckets inside its own location and hangar filter. Non-reserving plans then run on the leftovers and claim nothing. Rejected: storing claims, because they would go stale whenever assets, plans, prices or rules change. Computing them costs one engine run per reserving plan (live: ~1.3 s for a two-plan account, most of it loading shared data). Claims come from remaining demand, so once the tracker (step 5) lowers demand as jobs start, they shrink without separate release logic.

### Job tracking
- Usually one plan is in progress at a time, so matching is simple: **one plan is marked active**, and any new ESI job (character or corp) started after activation whose blueprint + activity is in the active plan is attributed to it.
- Matching fills planned jobs in order; extra runs beyond the plan show as "over plan".
- Manual unlink/relink for the odd job that isn't for the plan.
- Switching the active plan doesn't move jobs already attributed.
- **Decided (2026-11-03), how progress feeds the plan:**
  - Links are stored (`JobLink`); progress is computed. Each plan run feeds the engine the output of its linked jobs as `started` units. Those cover demand before assets do, plan lines included, so the plan needs fewer runs and fewer inputs. That is the reservation release: the inputs a started job consumed are no longer demanded, and nothing is counted twice.
  - Delivered output counts only for plan lines. Delivered components are in a hangar and arrive through the next asset sync.
  - Invention attempts running for the plan reduce the attempts still needed; delivered T2 copies arrive as owned blueprints.
  - Copy jobs are not fed as progress. The copies an open copy job is making reach the engine as owned BPCs usable when the job ends (see Step 6 progress).
  - Matching uses the plan computed without progress and without assets, so a blueprint stays matchable after its runs are all started or its output is in stock.
  - Cancelled and reverted jobs count for nothing.
  - Corp jobs installed by corpmates match too, as this section says. Unlink the odd one.

### Corp support (first-class, not an add-on)
Data needed, with the ESI role it requires:

| Data | Endpoint | In-game role required |
|---|---|---|
| Corp assets (hangars) | `/corporations/{id}/assets/` | Director |
| Corp blueprints | `/corporations/{id}/blueprints/` | Director |
| Corp industry jobs | `/corporations/{id}/industry/jobs/` | Factory_Manager |
| Hangar division names | `/corporations/{id}/divisions/` | Director |

- Corp data is fetched with whichever linked character holds the role; store **which character** provides each corp feed and surface "no character with Director role — corp assets unavailable".
- Corp hangar items are identified by `location_flag` (`CorpSAG1`–`CorpSAG7`) and division names.
- **Fallback when no one has the role:** paste-import of an inventory window (copy from in-game → parse) as a manual asset snapshot. Low priority: all of my characters are Directors (Director implies every corp role, Factory_Manager included), so corp data is fetched automatically for me. Only matters for other users without roles.
- Personal and corp sources are both selectable per plan.

### Sharing and permissions
- Plan owner + optional editors; viewers (corp or link) see progress, schedule, shopping list.
- **Viewers must not see the raw corp asset list** fetched with a director's token — only what the plan exposes (e.g. "need 40k Tritanium, 30k on hand"). Treat corp data as owner-private by default.
- **Decided (2026-11-03):** corp viewers log in with `publicData` only (the existing login); link viewers need no login and see aliases ("Station 1", "Builder 1", "Corp member 1", "Structure 1") instead of the owner's station, structure and character names, because structure names and stock at them can be sensitive. Editors are deferred: a plan computes from the owner's assets, blueprints and characters, so editing by others needs its own design.

## Other features (after the core)
- **Janice export** — copy button in Janice/EVE multibuy paste format. Later: Janice appraisal API for prices (needs API key).
- **Compressed ore calculator** — given the mineral shortfall, cheapest compressed-ore mix using reprocessing skills + structure/rig yields. Small LP problem.
- **Dashboard** — all characters' + corp jobs, idle slots, finishing soon, token/role problems, active plans' progress.

## What goes away
- Standalone **Production** (continuous profit) page — doesn't match the use case. No plan-level profit view either (decided 2026-11-04: not wanted).
- Changed 2026-11-05 (owner): a plan does show what goes into each line in ISK, stock included (Cost tab, "Value per line"). It is for building for someone else from your own stock. It shows input value only: no sale prices and no margin.
  - Code: `engine/valuation.py`, `PlanResultOut.value`.
  - Every unit of an item carries the average value of all its supply:
    - Stock and bought units at market price. With Jita prices, stock items are looked up too, priced as buying the quantity used.
    - Built units at their jobs' inputs and fees, plus a share of the copy and invention jobs that made their blueprint (split by runs).
    - Started units like a built unit.
  - Shared parts split by quantity used. Surplus and unused copies are reported as left over.
  - Owned blueprints and bought extra BPOs are not counted.
  - Live: dreadbatch 1 is 2.29 B per Phoenix, 6.50 B of the 6.87 B from stock.
- The Flask app itself: removed on 2026-11-04 (`src/`, its migrations, tests, Dockerfile and compose file); git history has it.
- Standalone **Invention** page — folded into plans for T2 lines.
- The **Industry** hub page, the three-form calculator, URL-encoded state.

## Architecture

- **Planning engine**: pure Python module, no Django/DB access. Input: plan lines, characters (skills, slots, roles), stations/rigs, blueprints, assets (after reservation), prices, build rules, BPO/BPC choices. Output: the full plan result (materials, jobs, schedule, costs). Heavily unit-tested. Every view reads from this one result, so tabs can't disagree.
- **Backend**: Django + django-ninja as a JSON API (see Backend stack). Celery for on-demand ESI fetches; cron for scheduled syncs and SDE checks.
- **Frontend**: React (Vite + TypeScript), fresh build — not a port of the Jinja templates. Edit the plan in place; recompute only when inputs change. Visual style and frontend structure: `docs/ui-design.md` (copies the AT Tool style).
- **Explanations in engine output**: the UI shows the reason for every derived value, so engine results carry a reason with each decision (ME source, station chosen and why, bought vs built and which rule, BPC vs BPO choice).
- **Database**: move to **Postgres** (multi-user, shared plans, concurrent Celery writers). SDE stays SQLite, read-only.
- **Account model**: config, stations, plans belong to the **account** (main character), not the logged-in character.

### Data model sketch
- `Account` (main character) → `Character` (linked, tokens, skills)
- `Corporation`, `CorpDataSource` (which character supplies which corp feed)
- `Station` (account-owned, rigs, tax)
- `BuildRules` (account defaults: item blacklist, tier switches) + per-plan overrides
- `Plan` (name, is_active, activated_at, reserve_assets, priority, visibility, owner) → `PlanLine` (type_id, qty)
- `PlanJob` (planned job: blueprint, activity, runs, character, station) ↔ `JobLink` (matched ESI job id, character or corp)
- `AssetSnapshot` (source: character / corp hangar / manual paste, location, flag, type_id, qty, fetched_at)
- `PlanShare` (plan, principal: corp / link token / user, role: viewer / editor)

### Planning engine (`backend/engine/`, steps 0–1 done 2026-11-03)
Pure package (no Django imports) inside the Django project; imported as `engine`, tests in `backend/tests/engine/`. `apps/sde/gamedata.py` builds its static inputs from the imported SDE.

- `types.py`: `PlanInput` (lines, SDE `GameData`, stations, systems with cost indices, characters, owned blueprints, assets after reservation, prices, effective `BuildRules`, per-blueprint `BlueprintChoice`) → `PlanResult` (items, blueprints, jobs, shopping list, costs, total time, warnings). Every decision carries a `Reason(code, text)`.
- `plan()` algorithm: decide build/buy per item → order BUILD items consumers-first → walk once, so each item's runs are computed on the merged demand of all lines and each job's materials are rounded per job → leftover BUY demand minus assets is the shopping list → schedule → fees.
- **Structure and rig bonuses come from CCP's data, not hardcoded maps** (2026-11-03). `industryModifierSources` lists, per hull and rig type, which activity and kind (material / time / cost) it modifies and, for rigs, the `industryTargetFilters` entry (category and group sets) of products it applies to. Hull values are the hull's own attributes (2600/2601/2602, Tatara 2721); rig values are the rig's bonus attributes (engineering 2594/2593/2595, reactor 2714/2713) times its security multiplier (2355–2357, missing = 1.0). All matching modifiers multiply. [SDE] This replaced the old rig-group and product-class maps, which disagreed with CCP's filters (e.g. haulers and mining barges are "Medium T1 Ships"; fuel blocks are "Structures"; reaction rigs filter on the product group).
- Decisions made in the engine:
  - Assets reduce input demand only, never a plan line's own quantity (a line means "build this").
  - A plan line is always built, even if a rule would buy its category.
  - When several blueprints make one product (fixed 2026-11-03, panel review EVE-1): published first, manufacturing before reaction, then the lowest type id; invention sources the same way, without the activity step. Before, the last one loaded won, so build 3667080's unpublished "Test Reaction Blueprint" (45732, no fuel blocks, 20 units per run) could replace the Tungsten Carbide formula (46207). The SDE has 5 such products, each with exactly one published blueprint. [SDE] Invention with several published sources (T3 relics Intact / Malfunctioning / Wrecked, Capital Hull Repairer from the T1 or a meta blueprint, condenser packs from two T1 blueprints) now takes the lowest type id (Intact relics, the T1 hull repairer); choosing by what the account owns is not done.
  - Blueprint source per blueprint: owned BPO (one job, all runs, or split with copies; see Step 6 progress) → owned BPCs (best ME first, one job each) → invention for T2 → "missing" at ME 0 / TE 0 with a warning.
  - Station: among stations offering the activity, lowest material multiplier, then the station whose jobs use the most of the product, then time, then fee rate. Copy and invention jobs pick a station too, so hull and lab-rig time bonuses apply to them.
  - Decided 2026-11-05 by the owner: "where it is used" ranks above time and fee rate. Items are planned after the jobs that use them, so those stations are already known.
    - Maelstroms, before the change: the components were built at Polite for the Azbel hull's ×0.80 time and ×0.96 cost, and then had to be carried to joe's (148,450 m³). Building at joe's added about 46 minutes and 10,600 ISK.
    - Material still ranks first, because a material bonus saves ISK on every run.
  - Decryptor `auto`: lowest invention inputs + direct T2 job materials at market price (not invention cost alone, which ignores what the ME bonus saves). With no prices it says so and takes the fewest attempts.
  - Invention chance uses the best eligible inventor's skills; attempts = ceil(BPCs / chance).
  - Schedule: dependency-aware list scheduling, longest ready job first, onto the eligible character slot that finishes it earliest. Replaces the depth-phase timeline.
- Fixed from the old calculator: bugs 1, 2, 8, 9, 10, 11 (tests in `backend/tests/engine/`). Bug 3 is a form bug; the engine takes ME override and decryptor as separate inputs, so the new UI cannot reproduce it. Invention chance changed from the old multiplicative skill formula to the additive one under Industry formulas.
- Checked against build 3667080: 10 Ishtar + 50 Hulk plans in 0.01 s (game data loads in 0.5 s); Vexor/Covetor invention base 0.26 from the SDE gives 0.671 with science 5/5, encryption 4 and Attainment, matching the formula by hand. Not yet compared with in-game job windows.
- Matched to the [client] formulas (2026-11-03):
  - Jobs on an original (owned BPO, reaction formula, or a BPO not yet owned) are split at the 30-day limit, computed without character skills, so every planned job stays valid whoever runs it. Copying and invention jobs are capped at 500 runs and 30 days. Invention copies are sized so one copy feeds one invention job. Live check: 285 Crystalline Carbonide reaction runs became 240 + 45.
  - Manufacturing time includes the required-skill bonus (attr 1982 on 26 skills, −1%/level). Job time is rounded to whole seconds.
  - Fees for every activity, split as in the client: base (EIV × runs; × 2% × runs per copy × copies for copying with the T1 product's EIV; × 2% × attempts for invention with the T2 product's EIV), then job cost (base × cost index × hull/rig cost modifiers × blueprint attr 1954, + 0.25% of base if alpha), facility tax, SCC 4% and the 5% safe-sec tax (security ≥ 0.95). Each part rounded half up to whole ISK, as Python 2 does.
- Not modelled yet (stated in reasons/warnings where they apply):
  - Facility `sccTaxModifier` and faction cost modifier: server-side values with no SDE source.
  - EIV is ME-0 materials × CCP adjusted price; science activities use the manufacturing materials. [client: `industryCommon.GetBlueprintPrice`; the server checks the client's cost against its own]
  - Implants (they feed the same character time attributes as skills).
  - Copying-activity materials in the SDE (T2 BPO copy datacores; not used for T1 invention copies).
  - Structure restrictions (e.g. which hulls a Raitaru can build); stations declare activities only.
  - Per-line cost attribution of shared components (Cost tab "per line").
- Confirmed from client code: Advanced Industry does not apply to reactions; invention consumes one T1 copy run per attempt; invention chance formula and encryption skill list. Still assumed: T1 copies for invention are made at the T1 blueprint's max runs per copy; only Generic Decryptor (group 1304) decryptors are offered.

## Known bugs to fix in the engine extraction
1. ME rounding applied per single run then multiplied — overcounts; must be applied to the whole job (`max(runs, ceil(base * runs * ME multipliers))`). `_resolve_material_tree` and `_compute_runs_needed` currently disagree.
2. T2 invented ME updates materials but not job cost, build strategy, or sub-component run counts.
3. Recalculate forms pin `me_<top_bp>` as an override, so changing decryptor afterwards doesn't change ME.
4. Config keyed by logged-in character, not account.
5. Blueprints/jobs only for the logged-in character.
6. Token refresh window (5 min) shorter than beat interval (15 min) → tokens expire between runs; web requests never refresh synchronously. Fixed in the new stack: tokens refresh on demand (see Step 2 progress).
7. `jsonify(response)` on failed SSO token exchange (`auth.py`) crashes.
8. T2 BPC base is ME 2 / TE 4 (positive, i.e. 2% fewer materials). Code uses `T2_BASE_ME = -2`, `T2_BASE_TE = -4` and adds decryptor mods (`industry.py:1609`), so invented T2 jobs are computed at ME -2: about 4% too many materials with no decryptor.
9. SCC surcharge is 4% (since Feb 2024), code uses 1.5% (`industry.py` `SCC_SURCHARGE`).
10. Job cost ignores the engineering complex cost bonus (Raitaru 3%, Azbel 4%, Sotiyo 5%; SDE attribute 2601 = 0.97/0.96/0.95) and the alpha clone tax (0.25%, alpha only).
11. M-set TE rigs (groups 1819, 1821, …, 1841) and reactor TE/L rigs (1933, 1935, 1937, 1939) are not in the rig group maps, so their bonuses are ignored.
12. ~~Security class uses raw security.~~ Not a bug. CCP's system-security guide: positive values below 0.05 display as 0.1, so `>= 0.45` high / `> 0.0` low / else null on the raw value is correct. [official: developers.eveonline.com/docs/guides/system-security]

## Groundwork findings (2026-11-03)

Tags: **[SDE]** checked against the local SDE file; **[official]** CCP page or live CCP endpoint; **[client]** decompiled game client; **[community]** EVE University wiki / EVE Ref / third-party repo; **[code]** read in this repo or the AT Tool repo; **[unverified]**.

### Game data (SDE)
- The local `src/instance/sqlite-latest.sqlite` (2025-04-29) is the old Fuzzwork layout (`invTypes`, `industryActivityMaterials`…). Since commit 6fd2cff the code queries a different schema (`EveType`, `BlueprintProduct`, `TypeDogmaAttribute`…). The app cannot run against the file on this machine. [SDE][code]
- That schema comes from maphillips1/EveOnline_StaticDataExport_Converter (C#). Its newest release is 2026-06-10; the official SDE is at build 3667080 (2026-11-03). Depending on it means stale data. [community]
- The 151 unit tests pass against a fake SDE built in `tests/conftest.py`, so they do not catch schema mismatches. [code]
- CCP publishes the SDE as JSONL (recommended) or YAML. Latest build pointer: `https://developers.eveonline.com/static-data/tranquility/latest.jsonl`; zip: `.../eve-online-static-data-latest-jsonl.zip` (redirects to a build-numbered file). Files needed: `types`, `groups`, `categories`, `marketGroups`, `blueprints`, `typeMaterials`, `typeDogma`, `mapSolarSystems`, `compressibleTypes`. Names are embedded in records. [official][community]
- **Decision: load CCP's JSONL directly into our own tables**, keyed by build number, with an import command. The AT Tool already has this (`backend/apps/sde/`: `download.py` reads `latest.jsonl`, `jsonl.py`, `loader.py`, `import_sde` command); extend it with blueprints, typeMaterials, typeDogma, mapSolarSystems, compressibleTypes. [code]
- All hardcoded group / skill / attribute IDs in `industry_constants.py` exist with the expected names in the 2025 SDE. Recheck after the JSONL import. [SDE]
- Tatara reaction time bonus is in the SDE (attribute 2721 = 0.75), not only hardcoded. [SDE] Tatara 25% reaction time, Athanor none. [community]

### ESI
- Base `https://esi.evetech.net`, no `/latest/` or `?datasource=`; send `X-Compatibility-Date` (newest date 2026-08-18). Without it ESI serves the oldest behaviour (2020-01-01). `/latest/*` still answers; no removal date announced. [official]
- Rate limits are per-group floating-window token buckets (2xx costs 2, 4xx costs 5); `X-Ratelimit-*` headers and `Retry-After` on 429. Legacy error limit still applies to unmigrated routes. [official]
- Corp routes: assets, blueprints, divisions need Director; industry jobs needs Factory_Manager (Director implies it). Assets / blueprints / corp jobs use `X-Pages`; character industry jobs is not paginated. [official]
- The AT Tool's `apps/esi/client.py` already does compatibility date, ETags, rate-limit logging and a circuit breaker. Reuse it. [code]

### SSO
- Use the metadata document `https://login.eveonline.com/.well-known/oauth-authorization-server`; validate the access token JWT offline against `jwks_uri`, character ID from `sub` (`CHARACTER:EVE:<id>`). Don't use `login.eveonline.com/oauth/verify` (not the documented endpoint). [official]
- Refresh tokens are long-lived; store the refresh token returned by every refresh. Access token lifetime ~20 min is from older docs. [official][community]
- The AT Tool's `apps/accounts/sso.py` already does PKCE + discovery + JWKS validation. Reuse it. [code]

### Industry formulas
- Job cost = EIV × (SCI × structure cost bonus + facility tax + SCC 4% [+ alpha 0.25%]); EIV = ME0 material quantities × adjusted price. SCC for ME/TE research is 2% since 2025-07-17. [community][official]
- Engineering complexes: ME 1%, TE 15/20/30%, cost 3/4/5% — matches SDE attributes 2600/2602/2601. [community][SDE]
- Rig security multipliers: high 1.0, low 1.9, null/WH 2.1. [community]
- Invention chance = base × (1 + (sci1 + sci2)/30 + encryption/40) × (1 + decryptor%). T2 BPC base ME 2 / TE 4; 10 runs modules, 1 run ships/rigs (before decryptors). Decryptor stats come from SDE attributes 1112/1113/1114/1124. [community]
- 2026 changes: unrefined mineral reactions 3600s → 360s (comes from the SDE); +5% install fees in Exordium starter space only. No slot, rig or SCC changes found through patch 24.01. [official]

**Client code (2026-11-03).** Read in the decompiled client at `G:\eve projects\src` (packages built from V24.01, compiled 2026-06-18): `industry/` (job, activities, const), `eve/common/script/util/industryCommon.py` (how server data becomes modifiers), `eveuniverse/security.py`. This is what the in-game industry window computes. Tag **[client]**. It supersedes the [community] lines above where they differ.
- Activity IDs: manufacturing 1, TE research 3, ME research 4, copying 5, invention 8, reaction 9. There is no 11. [client][SDE]
- Materials per job: `max(runs, ceil(round(base × Π material modifiers × runs, 2)))`. Modifiers are blueprint ME, hull and rigs. Matches the engine. [client]
- Time: `base time × runs × Π time modifiers`, rounded to whole seconds. Copying: `time × runs per copy × copies`. Modifiers are blueprint TE (manufacturing only), hull, rigs, character attributes (219 manufacturing, 387 copying, 1959 invention, 2662 reactions) and, for manufacturing, `1 + attr 1982 × level / 100` for each required skill that has attribute 1982 (26 skills, −1%/level: Advanced * Ship Construction, some science skills). [client][SDE]
- Character attribute sources from SDE dogma effects: Industry → 219; Advanced Industry → 219, 387, 1959, 385, 398 (not reactions); Science → 387; Reactions → 2662. Implants feed the same attributes. [SDE]
- Max runs per job: originals `ceil(30 days / (time × Π time modifiers))`, capped at 1,000,000; copies by remaining runs; copying and invention at most 500 runs. [client]
- Cost: base = `EIV per run × runs` (manufacturing, reaction); `EIV × 2% × runs per copy × copies` (copying); `EIV of the T2 product × 2% × attempts` (invention). Then, each rounded to whole ISK:
  - job cost = base × system cost index × hull and rig cost modifiers × faction modifier × blueprint attr 1954, + base × 0.25% if alpha (additive);
  - facility tax = base × tax;
  - SCC = base × 4% × the facility's `sccTaxModifier` (×0.5 for ME/TE research);
  - industry security tax = base × 5% in "safe sec" systems (security ≥ 0.95).
  EIV per blueprint is computed in the client too: Σ ME-0 material quantity × adjusted price (`industryCommon.GetBlueprintPrice`, science activities on the manufacturing materials). [client]
- Security classes on the raw value: ≤ 0 null, < 0.45 low, < 0.95 high, ≥ 0.95 safe. [client]
- Job length check: a job is refused when its total time minus one run exceeds 30 days (`job.py`, `RUN_LENGTH`). For copying, one run is one whole copy (time × licensed runs), so the number of copies per job depends on runs per copy. Licensed runs may not exceed the blueprint's max production limit. [client]
- Invention: chance = base × (1 + Σ level × 1/30 per required skill, 1/40 for skills in SDE type list 799 "LowerInventionSkillProbabilityTypes" = the seven Encryption Methods skills) × decryptor multiplier, clamped to [0, 1]. Output BPC ME 2 + decryptor, TE 4 + decryptor, runs = base + decryptor. Each attempt consumes one run of the T1 copy. [client][SDE]

### Reprocessing / compression (compressed ore calculator)
- Compression is 1:1 since patch 20.03; compressed ore reprocesses in batches of `portionSize` (100). Outputs in `typeMaterials`, raw↔compressed mapping in `compressibleTypes`. [community][SDE]
- Yield = (50 + rig) × (1 + sec) × (1 + structure) × (1 + 0.03·Reprocessing) × (1 + 0.02·Reprocessing Efficiency) × (1 + 0.02·ore skill) × (1 + implant). Rig T1 1 / T2 3; sec high 0, low 0.06, null/WH 0.12; Athanor 0.02, Tatara 0.055; implants 1/2/4%. Wiki page flagged possibly outdated. [community]
- Reprocessing rig groups 1941–1945 present. [SDE]
- **Checked 2026-11-03.** Client (`reprocessing/util.py`, `reprocessing/ui/util.py`): efficiency = min(1, station efficiency × character yield); character yield = Π (1 + level × attr 379 / 100) over the ore's processing skill, Reprocessing (3 %) and Reprocessing Efficiency (2 %), × implants; each material out = floor(quantity × batches × efficiency). [client] The ore's skill is SDE attr 790 on the ore and is now a grouped skill (Veldspar → Simple Ore Processing, 2 %/level), not one skill per ore, so the "ore skill" above is out of date. [SDE] Station efficiency is computed on the server; the SDE has rigs' `refiningYieldMultiplier` (attr 717: 0.51 T1, 0.53 T2), their security modifiers (2355–2357: 1.0 / 1.06 / 1.12) and refineries' `strRefiningYieldBonus` (attr 2722: Athanor 2, Tatara 5.5); engineering complexes have none. [SDE] The calculator combines them as the community formula does: rig multiplier × security modifier (0.50 with no rig) × (1 + hull bonus). [community, unverified against the server] M-set rigs bonus one ore class by group; L / XL "Reprocessing Monitor" rigs are assumed to cover all. [unverified]

### Janice
- API v2 (`https://janice.e-351.com/api/rest/v2/`), `X-ApiKey` header; key is requested via a ticket on their Discord. `POST /appraisal` (text/plain, `market`, `pricing`, `pricingVariant`) and `POST /pricer`. Rate limits undocumented. [official, Janice's swagger]
- Paste export format: one item per line, name + quantity (tab-separated like EVE inventory copy). Accepted formats not confirmed from a primary source; test with a real paste. [unverified]

## Backend stack

**Decided (2026-11-03): move to the AT Tool stack.** Django 5.2 + django-ninja (OpenAPI) + Postgres 16 + Redis; frontend API types generated with `openapi-typescript` / `openapi-fetch`; Python `pytest-playwright` browser tests; Docker deploy with Caddy (`deploy/` in the AT Tool). Port the AT Tool's `accounts/sso`, `esi` and `sde` apps; carry over this repo's engine and ESI fetch logic. The Flask app stayed runnable until the new stack replaced it (removed 2026-11-04).

Rejected: staying on Flask. Needs an OpenAPI add-on and a reimplementation of SSO / ESI / SDE code the AT Tool already has.

### Background work

**Decided (2026-11-03): cron for periodic work + Celery for on-demand work.** Supercronic `scheduler` container (as in the AT Tool) runs management commands for scheduled character/corp sync and SDE checks (tokens refresh on demand when a sync needs one; there is no refresh job). A Celery worker on the existing Redis runs on-demand jobs ("refresh now", first fetch after linking a character). No Celery beat; cron owns the schedule. Celery over RQ because this repo's fetch tasks (`src/tasks.py`) are already Celery tasks.

Options considered:
The AT Tool has no task queue: a `scheduler` container runs supercronic with `deploy/crontab` (hourly `refresh_affiliations`, SDE `--scan-incoming` every 5 min, `--check-latest` daily, backups). [code]

This app needs periodic work (token refresh, character + corp job / asset / blueprint sync, SDE check) and on-demand work ("refresh now", first fetch after linking a character; corp assets can be many pages). Options:
1. **Cron only, like the AT Tool**: management commands on a schedule; on-demand refresh writes a request row that a once-a-minute `sync_pending` command processes. One mechanism, up to ~1 min delay on "refresh now".
2. Cron for periodic + a task queue (Celery or RQ on the existing Redis) for on-demand. Immediate refresh, one more service and worker to run.

## Step 2 progress (2026-11-03)
Done:
- Django project in `backend/` (`manage.py`, `config/`, `apps/`), Python 3.12, own `pyproject.toml`. Dev Postgres 16 + Redis from `deploy/docker-compose.dev.yml` on ports 5434 / 6381 (the AT Tool's dev stack uses 5433 / 6380). Tests run on Postgres.
- Ported from the AT Tool: SSO (PKCE, discovery, offline JWT), ESI client (compatibility date, ETags, rate-limit logging, breaker), SDE JSONL import (zip / folder / drop folder / `--check-latest`), advisory lock, import reports.
- Not ported: team membership, roles, invites, admission rules, audit. Anyone with an EVE account can sign up.
- SDE import now keeps every type (the AT Tool kept fitting categories only) and derives blueprints (activities, materials, products with invention probability, skills) and solar systems. typeDogma, typeMaterials, compressibleTypes, industryModifierSources, industryTargetFilters, dogmaAttributes and marketGroups stay raw. Build 3667080 imports in 32 s.
- Accounts: `User` (account, main character) → `EveCharacter`. Login uses `publicData` only. "Link character" requests the industry scopes and stores an `EsiToken` (refresh and access tokens Fernet-encrypted, key from `TOKEN_ENCRYPTION_KEY` or derived from `SECRET_KEY`). Access tokens refresh on demand under a row lock when within 2 minutes of expiry; a rejected refresh marks the token so the UI can ask for a relink. A changed owner hash detaches the character and drops its token.
- ESI client: authenticated calls, ETag cache keyed by character (one character's cached response is never served to another), `X-Pages` paging.
- Scopes and routes checked against ESI's live OpenAPI spec (2026-11-03): skills, assets, blueprints, character and corp industry jobs, corp roles, corp assets, corp blueprints, divisions, structures.

- Verified live (2026-11-03): login, character linking (all 11 scopes granted), a real token refresh, and authenticated ESI calls (skills, corp roles). Dev uses the existing EVE application (callback `http://localhost:5050/callback`, served by the `/callback` route), credentials in gitignored `backend/.env`. EVE returned the same refresh token on refresh; the code stores whichever comes back.

- ESI sync (`apps/esidata`, `manage.py sync_esi --account N | --character N | --all | --public`):
  - Character feeds: skills, corp roles, assets, blueprints, industry jobs. Corp feeds: assets, blueprints, hangar divisions (need Director), industry jobs (Factory_Manager or Director). Public: `/markets/prices` (adjusted and average price) and `/industry/systems` cost indices. Response fields checked against ESI's OpenAPI spec.
  - Each corp feed uses the first linked character in that corp whose last roles fetch (from the same corp) has the role and whose token has the scope. `FeedStatus` records per owner and feed: ok/error, row count, last success, and which character supplied a corp feed. This replaces the sketch's `CorpDataSource`.
  - One feed failing (missing role or scope, rejected token, ESI error) is recorded and the rest still run.
  - Assets and blueprints are replaced per owner on each sync. Each row gets `root_location_id` (station, structure or system, after walking up through containers, ships and corp offices) and `hangar_flag` (e.g. `CorpSAG3` for an item in a container in division 3). Jobs are upserted by job id and never deleted, because ESI drops old completed jobs and the tracker needs them.
  - Corp data access: an account may read a corp feed only if one of its characters holds the feed's role in that corp (`access.readable_corp_feeds`).
  - Live run (2026-11-03, one Director in one corp): 9 feeds in 4.3 s; corp 2,887 assets, 509 blueprints, 42 jobs, 7 divisions; every asset resolved to a station or structure. Public: 16,064 prices, 32,910 cost indices in 3.8 s.
  - `/markets/prices` average price is not a buy price. The shopping list's unit price still needs a source (Janice, or ESI regional orders).

- Stations and build rules (`apps/planning`, 2026-11-03):
  - `Station` belongs to the account. Discovery (`POST /api/stations/discover`) adds every structure or NPC station where the account's characters or readable corps have industry jobs, and every structure holding their assets. NPC stations that only hold assets are reported, not added.
  - Rigs can't be discovered for structures the corp doesn't own: corp assets list a structure's rigs and service modules only for owned structures, and the live corp owns none (its D-JVGJ structures belong to an alliance corp). So rigs and facility tax are set per station; `tax_confirmed` stays false until tax is set.
  - Name, hull and system come from `/universe/structures` (needs docking access; 403 means "unresolved") or `/universe/stations` (public).
  - Default activities are the ones seen in jobs there, plus what the hull offers (engineering complex: manufacturing, copying, invention; refinery: reactions) or, for NPC stations, the `factory` / `labratory` services.
  - Live discovery: 8 structures added (Raitarus, Azbel, Tatara, Fortizars, Astrahus), 4 unresolved (no docking access), 10 asset-only NPC stations reported.
  - `BuildRules` holds account defaults (item blacklist, buy categories); plan overrides are step 3.
- Plan input (`apps/planning/inputs.py`) and `POST /api/plan/preview` run the engine on the account's real data:
  - Inputs: SDE game data, enabled stations, linked characters' skills, owned blueprints and assets of characters and readable corps, CCP adjusted and average prices, cost indices, build rules.
  - Available assets: at the plan's stations, in a personal hangar, corp division or deliveries, and not assembled.
  - Live: 10 Ishtar + 50 Hulk in 1.5 s (102 jobs).
  - Open: every character is treated as omega and allowed every activity until per-character settings exist; `unit_price` is CCP's average price until a buy-price source exists.

- Sync scheduling (2026-11-03), as decided under Background work:
  - Cron (`deploy/crontab`, supercronic in the `scheduler` container):
    - industry jobs every 10 min (`sync_esi --all --feeds jobs`; roles are read too, because corp feed sources depend on them);
    - everything else hourly;
    - public prices and cost indices hourly;
    - SDE drop folder every 5 min, CCP's latest build daily, `clearsessions` hourly.
    - Intervals follow ESI's cache times read from live headers: jobs 5 min; assets, blueprints, roles, divisions, prices and cost indices 1 h; skills 60 s.
    - Each `sync_esi` mode takes its own Postgres advisory lock, so a slow run is skipped by the next tick of the same line, not doubled.
  - Celery (`worker` container, Redis DB 1, no beat, results not stored):
    - `POST /api/sync` queues a full sync for the account; a second request within 10 minutes, or while one is running, is refused (`queued: false`). Linking a character queues one after the transaction commits; a broker outage logs and does not fail the link. `GET /api/sync/status` lists each feed's last attempt, success, row count, error and supplying character.
    - Live: queued from the API and run by a real worker, 9 feeds in 2.6 s.
  - Deploy: `deploy/Dockerfile.backend` (from the AT Tool's, with supercronic checksum-pinned), `deploy/entrypoint.sh` (web / worker / scheduler), `deploy/docker-compose.yml` (web, worker, scheduler, Postgres 16, Redis). Image builds, `manage.py check` passes under prod settings, and supercronic validates the crontab. Redis uses `volatile-lru`, so only TTL'd cache keys are evicted, never queued tasks. Caddy and the frontend come with step 4; until then `web` listens on 127.0.0.1:8000. No backup job yet (the AT Tool's `backup.sh` was not ported).

Step 2 is done apart from per-character settings (alpha clone, allowed activities) and a buy-price source.

## Step 3 progress (2026-11-03)
- `Plan` (`apps/planning`):
  - Fields: name, lines (`PlanLine`: type, quantity, position), `is_active` + `activated_at` (one active plan per account, enforced by a partial unique constraint), `reserve_assets`, `priority`, `visibility` (stored; enforced in step 7).
  - Rule overrides: `blacklist_add` / `blacklist_remove` (type ids) and `category_overrides` ({BuildCategory: "buy" | "build"}) applied on top of the account's `BuildRules`.
  - `choices` per blueprint: ME / TE override, decryptor.
  - Asset scope: `station_ids` (empty: every enabled station), `extra_location_ids`, `hangar_flags` (empty: all hangars).
- API:
  - `GET/POST /api/plans`, `GET/PATCH/DELETE /api/plans/{id}`, `PUT /api/plans/{id}/lines`, `POST /api/plans/{id}/activate | deactivate`.
  - `GET /api/plans/{id}/result` returns the engine result, the effective rules with the plan's overrides, this plan's claims, and `held_elsewhere` ({type: [{plan, quantity}]}: stock in this plan's scope held by earlier reserving plans). Plans are private to the account.
- Reservation: see Asset reservation (computed in priority order, per item / location / hangar).
- Live (2026-11-03): "indy 1" (10 Ishtar + 50 Hulk, priority 1) and "dreadbatch 1" (1 Phoenix, 2 Naglfar, 1 Revelation Navy Issue, priority 2), both reserving. indy 1 claims 16 items (e.g. all 3.67M Mexallon at the D-JVGJ structures); dreadbatch 1 sees them held by indy 1 and claims 50 others. Result in 1.3 s.
- Not done: results are recomputed on every request (no cache); rule overrides are not yet shown per item in the result (the engine's reason says "rule: <category>" but not whether the plan overrode it; the response lists the overrides beside it).

## Step 4 progress (2026-11-03)
- `frontend/`: React 19 + TypeScript + Vite 6, Tailwind v4 tokens, TanStack Router + Query, `openapi-fetch` with types generated from the backend's OpenAPI schema (`npm run gen:api`). Base ported from the AT Tool (tokens, primitives, toasts, hooks, shell), with font sizes moved to tokens (`text-label` / `text-ui` / `text-body` / `text-title`) as `docs/ui-design.md` asks. New primitives: `Tabs`, `Why` (a derived value's reason), `SearchPicker` (type-ahead for long lists), `Num` (right-aligned monospace cell).
- Backend for the frontend: plan result and preview responses are typed from the engine's dataclasses (pydantic reads them directly, so the TypeScript types cover the whole result without duplicate schemas). Lookups: `GET /api/types/search?kind=buildable|structure|rig|any`, `GET /api/types?ids=`, `GET /api/systems/search`.
- Dev ports: Django on 127.0.0.1:8000; Vite serves the app on localhost:5050 and proxies `/api`, `/auth`, `/callback`, because 5050 is the EVE application's registered callback.
- Pages:
  - Plans list (create, active / reserving badges, priority).
  - Plan view: inline rename, make active, delete. Tabs: Shopping list (with "held by plan X", copy as multibuy), Blueprints (source, ME/TE and station, each with its reason; invention chance and decryptor), Schedule (start, duration, character, station), Cost (totals and per-job fee parts), Progress (placeholder until step 5). Side column: lines editor with item search, settings (reserve, priority, stations, hangars, per-plan rule overrides), warnings.
  - Setup: characters and ESI status (link, re-link, main, remove), ESI feed status with "refresh now", stations (discover, enable, activities, rigs via search, tax), account build rules.
- Checked: `tsc`, `eslint` and the production build are clean; Vite compiles every module; the API answers through the Vite proxy with a real session (indy 1 result: 102 jobs in 1.3 s); login redirects to the registered callback. Not checked: rendering in a browser. Headless Chromium in this WSL distro lacks system libraries (`libatk` and others), and the Chrome extension was not connected.
- Dashboard (home page) and Library (2026-11-03):
  - "Library" was not defined in this doc. Taken to mean every blueprint the account's characters and readable corps hold (BPO / BPC / stack of unresearched originals, ME / TE, runs, owner, structure, corp division name), with search, kind and location filters and sortable columns. `GET /api/library/blueprints`.
  - Dashboard: open jobs (characters' and readable corps', ready first, then by end time, delivered in the last day last), slots per character, finishing within 24 h, the active plan, and problems (ESI access, failing feeds, one line per station with missing tax / rigs / activities). `GET /api/dashboard`.
  - Job state: an installed job past its end date shows as "ready", as the client does (`industryCommon.JobStatus`); ESI's status lags until the next sync. [client]
  - Slots: running jobs (active or paused) against slots from skills; ready-but-undelivered jobs are shown apart. The owner's rule (2026-11-04): a ready job frees its slot, and corp jobs take the installer's slot; plans use the same rule (see Panel review follow-up). Idle reaction slots are not flagged.
  - Names: corpmates and NPC stations via ESI `/universe/names` (cached a day; structure ids are not accepted there, so structures are named from the account's stations).
- Inputs that save on change (checkboxes, selects) keep a local copy (`useLocalCopy`) so they change within the click and follow the server afterwards; station and build-rule saves are also optimistic with rollback. Found by the browser tests: with the server value alone, a click snapped back until the refetch.
- Playwright (`backend/playwright_tests`, AT Tool pattern): 14 specs against the running dev servers. They cover signed-out state, navigation and titles, theme persistence, the no-ESI flag, adding a station by hand with system and hull search, rigs / tax / activities, build rules, creating a plan and editing lines, the reasons shown in every tab, the no-station warning, switching the active plan, rule overrides, settings toggles, and delete confirmation. Reserved character ids 900000001-900000099; `playwright_cleanup` wipes them (unit-tested to stay inside the range). Stable over three consecutive runs (~12 s each).

Step 4 is done apart from per-plan sharing views (step 7).

## Step 5 progress (2026-11-03)
- Engine: `PlanInput.started` (units by item) and `started_attempts` (invention attempts by T2 blueprint). `ItemPlan.started` / `over_plan` and `InventionPlan.attempts_in_progress` report them.
- `apps/planning/tracker.py`: `match()` links new jobs to the active plan. It runs after every sync that reads jobs (cron and Celery) and when the Progress tab loads. Unlinked jobs keep a link row with no plan and are never matched again. `progress_inputs()` builds the engine inputs, and every plan run (reservations included) uses them.
- API: `GET /api/plans/{id}/progress` returns, per blueprint and activity, runs to start / running / ready / delivered and units over plan. It also returns the linked jobs and the unlinked jobs of the last 30 days for these blueprints. `POST` / `DELETE /api/plans/{id}/jobs/{job_id}` link and unlink by hand.
- Frontend: a Progress tab with one bar per blueprint (delivered / ready / running / to start), the linked jobs with Unlink, and the other recent jobs with Link. The dashboard's active-plan panel shows the totals.
- Live (dreadbatch 1): 27 blueprint rows; 30 corp jobs (a corpmate's capital components started before activation) offered to link by hand. Progress response ~2 s.
- Tests: 14 unit tests (matching rules, progress inputs, engine effect, API) and 5 browser specs: auto link, unlink then link, jobs from before activation, inactive plan, over plan. Test jobs come from `manage.py playwright_job`, which only accepts reserved test ids.
- Found by the browser tests: the plan result cached from other tabs went stale after matching on the Progress tab. It is now refreshed whenever the linked jobs change.
- Not done: copy jobs reducing planned copies; progress caching (each call recomputes).

## Step 6 progress (2026-11-03)
- Scheduler: jobs carry the blueprint item they are installed with, and jobs on the same item never overlap. Before this, the 30-day chunks of one BPO (e.g. 285 Crystalline Carbonide runs as 240 + 45), a missing blueprint's chunks, and T1 copying for invention alongside T1 manufacturing were all scheduled in parallel, so finish times were too short.
- Invention copy jobs: copies per job are now capped using the time of a whole copy (runs per copy), per the client's length check. The old cap used one licensed run.
- Auto-copy (`engine/planner.py`, `_search_parallel`): candidates are owned BPOs with a copying activity and at least 2 runs, when the characters have 2+ manufacturing slots in total. For k parallel jobs, copies get ceil(runs / k) runs (at most the max production limit) and the BPO keeps the rest; the copy job runs first on the BPO and every job of the blueprint waits for it. Greedy search, longest blueprint first: try k = 2, 3, … up to runs and total slots, stop after two tries that do not beat the best, keep the best if it saves at least `MIN_SPLIT_GAIN` (1 hour); up to 3 passes. Options are compared by re-scheduling the base plan's jobs only; the chosen splits are then planned again in full so materials are exact, and that result is used only if it really finishes sooner. Each split blueprint's reason gives the time saved (the plan without that one split), the extra materials from per-job rounding, and the copy job fee. New source `copy` and reason code `source_copy`.
- Live (dreadbatch 1, one character with 11 manufacturing slots): the Phoenix BPO is split 3 ways while its capital components build; the plan finishes in 29.5 days instead of 35.7, for a 2.66M copy fee and 2 more units of materials (131k ISK). indy 1: no split helps (73.5 days either way). Engine time with the search: dreadbatch 1 ~170 ms (was ~30), indy 1 ~70 ms.
- Known limits: greedy search can miss gains that need two blueprints split together; copies always get equal runs; with several owned BPOs only the best is used.
- Owned BPCs next to an owned BPO (fixed 2026-11-03): BPCs are used first (best ME first, one job each) when their ME is at least the BPO's; the BPO takes the remaining runs and is the auto-copy candidate. Lower-ME BPCs stay unused, with a note. Before, every BPC was ignored once a BPO was owned. Live: 45 Maelstroms went from 17.6 days with 8 planned copies (3.6M fee) to 4.4 days with no copies, because the 11 Maelstrom BPCs and 13 Auto-Integrity Preservation Seal BPCs are now used.
- **BPC lines (decided 2026-11-03):** a plan line can pick owned BPCs ("run these five 9-run BPCs"). `PlanLine.blueprint_item_ids`; the API checks they are copies the account holds, of one blueprint that makes the line's item, not picked twice, and not in another plan (409), and sets the line quantity from their runs. The engine uses picked BPCs first, in the order picked, even below the BPO's ME. A picked BPC belongs to its plan: `reservation.plan_input` removes it from every other plan's blueprints, and the Library rows show which plan holds it. UI: "Pick BPCs" in the plan's Build panel (copies of one blueprint at a time); the line's quantity is read-only. Rejected: a per-blueprint "use these BPCs" choice on an item line, because the user would still have to compute the quantity and the two could disagree.
- Adding an item already in the plan from the search box raises that line's quantity by one (existing behaviour, kept); it never changes a BPC line.
- Splitting runs across jobs costs at most one unit per material per extra job (each job's materials are rounded up separately; the per-run floor of 1 unit applies either way). Checked on the Maelstrom recipe: 1 × 40 vs 2 × 20 runs at ME 10 differ by 0–1 unit of a few materials.
- **Blueprints in jobs (fixed 2026-11-03):** a blueprint installed in an open job (active, paused, or past its end and not delivered) is not in its hangar. ESI's blueprints feed still lists it at its old location (seen live: the Maelstrom BPO in a finished copy job showed as in Starch Man's hangar, and the assets feed had no row for it). `apps/esidata/jobs.py` `blueprint_jobs` maps each open job to its blueprint item (`IndustryJob.blueprint_id`). The engine gets `OwnedBlueprint.job_activity_id` / `job_ends_in`: BPCs in jobs are not used (their runs are being consumed; how ESI reports a BPC's remaining runs during a job is not verified), and a BPO's lock starts when its job ends, with a note to deliver it if the job has finished. Paused jobs use their stored end date. The Library shows "in copying job · finished, deliver it" or the time left; the BPC picker leaves out BPCs in jobs. Live: 23 of the account's blueprints were in open jobs and had been treated as free.
- **Copies being made (done 2026-11-03):** each open copy job becomes `runs` incoming BPCs of `licensed_runs` runs at the original's ME / TE (`inputs.incoming_copies`; made-up negative item ids), usable when the job ends; a finished job's copies carry a "deliver it first" note. They go to the plan the job is linked to, or to every plan when the job is linked to none (including unlinked by hand), the same way picked BPCs belong to one plan. Delivered copies arrive through the blueprint sync as before. The tracker's base run leaves them out, so a new copy job still finds a copying step to match. Rejected: feeding copy jobs as tracker progress, because copies are blueprints, not items, and the blueprint path already handles them once delivered.
- Invention now uses T1 BPCs on hand and copies being made, one invention job per copy, before planning copy jobs. Before, owning the T1 BPO meant every attempt got a planned copy, even with T1 BPCs in the hangar.
- Live: the Maelstrom BPO's finished copy job makes 10 copies of 10 runs; a 120-Maelstrom plan now uses the 11 BPCs plus 3 of those copies and no BPO runs.
- **Opt-in purchases (done 2026-11-03):** `BlueprintChoice` gains `buy_bpcs`, `bpc_runs` (default: max production limit), `bpc_me` / `bpc_te` (default 10 / 20), `bpc_price` (yours to set: BPCs sell on contracts, no market price), `extra_bpos`, `bpo_me` / `bpo_te` (default 0 / 0, a fresh BPO is unresearched). Bought BPCs are used after picked ones, before other owned BPCs; extra BPOs share the runs left evenly with the owned BPO (which takes the larger share). Source `bought`. An extra BPO goes on the shopping list at CCP's average price (blueprints have one: Maelstrom Blueprint 1.45B); bought BPCs only count in `CostSummary.blueprints`, with a warning while their price is not set. `engine.purchase_options` works out, per blueprint and on request (`GET /api/plans/{id}/blueprints/{bp}/options`), the best number of BPCs to buy and one extra BPO (not for invented blueprints), each by running the whole plan again: time saved from the scheduler, cost change from the plan's own totals, purchase price. The Blueprints tab's "Buy options" shows them with a per-BPC price box, "Buy" saves the choice, "Stop buying" clears it.
- **Spreading runs over owned BPCs (done 2026-11-03):** BPCs used to be filled one at a time, so a blueprint with 21 BPCs used 4 and left slots idle (reported live: the maelstroms plan, 11 slots, 56.9 h). The split search now also tries spreading a blueprint's runs over more of its owned BPCs (not picked ones), runs shared evenly (`_water_fill`). A change is kept when the plan finishes an hour sooner, or when the blueprint's own jobs do without delaying the plan (two blueprints that end together only shorten the plan when both spread); a final pass drops any setting whose removal costs the plan under an hour. Live: maelstroms 56.9 h → 19.3 h (seals and Life Support units over 11 BPCs each, Maelstroms over 7).
- BPC order among equals now prefers BPCs in the hangar over copies a finished, undelivered copy job holds (a negative "available in" sorted first before).
- Scheduler: ready jobs and their no-skill durations are tracked incrementally instead of recomputed every step (same order and results). dreadbatch 1 plans in ~0.5 s with the wider search (1.5 s before this change).
- Not done: copies attributed to a plan lose that attribution once delivered (they become ordinary owned BPCs); a picked BPC that disappears (consumed by a job, sold, moved out of the account) is silently skipped, with no warning.

## Step 7 progress (2026-11-03)
- `Plan.share_token` (link secret; "New link" replaces it and the old link stops working) and `Plan.share_corporation_id` (None: the owner's main's corp). Turning on link visibility makes a token.
- `apps/planning/sharing.py`: who may view, and the read-only payload. Corp access re-checks the viewer's characters against ESI's public affiliation when the stored one is older than 24 h, so someone who left the corp loses access within a day. Every viewer gets the lines, the engine result (shopping list, schedule, costs) and progress, computed from the owner's data; only the stations and characters the plan uses are listed. Never: reservation details, jobs offered for linking, buy options, settings. Link payloads replace every owner station, character and structure name in all text and remap their ids (character ids resolve to names through ESI); used stations are numbered first so the numbers do not hint at how many the owner has. Payloads are cached 60 s per plan and kind, keyed by the plan's last edit.
- API: `GET /api/shared/{token}` (no login), `GET /api/plans/{id}/view` (corp members, and the owner as a preview; anyone else gets 404), `GET /api/plans/shared-with-me`, `GET /api/plans/corporations`, `POST /api/plans/{id}/share-link`. Fixed paths are declared before `/plans/{plan_id}`: ninja matches the path before checking that the id is a number.
- Frontend: Sharing panel on the plan page (visibility, corporation, link with Copy and New link, Preview); `/shared/<token>` opens without login; `/plans/<id>/view` is the read-only page (Shopping list, Schedule, Progress tabs, no actions); Plans page lists "Shared with me".
- Live check (maelstroms plan, link payload built in memory, not shared): no station, structure, character or owner name and no character id in the payload; the plan's 2 stations show as Station 1 and 2.
- Tests: 7 API tests (link aliases and revocation, corp access, other corps, the 24 h re-check, corp validation, the cache) and 2 browser tests (link view in a logged-out browser, corp member finds and opens the plan; another corp gets nothing). Browser test characters can be put in a made-up corp: `login(corp=...)`.

## Step 8 progress (2026-11-03)
- Janice export: the Shopping list's "Copy list" (name, tab, quantity per line) exists since step 4. Whether Janice and EVE multibuy accept it is still to be checked with a real paste.
- Compressed ore calculator, done:
  - `engine/reprocess.py` (pure): yields as above, and the cheapest mix of whole batches that covers every needed mineral. A linear solve (scipy HiGHS `linprog`) rounded up per ore for mixes over 1,000 batches (at most one batch per ore over the cheapest), an integer solve (`milp`) for smaller ones; floor losses are made up by raising the short mineral's target and solving again. Rejected: exact integer solving everywhere (2 s per solve on dreadbatch 1, for a difference below one batch per ore). scipy is now a backend dependency.
  - `apps/sde/gamedata.py`: compressed ores from `compressibleTypes` + `typeMaterials` + attr 790 (186: 114 asteroid, 60 moon, 12 ice), skill bonuses (attr 379), refinery rigs and hull bonuses. The Setup rig search now finds reprocessing rigs (groups 1941–1945).
  - `GET /api/plans/{id}/compressed-ore?station_id&character_id&ore_classes`: the minerals on the plan's shopping list; default station the best asteroid-ore yield, default character the cheapest mix. Ore and minerals are both priced at CCP average price.
  - UI: "Minerals as compressed ore" under the Shopping list (owner only): station, character, ore classes; ore and mineral tables; ore cost vs buying minerals; "Copy ore" and "Copy list with ore" (the shopping list with the covered minerals replaced by ore).
  - Live: no reprocessing rig is recorded on the account's Tatara, so its yield is 52.8 % station × 1.39 skills = 73.4 %; at that yield ore costs ~7 % more than minerals on both plans. Warm request time is about that of the plan result (dreadbatch 1 ~1 s).
- Volumes (2026-11-03): `ItemType.volume` is the SDE packaged volume (what a market purchase hauls: a Rifter is 2,500 m3 packaged, 27,289 assembled). Shopping list rows, extra BPOs, ore lines and needed minerals carry m3; the Shopping list shows a total, the ore panel shows ore vs minerals and the whole list with ore. Live: dreadbatch 1's list is 224k m3, 77k m3 with its minerals as ore; maelstroms 2.32M m3, 185k m3 with ore.
- **Jita prices and stock (done 2026-11-04):** `apps/esidata/market.py` reads `GET /markets/10000002/orders?order_type=sell&type_id=` (public; 5-minute ESI cache; 2 tokens of the `market-order` group's 12,000 per 15 minutes [official: live OpenAPI spec and response headers]) for each ore that yields a needed mineral and each needed mineral, 8 in parallel, keeps orders at Jita 4-4 (station 60003760 [official: ESI]) cheapest first, and caches each for 5 minutes. The engine buys through each order book as price tiers capped by the units on sale, so large buys pay the deeper orders and cannot exceed what is listed; minerals bought directly are priced the same way. Items with no orders are left out; items whose fetch failed use the CCP average, and the response says how many. Order minimum quantities are ignored. The panel has a Jita / CCP average switch and shows average paid, dearest order and units on sale.
- Live (2026-11-04): Jita turns both comparisons around from the CCP-average ones: dreadbatch 1 ore 850M vs minerals 831M (minerals 2% cheaper), maelstroms ore 2.69B vs minerals 2.76B (ore 2.5% cheaper). A cold request fetched about 120 order books (~2.6 s); warm requests take what the plan takes.
- **Jita prices for the whole plan (done 2026-11-04):** `engine/pricing.py` `reprice` takes a finished result and prices every shopping item through its Jita 4-4 order book (average paid, units on sale; not enough on sale: the rest at the dearest order, with a warning; nothing on sale or not fetched: the CCP average, marked), then recomputes materials, invention inputs, extra BPOs and the total. Job fees are unchanged (EIV uses CCP's adjusted price, as in the game). The planner itself still prices with the average; its only price-driven choice is the automatic decryptor, and buy options' cost changes also use the average. `GET /api/plans/{id}/result` prices from Jita unless `prices=average`; shared views always use Jita. The plan page has a Jita / CCP average switch, remembered per browser. Live: dreadbatch 1 total 1.77B → 1.92B, maelstroms 2.87B → 3.16B; every item was on sale in full.
- Fixed with it: plan edits (settings, choices, lines) are now sent one at a time in order (TanStack Query mutation scope); two quick edits could reach the threaded server together and leave the older value saved. The settings browser test waited on a toast an earlier save had already shown; it now waits for each PATCH response. It failed about one run in six before.
- Not done: implants (not synced; the engine takes a percentage), by-products counted as value.

## Deployment (2026-11-04)
- The Flask app is removed; the new stack is the only one. CI (`.github/workflows/test.yml`) runs backend lint and tests against a Postgres service and the frontend type check, lint and build; browser tests stay local (they need both dev servers and the SDE).
- `deploy/docker-compose.yml` gained the frontend: `deploy/Dockerfile.frontend` builds it and serves it from Caddy, which proxies `/api`, `/auth`, `/callback`, `/admin`, `/static` to `web` and gets the certificate (`deploy/Caddyfile`, from the AT Tool). `ACME_EMAIL` is required; compose stops with a message without it.
- Only `web` builds the backend image; `worker` and `scheduler` use it. All three building it at once failed with containerd "parent snapshot does not exist".
- Checked locally with throwaway settings (project `eveindy-prodtest`, ports 8081 / 8444, removed afterwards), starting with no backend image: migrations, health, the app and SPA deep links, the SSO redirect with the https callback, dev-login 404, admin and static files, http → https, the worker and scheduler starting, and `sync_esi --public` from the container (16k prices, 33k cost indices). Not checked: a real SSO login (needs a registered domain callback) and the SDE import (a large download).
- Decided (2026-11-04): the app runs on localhost for the user only; no server deploy for now. The production stack stays ready.
- So that it stays synced on localhost, `deploy/docker-compose.dev.yml` also runs the worker and the scheduler: the backend image with `backend/` mounted over `/app` (the image's virtualenv moved to `/opt/venv` for this), dev settings, your user id. The worker runs under `watchfiles` and restarts when backend Python changes. Checked: a sync queued from runserver's side was run by the container worker (19 feeds, all ok, tokens decrypt), a crontab job ran in the scheduler, the worker restarted on a file change, and the production image still starts uvicorn, Celery and supercronic from `/opt/venv`.
- Never create `deploy/.env` on a dev machine: the dev backend reads it too (`config/settings/base.py`), and its production `EVE_CALLBACK_URL` would break dev login.

## Build order
0. **Engine types** — input/output dataclasses, including a reason on each decision. Done.
1. **Engine** — extract from `industry.py:get_calculator`, multi-line plans, build rules (item blacklist + tier switches), fix bugs 1–3 and 8–12, tests. Done; see Planning engine. Pure Python, independent of the backend stack decision. Track C (compressed ore + Janice export) runs alongside in a worktree.
2. **Account + data layer** — account-scoped config, all-character + corp fetches (assets, blueprints, jobs, divisions), role detection, token fix, Postgres. In progress; see Step 2 progress.
3. **Plans** — model + JSON API, asset reservation. Done; see Step 3 progress.
4. **React frontend** — Plans list, Plan view (tabs), Setup, Library, Dashboard. Done; see Step 4 progress.
5. **Tracker** — active-plan job matching, progress tab, reservation release. Done; see Step 5 progress.
6. **BPO/BPC trade-off** — auto-copy to fill slots, opt-in buy BPC / extra BPO with cost vs time shown.
7. **Sharing** — corp/link visibility. Done; see Step 7 progress.
8. **Janice export**, then **compressed ore calculator**. Calculator done; see Step 8 progress.

## Decisions (from review, 2026-11-03)
- No plan deadlines.
- One active plan; tracker attributes new jobs to it.
- Build rules (item blacklist + tier switches incl. reaction levels) as account defaults with per-plan overrides.
- BPO vs BPC: auto-copy to fill idle mfg slots; buying BPCs / extra BPOs is opt-in per blueprint with cost vs time shown.
- Corp roles: all my characters are Directors, so corp assets, blueprints, jobs and divisions come straight from ESI; paste fallback is deferred.

## Decisions (panel review, 2026-11-03)
Review in `docs/reviews/2026-11-03-panel-review/` (report, brief, seven reviewers' findings).
- **Invention with characters of different skill (D2):** invention jobs are pinned to the characters whose chance the attempts were computed from, and the reason says so. Rejected: computing attempts per scheduled character (a second planning pass). Attempts stay the expected value `ceil(bpcs / chance)`; a confidence margin is not planned.
- **Deployment model (D3):** other users run their own deploy (self-hosted, like Wanderer), not a shared site. So the production stack must be safe for someone else to run as is; hardening for many accounts on one instance is not a goal.
- **Token key and backups (D4):** set an explicit `TOKEN_ENCRYPTION_KEY` and a random `SECRET_KEY` in `backend/.env`, re-encrypt the stored tokens from the derived key with a one-off script, and back up the dev database together with `backend/.env`. Rejected: re-linking the characters instead of the script; accepting the derived key.
- **Mechanics questions (D1), checked against the client and SDE instead of in game:**
  - Rig security multiplier on cost: settled. Every type with the engineering rig cost bonus (attr 2595, 111 types) has effect 6842 `structureEngineeringRigSecurityModification`, which multiplies 2593 / 2594 / 2595 by `securityModifier` (2358); reactor rigs have 6976 for 2713 / 2714. 2358 resolves to attr 2355 / 2356 / 2357 by system security (`dogma/attributes/securityModifierAttribute.py`). The engine's `station_bonuses` already applies it to cost. [SDE build 3667080][client]
  - Upwell conversion rigs carry attr 2594 without effect 6842 (their effects are 7098–7110), so the security multiplier should not apply to them; relevant to EVE-3 in the review. [SDE]
  - Slots: `industrySvc._UpdateSlots` asks the server `GetJobCounts(session.charid)` per character and refreshes on any job whose `installerID` is the character, whoever owns it. So corp jobs very likely count against the installer's slots; the count itself is server-side. Whether a ready, undelivered job holds a slot is not in client code. [client]
  - Whether an item keeps its `item_id` when moved between a personal and a corp hangar is server-side; not in client code.

## Panel review follow-up (2026-11-04)
What changed from the review (`docs/reviews/2026-11-03-panel-review/`; item ids N/X/L from its report).
- **Engine**
  - Producers: published blueprints first, then manufacturing before reaction, then the lowest type id (N1; see Planning engine).
  - Invention jobs run only on the characters whose chance the attempts use (X3, decision D2).
  - Jobs on copies are split at the 30-day limit too, on the same item one after another (L6). T3 from relics is planned as a missing blueprint with a warning (L7).
  - `PlannedJob.blueprint_item_id`: the owned blueprint a job is installed with (X6).
  - **Busy slots (X2, decided 2026-11-04 by the owner):** a character's slots start occupied by its running jobs (active, or paused until the stored end), corp jobs included for the character who installed them, ME/TE research in science slots. A job past its end and not delivered frees its slot. Live: maelstroms 0.82 → 1.06 days with the account's 5 running manufacturing jobs.
  - Rig bonuses come from each rig's dogma effects: which rig attribute feeds which structure attribute, and whether its security effect scales it (L5). Thukker rigs use attr 2653 (security 0.1 / 1.9 / 0.1), Upwell outpost rigs are not security-scaled. Needs `dogmaEffects` in the SDE import (added; an older import falls back to 2593/2594/2595 and 2713/2714).
  - The compressed ore mix pays the station's reprocessing tax: round(adjusted price × recovered × tax, 2) per material, as the client charges it (L8). `Station.reprocessing_tax`, set in Setup.
- **Pricing (X4/L1):** with Jita prices, the requested plan runs a second time with Jita unit prices (`engine.pricing.market_prices`; datacores and decryptors are looked up too), then `reprice` prices the shopping list through the order books. The automatic decryptor and ISK in reasons now use the prices the list shows. Buy options use the same priced input. Cost: about +0.45 s on dreadbatch 1. The engine's "no price" warning is replaced by an up-to-date one. Since 2026-11-07 the second run happens only when the first result has invention or copy jobs, the only results prices can change (decryptor choice; the ISK quoted for an auto-copy split's extra materials); other plans are only repriced, which on the dev plans gave identical results. Dreadbatch 1: the Jita step went from ~290 ms to ~1 ms. The planner also builds its adjusted-price map once instead of once per job (16.8k entries, 78 jobs on dreadbatch 1).
- **Reservation (X6):** reserving plans also take BPC runs, in priority order; later plans see what is left on each copy. A BPO two reserving plans schedule is flagged, not divided. When only reserving plans are asked for, the ones after the last of them are not run.
- **Data health (N5):** one function (`esidata.freshness`) reports per owner and feed whether the last sync failed or is older than about three sync intervals (jobs 30 min, the rest 3 h). The plan header shows "data N ago" and the problems; the dashboard uses the same rules. A finished "Refresh now" refetches plans, library and dashboard.
- **Sync (N3, N4, L12):** snapshot writes (assets, blueprints, skills, divisions) take a per-owner advisory lock, and assets and blueprints are unique per owner and item id. An SSO error during refresh is a failed feed (`TokenRefreshFailed`), not an aborted run; only `invalid_grant` / `invalid_token` mark a token rejected. Paged fetches must come from one snapshot (`Last-Modified`): one retry, then the feed fails. Token validation allows 60 s of clock skew (a Docker Desktop VM clock behind CCP's made fresh tokens "not yet valid").
- **Security (N8, N9, D3, D4):** dev Postgres and Redis on 127.0.0.1; dev-login only for ids 900000001–900000099 (`DEV_LOGIN_CHARACTER_IDS`); corp access needs a working token; Caddy no longer proxies `/admin`; uvicorn trusts forwarded headers from private networks only. `manage.py rekey_tokens` re-encrypts tokens after setting `TOKEN_ENCRYPTION_KEY`, and `deploy/backup-dev.sh` (`make backup`) dumps the dev database with `backend/.env`. Done 2026-11-04: generated keys in `backend/.env`, 3 tokens re-encrypted (the derived key no longer decrypts them), worker and scheduler restarted, a sync and the worker both read the tokens, backups before and after.
- **Frontend:** Items tab (decision, why, made / left over, per-plan buy or build), ME / TE / decryptor overrides on the Blueprints tab, the plan tab in the URL, line and choice edits that do not undo each other, copy buttons disabled while the plan recomputes, the ore panel priced by the header's switch, owner names and failing feeds on Setup.
- **Code:** the unused `/api/plan/preview` is gone; `inputs` assembles a plan's input (`load`, `plan_input`) and `progress` builds progress, so `tracker` no longer imports `reservation`.
- **Tests:** result invariants on every planner test (`tests/engine/invariants.py`); golden tests on real SDE records through the real importer (`tests/golden/`, `extract.py` refreshes the fixture from CCP's zip); CI checks the frontend's API types against the schema (`make api-check`).
- **Dev tooling:** root `Makefile` (`make help`). After a Docker Desktop restart, containers can keep stale bind mounts (`stat /app/deploy/entrypoint.sh: no such file`, or Celery's "module config was not found"): `make services-recreate`.

**Left for later (owner, 2026-11-05):**
- L2: move `_choose_sources` out of `plan_blueprint`, with unit tests, before the next blueprint-source rule.
- L15: release the `edit` mutation queue once the PATCH returns.
- Warn when a picked BPC disappears instead of skipping it silently.
- Some POS structures list themselves as their own material in the SDE: not investigated.
- Waiting on the owner: X7 (the item_id check below), L14 (User-Agent contact), and how a self-hosted copy limits signup (L19).

## Open questions
- Exact list of tier/category build switches.
- In game: does an item keep its `item_id` when moved whole from a personal to a corp hangar (decides whether the same item can be counted in both snapshots, review DATA-2).
