# EVE Indy App — Redesign

Status: draft, agreed direction (2026-11-03). Source of truth for the rewrite; update it when decisions change.

## Goal

Answer one question well, for me and anyone with the same use case:

> I have these characters, these skills, these stations, and these assets (personal **and corp**).
> I want to build these things. What's the plan — and where are we on it?

The app becomes **plan-centric**. Today it is tool-centric (Calculator / Invention / Production pages that each half-answer the question and disagree with each other).

## Users and use case

- Knows what they want to build; does not need a "what's profitable" scanner (may come later).
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

- The real constraint is **slots**, not dates. Copying is cheap (small job fee, uses lab slots); it exists to run more manufacturing jobs in parallel.
- **Default: copy to fill idle manufacturing slots.** If one BPO would leave mfg slots idle, plan enough copies to use them. This is close to free speed, so it's automatic.
- **Buying BPCs and extra BPOs cost real ISK**, so they're never automatic. Per blueprint, show the trade-off: "buy 3 BPCs (~15M) → finishes ~2 days sooner" / "extra BPO (~80M) → saves ~1 day per batch, reusable". You opt in.
- No plan-level "cheapest vs fastest" preference for now; the per-blueprint choice is enough. Revisit if it gets tedious on big plans.

### Asset reservation
- Plans with **Reserve assets** checked claim matching assets from the pool in **priority order**.
- Non-reserving plans see only what's left over (and show "X reserved by plan Y").
- Reservations shrink as the plan consumes materials (job started → inputs are gone from assets, so the reservation for them must be released, not double-counted). The tracker drives this.
- Location filter per plan: default = assets at the plan's build stations; user can tick other locations/hangars.

### Job tracking
- Usually one plan is in progress at a time, so matching is simple: **one plan is marked active**, and any new ESI job (character or corp) started after activation whose blueprint + activity is in the active plan is attributed to it.
- Matching fills planned jobs in order; extra runs beyond the plan show as "over plan".
- Manual unlink/relink for the odd job that isn't for the plan.
- Switching the active plan doesn't move jobs already attributed.

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

## Other features (after the core)
- **Janice export** — copy button in Janice/EVE multibuy paste format. Later: Janice appraisal API for prices (needs API key).
- **Compressed ore calculator** — given the mineral shortfall, cheapest compressed-ore mix using reprocessing skills + structure/rig yields. Small LP problem.
- **Dashboard** — all characters' + corp jobs, idle slots, finishing soon, token/role problems, active plans' progress.

## What goes away
- Standalone **Production** (continuous profit) page — doesn't match the use case. Revisit later as a plan-level "profit" view if wanted.
- Standalone **Invention** page — folded into plans for T2 lines.
- The **Industry** hub page, the three-form calculator, URL-encoded state.

## Architecture

- **Planning engine**: pure Python module, no Flask/DB access. Input: plan lines, characters (skills, slots, roles), stations/rigs, blueprints, assets (after reservation), prices, build rules, BPO/BPC choices. Output: the full plan result (materials, jobs, schedule, costs). Heavily unit-tested. Every view reads from this one result, so tabs can't disagree.
- **Backend**: Flask as a JSON API. Celery for ESI fetches (character + corp assets, blueprints, jobs, skills) and token refresh.
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
  - Blueprint source per blueprint: owned BPO (one job, all runs) → owned BPCs (best ME first, one job each) → invention for T2 → "missing" at ME 0 / TE 0 with a warning. Splitting BPO runs across idle slots is step 6.
  - Station: among stations offering the activity, lowest material multiplier, then time, then fee rate. Copy and invention jobs pick a station too, so hull and lab-rig time bonuses apply to them.
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
  - EIV is ME-0 materials × CCP adjusted price ([community]); the client receives EIV from the server, so it can't be checked in client code.
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
  EIV per blueprint comes from the server, so it isn't visible in client code. [client]
- Security classes on the raw value: ≤ 0 null, < 0.45 low, < 0.95 high, ≥ 0.95 safe. [client]
- Invention: chance = base × (1 + Σ level × 1/30 per required skill, 1/40 for skills in SDE type list 799 "LowerInventionSkillProbabilityTypes" = the seven Encryption Methods skills) × decryptor multiplier, clamped to [0, 1]. Output BPC ME 2 + decryptor, TE 4 + decryptor, runs = base + decryptor. Each attempt consumes one run of the T1 copy. [client][SDE]

