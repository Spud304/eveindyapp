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
- **Frontend**: React (Vite + TypeScript), fresh build — not a port of the Jinja templates. Edit the plan in place; recompute only when inputs change.
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

## Known bugs to fix in the engine extraction
1. ME rounding applied per single run then multiplied — overcounts; must be applied to the whole job (`max(runs, ceil(base * runs * ME multipliers))`). `_resolve_material_tree` and `_compute_runs_needed` currently disagree.
2. T2 invented ME updates materials but not job cost, build strategy, or sub-component run counts.
3. Recalculate forms pin `me_<top_bp>` as an override, so changing decryptor afterwards doesn't change ME.
4. Config keyed by logged-in character, not account.
5. Blueprints/jobs only for the logged-in character.
6. Token refresh window (5 min) shorter than beat interval (15 min) → tokens expire between runs; web requests never refresh synchronously.
7. `jsonify(response)` on failed SSO token exchange (`auth.py`) crashes.

## Build order
1. **Engine** — extract from `industry.py:get_calculator`, multi-line plans, build rules (item blacklist + tier switches), fix bugs 1–3, tests.
2. **Account + data layer** — account-scoped config, all-character + corp fetches (assets, blueprints, jobs, divisions), role detection, token fix, Postgres.
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
