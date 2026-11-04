# UX Designer / Frontend Engineer findings

## Summary
The frontend follows `docs/ui-design.md` closely: one primitives file, tokens, Why reasons in every tab, toasts via mutation meta, a coherent `['plans', ...]` query-key tree, and local copies with rollback for save-on-change inputs. The weak spots are about trusting what's on screen at the moment the user acts. The plan page never says how old or how healthy the ESI data behind the shopping list is. The shopping list stays copyable while a 1–2 s recompute is in flight. Line edits are built from server state, so quick consecutive edits can overwrite each other. Several per-plan controls that the API accepts and `docs/redesign.md` promises (per-item buy/build flip, ME/TE override, decryptor) have no UI.

## What I checked
- `docs/ui-design.md`, relevant parts of `docs/redesign.md` (steps 3–4, Jita pricing, rule overrides), the context brief.
- `frontend/src/router.tsx`, `main.tsx`, `components/ui/index.tsx`, `components/AppShell.tsx`, `components/toast.tsx`.
- `frontend/src/features/plans/{PlanPage,tabs,progress,ore,PlansPage,SharedPlanPage}.tsx`, `features/setup/SetupPage.tsx`, `features/dashboard/DashboardPage.tsx`, `features/library/LibraryPage.tsx` (first half).
- `frontend/src/lib/api/{hooks,client}.ts`, `schema.d.ts` (FeedOut), `hooks/{useLocalCopy,useCopy,usePriceSource,useDebouncedValue}.ts`, `lib/format.ts`.
- Backend shapes the UI depends on: `backend/apps/planning/plans_api.py` (PlanSettings, ChoiceIO, PlanResultOut, put_lines/edit_plan return values, progress/link endpoints), `backend/apps/esidata/overview_api.py` `_problems`, `backend/engine/types.py` ItemPlan, `backend/engine/planner.py` warning/decision codes, `backend/apps/planning/ore_api.py` price default.
- TanStack Query 5.105.3 behaviour in `frontend/node_modules/@tanstack/query-core/build/modern/`: `mutation.js:193-201` (status stays `pending` until `onSuccess` resolves), `mutationCache.js:98-104` (scope queue waits on the pending mutation), `queryObserver.js:423-427` (tracked-props re-render).
- Did not run the app (as instructed); no commands with side effects.

## Findings

### UX-1: Plan page gives no sign of how old or how healthy the ESI data behind the shopping list is
- **Severity:** P1
- **Status:** verified
- **Evidence:** `PlanResultOut` (`backend/apps/planning/plans_api.py:359-366`) has no data-as-of or feed-health field. `PlanPage.tsx:62-92` shows total, days and "computing", with nothing about feeds. Feed status is shown only in Setup (`SetupPage.tsx:126-176`) and as failed-feed lines on the Dashboard (`overview_api.py:316-326`, `FeedStatus.objects.filter(ok=False)`). Nothing flags a feed that is `ok` but old, for example when the scheduler is not running; the dev scheduler was only added in HEAD 497cee2. `useRefreshNow` (`hooks.ts:115-122`) invalidates only `['sync','status']`, so when a sync finishes, the open plans, library and dashboard do not refetch. The plan result has `refetchOnWindowFocus: false` (`main.tsx:13`) and no interval (`hooks.ts:227-234`).
- **Problem:** The shopping list subtracts hangar stock (personal and corp assets), and the schedule uses skills and running jobs. If the corp assets feed failed, or last ran hours ago, the list asks the user to buy things they already hold, and the plan page gives no hint of that. This is the page the user copies the multibuy from, so the correctness of the main output depends on information that lives on another page or nowhere.
- **Recommendation:** Add a small `inputs` block to `PlanResultOut`: the oldest `fetched_at` of the asset, blueprint, skill and job feeds the plan used, plus the list of failed feeds. Show it in `PlanHeader` as "assets 12 min ago", turning warn or bad past a threshold or on failure, with a link to Setup. In `useSyncStatus`, when `queued` goes from true to false, invalidate `keys.plans`, `keys.library` and `keys.dashboard`.
- **Effort:** M
- **Tradeoffs / dependencies:** Backend needs a cheap query over `FeedStatus` for the plan's owners; the ESI/data reviewers may want to set the staleness thresholds.