### Reprocessing / compression (compressed ore calculator)
- Compression is 1:1 since patch 20.03; compressed ore reprocesses in batches of `portionSize` (100). Outputs in `typeMaterials`, raw↔compressed mapping in `compressibleTypes`. [community][SDE]
- Yield = (50 + rig) × (1 + sec) × (1 + structure) × (1 + 0.03·Reprocessing) × (1 + 0.02·Reprocessing Efficiency) × (1 + 0.02·ore skill) × (1 + implant). Rig T1 1 / T2 3; sec high 0, low 0.06, null/WH 0.12; Athanor 0.02, Tatara 0.055; implants 1/2/4%. Wiki page flagged possibly outdated. [community]
- Reprocessing rig groups 1941–1945 present. [SDE]

### Janice
- API v2 (`https://janice.e-351.com/api/rest/v2/`), `X-ApiKey` header; key is requested via a ticket on their Discord. `POST /appraisal` (text/plain, `market`, `pricing`, `pricingVariant`) and `POST /pricer`. Rate limits undocumented. [official, Janice's swagger]
- Paste export format: one item per line, name + quantity (tab-separated like EVE inventory copy). Accepted formats not confirmed from a primary source; test with a real paste. [unverified]

## Backend stack

**Decided (2026-11-03): move to the AT Tool stack.** Django 5.2 + django-ninja (OpenAPI) + Postgres 16 + Redis; frontend API types generated with `openapi-typescript` / `openapi-fetch`; Python `pytest-playwright` browser tests; Docker deploy with Caddy (`deploy/` in the AT Tool). Port the AT Tool's `accounts/sso`, `esi` and `sde` apps; carry over this repo's engine and ESI fetch logic. The Flask app stays runnable until the new stack replaces it.

Rejected: staying on Flask. Needs an OpenAPI add-on and a reimplementation of SSO / ESI / SDE code the AT Tool already has.

### Background work

**Decided (2026-11-03): cron for periodic work + Celery for on-demand work.** Supercronic `scheduler` container (as in the AT Tool) runs management commands for token refresh, scheduled character/corp sync and SDE checks. A Celery worker on the existing Redis runs on-demand jobs ("refresh now", first fetch after linking a character). No Celery beat; cron owns the schedule. Celery over RQ because this repo's fetch tasks (`src/tasks.py`) are already Celery tasks.

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

Next: account-scoped stations (from corp structures in the asset list and `/universe/structures`) and build rules, a builder that turns esidata rows into `PlanInput`, cron entries for `sync_esi`, and a Celery task for "refresh now".

## Build order
0. **Engine types** — input/output dataclasses, including a reason on each decision. Done.
1. **Engine** — extract from `industry.py:get_calculator`, multi-line plans, build rules (item blacklist + tier switches), fix bugs 1–3 and 8–12, tests. Done; see Planning engine. Pure Python, independent of the backend stack decision. Track C (compressed ore + Janice export) runs alongside in a worktree.
2. **Account + data layer** — account-scoped config, all-character + corp fetches (assets, blueprints, jobs, divisions), role detection, token fix, Postgres. In progress; see Step 2 progress.
3. **Plans** — model + JSON API, asset reservation.
4. **React frontend** — Plans list, Plan view (tabs), Setup, Library, Dashboard.
5. **Tracker** — active-plan job matching, progress tab, reservation release.
6. **BPO/BPC trade-off** — auto-copy to fill slots, opt-in buy BPC / extra BPO with cost vs time shown.
7. **Sharing** — corp/link visibility.
8. **Janice export**, then **compressed ore calculator**.

## Decisions (from review, 2026-11-03)
- No plan deadlines.
- One active plan; tracker attributes new jobs to it.
- Build rules (item blacklist + tier switches incl. reaction levels) as account defaults with per-plan overrides.
- BPO vs BPC: auto-copy to fill idle mfg slots; buying BPCs / extra BPOs is opt-in per blueprint with cost vs time shown.
- Corp roles: all my characters are Directors, so corp assets, blueprints, jobs and divisions come straight from ESI; paste fallback is deferred.

## Open questions
- Exact list of tier/category build switches.
- Corp viewers of a shared plan. Default unless changed: **corp** visibility requires EVE SSO login with minimal scopes (to prove corp membership, no data pulled); **link** visibility needs no login.