### UX-2: The shopping list, and the list with ore, can be copied while a recompute is running
- **Severity:** P2
- **Status:** verified
- **Evidence:** `usePlanResult` keeps the previous data during a refetch (`hooks.ts:231`, `placeholderData: keepPreviousData`, plus normal refetch-with-data after `invalidateQueries`). `PlanPage.tsx:145` only shows a small muted "computing" label in the header. `ShoppingTab` "Copy list" is enabled whenever `paste` is non-empty (`tabs.tsx:44`). `OrePanel` builds "Copy list with ore" from the current shopping list combined with an ore mix that can belong to the previous plan state (`ore.tsx:47-49`; the ore query is also kept with `keepPreviousData`, `hooks.ts:304`).
- **Problem:** Each plan edit causes a 1–2 s recompute. A common sequence is to change a quantity or rule override, switch to Shopping, and click Copy. That copies the pre-edit list, and the user buys from it. The header label is easy to miss, and the table looks no different.
- **Recommendation:** Pass `stale = result.isFetching` (and `ore.isFetching` for the ore buttons) into the tabs. While it is true, dim the main column (`opacity-60`), disable both copy buttons, and set their title to "recomputing". This is a few lines in `PlanPage.tsx`, `tabs.tsx` and `ore.tsx`.
- **Effort:** S
- **Tradeoffs / dependencies:** The progress poll invalidates results every time job links change (`hooks.ts:410`), so the table will occasionally dim on its own. That is acceptable.

### UX-3: Quick consecutive line edits overwrite each other (lost update)
- **Severity:** P2
- **Status:** verified (mechanism from code); how often it happens is inferred
- **Evidence:** `LinesPanel` builds every new line list from server state: `const lines = p.lines.map(...)` (`PlanPage.tsx:185`). Add, remove and quantity changes all call `save(lines.map/filter(...))` (`PlanPage.tsx:207,220,235`). `setLines` has no `onMutate` and ignores the `PlanOut` that `PUT /lines` returns (`hooks.ts:256-265`; the server returns `_out(p)` at `plans_api.py:299-305`). `scope: 'plan-edit'` serializes the requests but does not rebase them. Each queued PUT still carries the list computed at click time. A `setLines` queued behind an `edit` also waits for that edit's full recompute (UX-6), which widens the window to about 1–2 s.
- **Problem:** Example: removing two lines in quick succession, or changing priority and then adding two items. The second PUT is computed from the old list, so it restores the first removal or drops the first add. Both saves show the "Lines saved" toast. The user builds batches of several lines, so this case is realistic.
- **Recommendation:** Treat lines the way the settings panel already treats its inputs. Keep a `useLocalCopy(p.lines)` list in `LinesPanel`, compute every change from that local copy, and in `setLines` add `onSuccess: (data) => qc.setQueryData(keys.plan(id), data)` so the server's answer replaces the cache without a GET.
- **Effort:** S
- **Tradeoffs / dependencies:** The same stale-base pattern exists in `PurchasePanel.save`, which spreads `plan.choices` from props (`tabs.tsx:251-252`). It is less likely to bite there, but the same fix applies.

### UX-4: Built items have no "why" view, and per-plan item/blueprint overrides the API accepts have no UI
- **Severity:** P2
- **Status:** verified
- **Evidence:**
  - `ItemPlan` carries `decision`, `reason`, `produced` and `surplus` for every item in the tree (`engine/types.py:390-408`). The planner gives build decisions their own reason (`ReasonCode.BUILD_COMPONENT`, `planner.py:331`).
  - The frontend reads `r.items` only for names and the on-hand table (`tabs.tsx:15-18,28`). `grep` finds no use of `.decision`, item `surplus`, `blacklist_add`/`blacklist_remove`, or editing of `me`/`te`/`decryptor` outside `toChoiceIO`.
  - `PlanSettings` accepts `blacklist_add`/`blacklist_remove` (`plans_api.py:61-62`), and `ChoiceIO` accepts `me`, `te` and `decryptor` (`plans_api.py:41-44`).
  - `docs/redesign.md:57` says "A plan shows which rules are in effect and lets you flip one for that plan only". `redesign.md:310` lists ME/TE override and decryptor as plan choices.
- **Problem:** The shopping list explains each bought item. For built intermediates there is no view of why they are built, under which category, or how much surplus they produce. The only per-plan lever is the 10 category selects in Settings. To buy one specific component for one plan, the user has to change the account-wide blacklist, which also changes every other plan. A wrong ME read from ESI or an unwanted automatic decryptor cannot be corrected per blueprint, even though the engine supports both.
- **Recommendation:** Add an "Items" tab: a table of `r.items` with decision badge, Why, produced/needed/surplus, and a per-row "buy here" / "build here" toggle that PATCHes `blacklist_add`/`blacklist_remove`. In the Blueprints tab, add ME/TE number inputs and a decryptor select (for invention) to the expanded row that already exists for buy options, saving through the existing `PurchasePanel.save` path.
- **Effort:** M
- **Tradeoffs / dependencies:** The Items tab makes `effective_rules.overrides` visible. That also addresses the open item at `redesign.md:317` ("rule overrides are not yet shown per item").

### UX-5: Engine warnings are at the bottom of the side column, below a long settings panel
- **Severity:** P2
- **Status:** verified (layout); that they fall below the fold is inferred from the panel contents
- **Evidence:** `PlanPage.tsx:87-92` stacks the side column in the order Lines, Sharing, Settings, Warnings. Settings holds the stations list plus 10 category selects (`format.ts:60-71`, `PlanPage.tsx:394-414`). Below `xl` the side column stacks under the whole main column (`grid gap-4 xl:grid-cols-[1fr_380px]`). The header shows no warning count (`PlanPage.tsx:131-146`). Warnings include "no owned blueprint for N runs" and "No station offers X; planned with no structure bonuses and no job fee" (`planner.py:384-387,640-642`), and both change what gets bought.
- **Problem:** The warnings that most affect whether the plan is right are the ones the user is least likely to see, and they are not visible from the tab where the user acts (Shopping).
- **Recommendation:** Add a `Badge tone="warn"` with the count ("3 warnings") to the `PlanHeader` context. Move `WarningsPanel` to the top of the side column, or above the tabs in the main column.
- **Effort:** S
- **Tradeoffs / dependencies:** none

### UX-6: Settings edits queue behind each other's full recompute
- **Severity:** P3
- **Status:** verified
- **Evidence:** `edit` uses `scope: { id: 'plan-edit' }` and `onSuccess: done`, where `done` returns the `invalidateQueries` promise for all `['plans']` queries (`hooks.ts:238-255`). TanStack keeps the mutation `pending` until `onSuccess` resolves (`query-core/build/modern/mutation.js:193-201`), and a scoped mutation cannot start while another in its scope is pending (`mutationCache.js:98-104`). Active refetches include the plan result (1–2 s), and the blueprint buy-options and compressed-ore queries when those panels are open (`hooks.ts:216-223,299-309`, all under `['plans']`).
- **Problem:** Toggling three rule overrides queues three saves. Each waits for the previous save's full recompute, plus its buy-options plan runs if a buy-options panel is open. The local copies keep the UI responsive, but the toasts arrive seconds late, the result passes through intermediate states, and a later line save (UX-3) waits too.
- **Recommendation:** Use `onSuccess: () => { void done() }` for `edit`, as `setLines` already does, so the queue releases once the PATCH returns. Optionally write the returned `PlanOut` into `keys.plan(id)`.
- **Effort:** S
- **Tradeoffs / dependencies:** Removing the await means a fast sequence of edits triggers overlapping recomputes. `invalidateQueries` cancels the earlier refetch by default (`cancelRefetch`), so only the last one completes.

### UX-7: Plan page state is lost on reload and the page is blank while loading
- **Severity:** P3
- **Status:** verified
- **Evidence:** The tab is `useState` (`PlanPage.tsx:49`), not a search param on `/plans/$planId` (`router.tsx:22`). `if (!plan.data) return null` (`PlanPage.tsx:53`). The same happens in `ProgressTab` (`progress.tsx:77`) and `SharedLinkPage`/`PlanViewPage` (`SharedPlanPage.tsx:23,32`). `PlanViewPage` reports every error, including a 500, as "This plan is not shared with you." (`SharedPlanPage.tsx:30`).
- **Problem:** Reloading, or going Back from Library to a plan, always lands on Shopping. Slow loads show an empty page with no sign the request is in flight. A server error on a shared view reads like a permissions problem.
- **Recommendation:** Add `validateSearch` with `tab` to the plan route and use `useSearch`/`navigate({ search })`. Render a muted "loading" line in place of `null`. On `PlanViewPage`, show the "not shared" message only when `error.status === 404` and use `ErrorText` otherwise.
- **Effort:** S
- **Tradeoffs / dependencies:** none

### UX-8: Smaller consistency gaps
- **Severity:** P3
- **Status:** verified
- **Evidence:**
  - (a) `OrePanel` starts with `{ ore_classes: 'asteroid' }` and no `prices` (`ore.tsx:35`), so it uses Jita (`ore_api.py:54`) even when the header switch is set to CCP average.
  - (b) The Setup feed table and Dashboard problems show owners as ids ("corporation 98xxxxxx assets"). `FeedOut` has no name (`schema.d.ts:1822-1838`, `SetupPage.tsx:160-162`, `overview_api.py:322`).
  - (c) The "Left" countdowns in Progress and Dashboard are computed from `Date.now()` at render (`progress.tsx:27`, `DashboardPage.tsx:22`). The 60 s refetch does not re-render when the data is unchanged, because of structural sharing and tracked props (`queryObserver.js:423-427`), so the countdowns freeze between data changes.
  - (d) Removing a line with picked BPCs (`PlanPage.tsx:220`) has no confirm, and it discards the BPC selection, which has to be picked again.
  - (e) The Schedule tab shows the scheduling reason only as a `title` tooltip on the character cell (`tabs.tsx:341`), against ui-design's "every derived value shows its reason".
- **Problem:** Each is small. (a) and (b) cause confusion when cross-checking numbers. (c) shows wrong times on a page left open.
- **Recommendation:**
  - (a) Initialise the ore query's `prices` from `usePriceSource()`.
  - (b) Add `owner_name` to `FeedOut` and the problem text.
  - (c) Add a 30 s tick, as `PricedAt` already does (`ore.tsx:9-14`).
  - (d) Confirm only when `blueprint_item_ids.length`.
  - (e) Render `<Why>` under the character name.
- **Effort:** S
- **Tradeoffs / dependencies:** none

## Keep
- One query-key tree under `['plans', ...]`, with documented reasons for invalidating everything (reservations couple plans): `hooks.ts:236-240,293-296`.
- `useLocalCopy` plus optimistic `onMutate`/rollback for station and build-rule saves, written before the first await: `hooks.ts:149-166,183-191`, `useLocalCopy.ts`.
- `scope: 'plan-edit'` to stop out-of-order saves, a real fix for a real race (see UX-3/UX-6 for its limits): `hooks.ts:250-252`.
- The ore mix is pinned with `staleTime: Infinity` and a "priced 03:42 · 2 min ago" label that turns amber after 5 min ("what you copy is what you see"): `hooks.ts:297-309`, `ore.tsx:9-23`.
- The `Why` primitive is used consistently for the shopping, source, ME/TE and station reasons; "only N on sale" and "avg" price markers are on shopping rows: `tabs.tsx:73-95,170-206`.
- The global mutation toast through `meta.toast`, with errors always toasted with the server's message, including ninja 422 field paths: `main.tsx:15-21`, `client.ts:31-45`.
- The clipboard fallback to `window.prompt` when clipboard access is refused: `useCopy.ts:11-20`.
- The shared views reuse the same Shopping/Schedule/Progress components read-only, so owner and viewer cannot drift: `SharedPlanPage.tsx:38-91`, `progress.tsx:84`.
- Destructive confirms name what is lost, as ui-design asks: `PlanPage.tsx:168`, `SetupPage.tsx:108,343`, share-link renewal `PlanPage.tsx:467`.
- Station tax input shows `invalid` when the tax is unconfirmed, and the Dashboard lists per-station gaps: `SetupPage.tsx:328`, `overview_api.py:328-339`.

## Concerns to investigate
- The Blueprints tab shows the ME/TE and reason of only the first job (`tabs.tsx:155,183-194`). With mixed sources (BPO plus several BPCs at different ME), the row may mislead. To confirm, look at `dreadbatch 1` (read-only) for a blueprint with more than one job at different ME.
- Plan page performance with large plans (for example 120 Maelstroms): every tab re-renders the full tables on each 60 s progress-triggered invalidation. Not measured; a React profiler run on a large plan would confirm or rule it out.
- The Progress tab and the Dashboard's `ActivePlanSummary` each poll `/progress` every 60 s, and each call runs the tracker plus a full plan run. This is a server-cost question for the architect or SRE reviewers; UX-wise it is invisible.

## Out of lane
- Several interactive elements lack `data-testid`: line ×, rig ×, station Remove, Make main, Re-link (`PlanPage.tsx:220`, `SetupPage.tsx:95-112,299,339`). This is for QA.
- `/progress` is a GET with side effects: it runs `tracker.match` (`plans_api.py:449-451`). This is for architecture.
