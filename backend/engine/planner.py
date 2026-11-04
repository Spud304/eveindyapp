"""Plan computation: merged demand tree -> jobs -> schedule -> costs.

Algorithm:
1. Decide build vs buy for every item reachable from the plan lines.
2. Order the BUILD items so every consumer comes before its inputs.
3. Walk that order once. Each item's demand is final when it is reached
   (all consumers are done), so its runs are computed once on the merged
   demand of all lines. Its jobs are created (one per blueprint source) and
   each job's materials, rounded per job, become demand on its inputs.
4. BUY items are leaves; what is left after assets goes on the shopping list.
5. Schedule jobs onto characters, then compute fees (alpha tax depends on
   who runs the job).
6. Auto-copy: for each owned BPO that can be copied, try running it as the BPO
   plus copies it makes first, all in parallel. A split is kept only if it
   makes the whole plan finish sooner (by at least MIN_SPLIT_GAIN). Options
   are compared by re-scheduling only; the chosen splits are then planned
   again in full, so materials are exact.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace

from . import constants as c
from . import formulas as f
from .schedule import WorkJob, schedule
from .types import (
    Activity,
    BlueprintChoice,
    BlueprintPlan,
    BlueprintSource,
    BuildCategory,
    Character,
    CostSummary,
    Decryptor,
    DecryptorOption,
    InventionPlan,
    ItemDecision,
    ItemPlan,
    JobCost,
    Material,
    OwnedBlueprint,
    PlanInput,
    PlannedJob,
    PlanResult,
    PlanWarning,
    Reason,
    ReasonCode,
    Recipe,
    ScheduledSlot,
    ShoppingItem,
    Station,
    StationChoice,
    TypeId,
)


class PlanError(ValueError):
    pass


# A split must make the plan finish at least this much sooner to be kept: each copy costs a
# copy job fee and a little extra material (materials are rounded per job).
MIN_SPLIT_GAIN = 3600.0


def plan(inp: PlanInput) -> PlanResult:
    base = _Planner(inp)
    result = base.run()
    spread, parallel, saved = _search_parallel(base)
    if not spread and not parallel:
        return result
    split = _Planner(inp, parallel, saved, spread).run()
    # Per-job rounding can add a downstream run the search did not see; never return a
    # slower plan than the one without these settings.
    return split if split.total_seconds < result.total_seconds else result


@dataclass(frozen=True)
class _Producer:
    blueprint_type_id: TypeId
    activity: Activity
    recipe: Recipe


@dataclass(frozen=True)
class _Spec:
    """One manufacturing or reaction job to create for a blueprint."""

    runs: int
    me: int
    te: int
    source: BlueprintSource
    me_reason: Reason
    lock: str | None = None  # blueprint item the job is installed with


@dataclass(frozen=True)
class _CopyPlan:
    """An owned BPO whose runs could be split across copies of it (see `_bpo_layout`)."""

    prod: _Producer
    bpo: _Spec  # the BPO's single job, after any ME/TE override
    runs: int
    time_mult: float  # station time factor for manufacturing
    max_per_copy: int  # blueprint max production limit
    copy_recipe: Recipe
    copy_station: Station | None
    copy_bonuses: f.StationBonuses
    cost_mult: float  # blueprint job cost multiplier
    first: int = 0  # owned BPC jobs of the blueprint numbered before the BPO's


def _bpo_layout(cp: _CopyPlan, k: int) -> tuple[list[_Spec], list[int], int]:
    """Split a BPO's runs into k parallel jobs: the BPO itself plus k - 1 copies it makes
    first. Returns (manufacturing specs, copies per copy job, runs per copy). Copies get
    ceil(runs / k) runs each, capped at the blueprint's max production limit; the BPO keeps
    the rest, at least one run. One copy job's time minus one copy's time may not exceed
    30 days. [client: job.py RUN_LENGTH check, activities/copying.py]"""
    per_copy = min(math.ceil(cp.runs / k), cp.max_per_copy)
    n = min(k - 1, (cp.runs - 1) // per_copy) if k > 1 else 0
    if n <= 0:
        return [cp.bpo], [], 0
    me, te = cp.bpo.me, cp.bpo.te
    why = Reason(
        ReasonCode.ME_OWNED_BPO,
        f"Copy of the owned BPO at ME {me} / TE {te}, made by this plan.",
    )
    specs = [replace(cp.bpo, runs=cp.runs - n * per_copy)]
    specs += [_Spec(per_copy, me, te, BlueprintSource.COPY, why)] * n
    cap = f.max_runs(Activity.COPYING, cp.copy_recipe.time_seconds * per_copy, cp.copy_bonuses.time)
    return specs, list(_split(n, cap)), per_copy


@dataclass
class _Layout:
    """What a blueprint's jobs are made from, kept so the search can lay them out again with a
    different spread over owned BPCs or BPO split: specs before the owned BPCs (picked and
    bought), the owned BPCs and the runs they cover, specs after (extra BPOs, the BPO,
    invention, missing)."""

    prod: _Producer
    prefix: list[_Spec]
    pool: list[OwnedBlueprint]
    pool_need: int
    suffix: list[_Spec]
    choice: BlueprintChoice
    time_mult: float
    invention_job_ids: list[str]
    k_min: int = 0  # owned BPCs used when each is used up in order
    cp: _CopyPlan | None = None


@dataclass
class _JobMeta:
    """Output-only job fields kept alongside the schedulable WorkJob."""

    me: int
    te: int
    me_reason: Reason
    source: BlueprintSource
    station: Station | None
    materials: tuple[Material, ...]
    product_type_id: TypeId | None
    product_quantity: int
    eiv_materials: tuple[Material, ...]  # ME 0 materials whose adjusted value is the EIV
    cost_multiplier: float = 1.0  # hull, rig and blueprint cost modifiers on the cost index
    base_share: float = 1.0  # base cost = EIV x runs x copies x this (2% for copy/invention)


class _Planner:
    def __init__(
        self,
        inp: PlanInput,
        parallel: dict[TypeId, int] | None = None,
        saved: dict[TypeId, float] | None = None,
        spread: dict[TypeId, int] | None = None,
    ):
        self.inp = inp
        # Auto-copy: parallel jobs per BPO blueprint, and the seconds each split saves.
        self.parallel = parallel or {}
        self.saved = saved or {}
        # Owned BPCs to spread a blueprint's runs over (None in the dict: the fewest).
        self.spread = spread or {}
        self.layouts: dict[TypeId, _Layout] = {}
        self.copy_plans: dict[TypeId, _CopyPlan] = {}
        self.copy_job_ids: dict[TypeId, list[str]] = {}  # auto-copy jobs by blueprint
        # Opt-in blueprint purchases: (kind "bpc" / "bpo", blueprint, count, unit price or None)
        self.purchases: list[tuple[str, TypeId, int, float | None]] = []
        self.types = inp.game.types
        self.warnings: list[PlanWarning] = []

        self.producers: dict[TypeId, _Producer] = {}
        self.invented_from: dict[TypeId, tuple[TypeId, Recipe]] = {}
        reaction_inputs: set[TypeId] = set()
        for bp in inp.game.blueprints.values():
            if bp.manufacturing and bp.manufacturing.product_type_id is not None:
                self.producers[bp.manufacturing.product_type_id] = _Producer(
                    bp.type_id, Activity.MANUFACTURING, bp.manufacturing
                )
            for inv in bp.invention:
                if inv.product_type_id is not None:
                    self.invented_from[inv.product_type_id] = (bp.type_id, inv)
            if bp.reaction:
                reaction_inputs.update(m.type_id for m in bp.reaction.materials)
        for bp in inp.game.blueprints.values():
            r = bp.reaction
            if r and r.product_type_id is not None and r.product_type_id not in self.producers:
                self.producers[r.product_type_id] = _Producer(bp.type_id, Activity.REACTION, r)
        self.reaction_inputs = reaction_inputs

        self.owned: dict[TypeId, list[OwnedBlueprint]] = defaultdict(list)
        # Originals already in a job are free when that job ends; their planned jobs wait.
        self.busy: dict[str, float] = {}
        for ob in inp.blueprints:
            self.owned[ob.type_id].append(ob)
            if ob.job_activity_id is not None and not ob.is_copy:
                self.busy[_item_lock(ob)] = max(0.0, ob.job_ends_in)
            if ob.source_job_id is not None:
                self.busy[_item_lock(ob)] = max(0.0, ob.available_in)

        self.line_qty: dict[TypeId, int] = defaultdict(int)
        # BPCs picked on plan lines, by item id, in the order they were picked.
        self.picked: dict[int, int] = {}
        for line in inp.lines:
            for item_id in line.blueprint_item_ids:
                self.picked.setdefault(item_id, len(self.picked))
            if line.quantity <= 0:
                raise PlanError(f"line {line.line_id}: quantity must be positive")
            self.line_qty[line.type_id] += line.quantity

        self.decisions: dict[TypeId, tuple[ItemDecision, Reason, BuildCategory | None]] = {}
        self.input_qty: dict[TypeId, int] = defaultdict(int)
        self.item_rows: dict[TypeId, ItemPlan] = {}
        self.jobs: list[WorkJob] = []
        self.meta: dict[str, _JobMeta] = {}
        self.jobs_by_product: dict[TypeId, list[str]] = defaultdict(list)
        self.bp_plans: list[BlueprintPlan] = []

    # -- helpers -----------------------------------------------------------

    def name(self, type_id: TypeId) -> str:
        t = self.types.get(type_id)
        return t.name if t else f"Type {type_id}"

    def warn(self, code: ReasonCode, text: str) -> None:
        self.warnings.append(PlanWarning(code, text))

    def price(self, type_id: TypeId) -> float | None:
        p = self.inp.prices.get(type_id)
        return p.unit_price if p else None

    def volume(self, type_id: TypeId) -> float:
        t = self.types.get(type_id)
        return t.volume if t else 0.0

    def adjusted(self) -> dict[TypeId, float | None]:
        return {t: p.adjusted_price for t, p in self.inp.prices.items()}

    # -- 1. build vs buy ---------------------------------------------------

    def build_category(self, type_id: TypeId) -> BuildCategory | None:
        prod = self.producers.get(type_id)
        if prod is None:
            return None
        if prod.activity == Activity.REACTION:
            formula = self.types.get(prod.blueprint_type_id)
            group = formula.group_id if formula else None
            if group == c.GROUP_COMPOSITE_FORMULAS:
                if type_id in self.reaction_inputs:
                    return BuildCategory.REACTION_INTERMEDIATE
                return BuildCategory.REACTION_COMPOSITE
            return {
                c.GROUP_POLYMER_FORMULAS: BuildCategory.REACTION_HYBRID,
                c.GROUP_BIOCHEMICAL_FORMULAS: BuildCategory.REACTION_BIOCHEMICAL,
                c.GROUP_MOLECULAR_FORGED_FORMULAS: BuildCategory.REACTION_MOLECULAR_FORGED,
            }.get(group)
        if prod.blueprint_type_id in self.invented_from:
            return BuildCategory.T2_ITEMS
        t = self.types.get(type_id)
        return c.GROUP_BUILD_CATEGORY.get(t.group_id) if t else None

    def decide(self, type_id: TypeId) -> tuple[ItemDecision, Reason, BuildCategory | None]:
        if type_id in self.decisions:
            return self.decisions[type_id]
        rules = self.inp.rules
        prod = self.producers.get(type_id)
        cat = self.build_category(type_id)
        if type_id in self.line_qty:
            if prod:
                d = (
                    ItemDecision.BUILD,
                    Reason(ReasonCode.PLAN_LINE, "Plan line."),
                    cat,
                )
            else:
                d = (
                    ItemDecision.BUY,
                    Reason(
                        ReasonCode.LINE_NOT_BUILDABLE,
                        "Plan line has no blueprint; buying it.",
                    ),
                    cat,
                )
                self.warn(
                    ReasonCode.LINE_NOT_BUILDABLE,
                    f"{self.name(type_id)} has no blueprint.",
                )
        elif type_id in rules.item_blacklist:
            d = (
                ItemDecision.BUY,
                Reason(ReasonCode.BUY_BLACKLIST, "Buying (item blacklist)."),
                cat,
            )
        elif prod is None:
            d = (
                ItemDecision.BUY,
                Reason(ReasonCode.BUY_NO_BLUEPRINT, "No blueprint or reaction."),
                cat,
            )
        elif cat in rules.buy_categories:
            d = (
                ItemDecision.BUY,
                Reason(ReasonCode.BUY_RULE, f"Buying (rule: {cat.value})."),
                cat,
            )
        else:
            d = (
                ItemDecision.BUILD,
                Reason(ReasonCode.BUILD_COMPONENT, "Built as a component."),
                cat,
            )
        self.decisions[type_id] = d
        return d

    # -- 2. ordering ---------------------------------------------------------

    def build_order(self) -> list[TypeId]:
        children: dict[TypeId, set[TypeId]] = {}
        stack = list(self.line_qty)
        while stack:
            t = stack.pop()
            if t in children:
                continue
            decision, _, _ = self.decide(t)
            if decision != ItemDecision.BUILD:
                children[t] = set()
                continue
            kids = {m.type_id for m in self.producers[t].recipe.materials}
            children[t] = kids
            stack.extend(kids)

        build = [t for t in children if self.decisions[t][0] == ItemDecision.BUILD]
        indegree = {t: 0 for t in build}
        for t in build:
            for k in children[t]:
                if k in indegree:
                    indegree[k] += 1
        order: list[TypeId] = []
        queue = sorted(t for t in build if indegree[t] == 0)
        while queue:
            t = queue.pop(0)
            order.append(t)
            for k in sorted(children[t]):
                if k in indegree:
                    indegree[k] -= 1
                    if indegree[k] == 0:
                        queue.append(k)
        if len(order) != len(build):
            cyclic = sorted(set(build) - set(order))
            raise PlanError(f"build tree has a cycle through {cyclic}")
        self.children = children
        return order

    # -- station -------------------------------------------------------------

    def choose_station(self, activity: Activity, product_type_id: TypeId | None, bp_id: TypeId):
        """Best station for one activity and product: (station, bonuses, choice)."""
        product = self.types.get(product_type_id) if product_type_id is not None else None
        candidates = [s for s in self.inp.stations if activity in s.activities]
        if not candidates:
            self.warn(
                ReasonCode.STATION_NONE,
                f"No station offers {activity.value}; {self.name(bp_id)} "
                "planned with no structure bonuses and no job fee.",
            )
            none = f.StationBonuses(1.0, 1.0, 1.0, "no station")
            reason = Reason(ReasonCode.STATION_NONE, f"No station offers {activity.value}.")
            return None, none, StationChoice(None, 0.0, 1.0, reason)

        scored = []
        for s in candidates:
            system = self.inp.systems.get(s.system_id)
            sec = f.security_class(system.security if system else None)
            bonuses = f.station_bonuses(s, activity, product, sec)
            index = system.cost_indices.get(activity, 0.0) if system else 0.0
            fee_rate = index * bonuses.cost + s.facility_tax / 100
            key = (bonuses.material, bonuses.time, fee_rate, s.station_id)
            scored.append((key, s, bonuses))
        scored.sort(key=lambda x: x[0])
        _, best, bonuses = scored[0]
        text = (
            f"{best.name}: {bonuses.description}; material x{bonuses.material:.4f}, "
            f"time x{bonuses.time:.4f}, cost x{bonuses.cost:.4f}. Lowest materials, then time, "
            f"then fee rate, of {len(candidates)} station(s) offering {activity.value}."
        )
        choice = StationChoice(
            best.station_id,
            (1 - bonuses.material) * 100,
            bonuses.time,
            Reason(ReasonCode.STATION_BEST, text),
        )
        return best, bonuses, choice

    # -- 3. jobs -------------------------------------------------------------

    def add_job(self, work: WorkJob, meta: _JobMeta) -> None:
        self.jobs.append(work)
        self.meta[work.job_id] = meta
        if meta.product_type_id is not None and work.activity in (
            Activity.MANUFACTURING,
            Activity.REACTION,
        ):
            self.jobs_by_product[meta.product_type_id].append(work.job_id)
        for m in meta.materials:
            self.input_qty[m.type_id] += m.quantity

    def cover(self, type_id: TypeId) -> tuple[int, int, int, int]:
        """(started used, assets used, still needed, over plan) for one item.

        Units from jobs already attributed to the plan cover demand first, plan lines
        included (a started job is the line being built). Assets then cover what is left of
        the input demand only, as before."""
        line, inputs = self.line_qty[type_id], self.input_qty[type_id]
        started = self.inp.started.get(type_id, 0)
        s = min(started, line + inputs)
        line_left = max(0, line - s)
        inputs_left = inputs - (s - (line - line_left))
        used = min(self.inp.assets.get(type_id, 0), inputs_left)
        return s, used, line_left + inputs_left - used, started - s

    def plan_item(self, type_id: TypeId) -> None:
        prod = self.producers[type_id]
        decision, reason, cat = self.decisions[type_id]
        reducible = self.input_qty[type_id]
        started, used, net, over = self.cover(type_id)
        per_run = prod.recipe.product_quantity or 1
        runs = math.ceil(net / per_run) if net > 0 else 0
        if runs:
            self.plan_blueprint(prod, type_id, runs)
        produced = runs * per_run
        self.item_rows[type_id] = ItemPlan(
            type_id=type_id,
            name=self.name(type_id),
            decision=decision,
            reason=reason,
            line_quantity=self.line_qty[type_id],
            input_quantity=reducible,
            on_hand_used=used,
            produced=produced,
            surplus=produced - net,
            to_buy=0,
            blueprint_type_id=prod.blueprint_type_id,
            build_category=cat,
            started=started,
            over_plan=over,
        )

    def plan_blueprint(self, prod: _Producer, product_type_id: TypeId, runs: int) -> None:
        bp_id = prod.blueprint_type_id
        station, bonuses, station_choice = self.choose_station(
            prod.activity, product_type_id, bp_id
        )
        mat_mult, time_mult = bonuses.material, bonuses.time
        choice = self.inp.choices.get(bp_id, BlueprintChoice())
        owned = self.owned.get(bp_id, [])
        bpos = [b for b in owned if not b.is_copy]
        # Picked BPCs first, in the order picked; then the rest, best ME first.
        in_jobs = [b for b in owned if b.is_copy and b.job_activity_id is not None]
        bpcs = sorted(
            (b for b in owned if b.is_copy and b.job_activity_id is None),
            key=lambda b: (
                self.picked.get(b.item_id, len(self.picked)),
                -b.me,
                -b.te,
                max(0.0, b.available_in),
                b.source_job_id is not None,  # in the hangar before copies not yet delivered
                b.item_id,
            ),
        )
        is_reaction = prod.activity == Activity.REACTION

        specs: list[_Spec] = []
        source_notes: list[str] = []
        invention: InventionPlan | None = None
        invention_job_ids: list[str] = []
        remaining = runs

        def me_reason(code: ReasonCode, text: str) -> Reason:
            if is_reaction:
                return Reason(ReasonCode.ME_REACTION, "Reaction formulas have no ME/TE.")
            return Reason(code, text)

        # Owned BPCs first, best ME first, one job each. With a BPO owned too, only BPCs at
        # least as good in ME are used (they cost no more materials), and the BPO takes the
        # rest of the runs.
        best_bpo = _best_bpo(bpos) if bpos else None
        usable = [
            b for b in bpcs if best_bpo is None or b.me >= best_bpo.me or b.item_id in self.picked
        ]
        bp_data = self.inp.game.blueprints.get(bp_id)
        picked_used = incoming_used = owned_used = 0

        def use_bpc(b: OwnedBlueprint) -> None:
            nonlocal remaining, picked_used, incoming_used, owned_used
            take = min(b.runs, remaining)
            if take <= 0:
                return
            specs.append(
                _Spec(
                    take,
                    b.me,
                    b.te,
                    BlueprintSource.BPC,
                    me_reason(ReasonCode.ME_OWNED_BPC, self.bpc_text(b)),
                    _item_lock(b),
                )
            )
            remaining -= take
            owned_used += 1
            picked_used += b.item_id in self.picked
            incoming_used += b.source_job_id is not None

        for b in [b for b in usable if b.item_id in self.picked]:
            use_bpc(b)
        # BPCs you chose to buy come after picked ones, before the rest you own.
        bought_bpcs = 0
        if not is_reaction and choice.buy_bpcs > 0:
            per = choice.bpc_runs or (bp_data.max_production_limit if bp_data else 1)
            why = Reason(
                ReasonCode.ME_BOUGHT,
                f"Bought BPC (your choice): ME {choice.bpc_me} / TE {choice.bpc_te}, {per} runs.",
            )
            for n in range(1, choice.buy_bpcs + 1):
                take = min(max(1, per), remaining)
                if take <= 0:
                    break
                lock = f"bought-bpc:{bp_id}:{n}"
                specs.append(
                    _Spec(take, choice.bpc_me, choice.bpc_te, BlueprintSource.BOUGHT, why, lock)
                )
                remaining -= take
                bought_bpcs += 1
            self.purchases.append(("bpc", bp_id, choice.buy_bpcs, choice.bpc_price))
            source_notes.append(f"{choice.buy_bpcs} bought BPC(s) of {per} runs (your choice)")
        # The rest of the owned BPCs: how many to use, and how many runs each, is decided by
        # `pool_specs` (fewest BPCs, or spread over more when that finishes the plan sooner).
        pool = [b for b in usable if b.item_id not in self.picked]
        pool_index = len(specs)
        pool_need = min(remaining, sum(b.runs for b in pool))
        remaining -= pool_need
        if in_jobs:
            source_notes.append(f"{len(in_jobs)} owned BPC(s) in jobs not used")
        if len(usable) < len(bpcs) and best_bpo is not None:
            skipped = len(bpcs) - len(usable)
            source_notes.append(
                f"{skipped} owned BPC(s) with lower ME than the BPO (ME {best_bpo.me}) not used"
            )

        # Originals: the owned BPO and any extra BPOs you chose to buy share the rest evenly.
        extra = choice.extra_bpos if not is_reaction else 0
        if extra > 0:
            self.purchases.append(("bpo", bp_id, extra, self.price(bp_id)))
        if remaining > 0 and (best_bpo is not None or extra > 0):
            shares = [x for x in _even(remaining, extra + (best_bpo is not None)) if x > 0]
            own_share = shares.pop(0) if best_bpo is not None else 0
            why = Reason(
                ReasonCode.ME_BOUGHT,
                f"Extra BPO (your choice): ME {choice.bpo_me} / TE {choice.bpo_te}.",
            )
            for n, share in enumerate(shares, 1):
                lock = f"bought-bpo:{bp_id}:{n}"
                specs.append(
                    _Spec(share, choice.bpo_me, choice.bpo_te, BlueprintSource.BOUGHT, why, lock)
                )
            if extra:
                source_notes.append(
                    f"{extra} extra BPO(s) bought (your choice) at ME {choice.bpo_me} / "
                    f"TE {choice.bpo_te}, sharing the runs"
                )
            if best_bpo is not None:
                b = best_bpo
                specs.append(
                    _Spec(
                        own_share,
                        b.me,
                        b.te,
                        BlueprintSource.BPO,
                        me_reason(
                            ReasonCode.ME_OWNED_BPO,
                            f"Owned BPO ME {b.me} / TE {b.te} (best of {len(bpos)}).",
                        ),
                        _item_lock(b),
                    )
                )
                source_notes.append(
                    f"owned BPO for {own_share} runs" if specs[:-1] or pool_need else "owned BPO"
                )
                if b.job_activity_id is not None:
                    source_notes.append(_job_note(b))
            remaining = 0

        if remaining > 0 and not is_reaction and bp_id in self.invented_from:
            invention, inv_specs, invention_job_ids = self.plan_invention(
                bp_id, remaining, choice, mat_mult, prod.recipe
            )
            if invention is not None:
                specs.extend(inv_specs)
                source_notes.append(f"{remaining} runs from invention")
                remaining = 0

        if remaining > 0:
            specs.append(
                _Spec(
                    remaining,
                    0,
                    0,
                    BlueprintSource.MISSING,
                    me_reason(
                        ReasonCode.ME_MISSING_BLUEPRINT,
                        "No owned blueprint; planned at ME 0 / TE 0 until you add one.",
                    ),
                    # Planned as one blueprint you would buy, so its jobs run one after another.
                    f"missing:{bp_id}",
                )
            )
            source_notes.append(f"{remaining} runs need a blueprint you do not own")
            self.warn(
                ReasonCode.SOURCE_MISSING,
                f"{self.name(bp_id)}: no owned blueprint for {remaining} runs.",
            )

        bp_cost_mult = bp_data.job_cost_multiplier if bp_data else 1.0
        lay = _Layout(
            prod=prod,
            prefix=specs[:pool_index],
            pool=pool,
            pool_need=pool_need,
            suffix=specs[pool_index:],
            choice=choice,
            time_mult=time_mult,
            invention_job_ids=invention_job_ids,
        )
        lay.k_min = len(self.pool_specs(lay, None)[0])

        # Auto-copy: an owned BPO that can be copied is a candidate for the split search.
        bpo_spec = next(
            (sp for sp in self.override(lay.suffix, lay) if sp.source == BlueprintSource.BPO),
            None,
        )
        if not is_reaction and bp_data and bp_data.copying and bpo_spec and bpo_spec.runs > 1:
            copy_station, copy_bonuses, _ = self.choose_station(Activity.COPYING, None, bp_id)
            lay.cp = _CopyPlan(
                prod=prod,
                bpo=bpo_spec,
                runs=bpo_spec.runs,
                time_mult=time_mult,
                max_per_copy=max(1, bp_data.max_production_limit),
                copy_recipe=bp_data.copying,
                copy_station=copy_station,
                copy_bonuses=copy_bonuses,
                cost_mult=bp_cost_mult,
            )
            self.copy_plans[bp_id] = lay.cp
        self.layouts[bp_id] = lay
        cp = lay.cp

        k_spread = self.spread.get(bp_id)
        specs, copy_parts, per_copy, one_job, used = self.layout_specs(
            lay, k_spread, self.parallel.get(bp_id, 1)
        )
        bpc_runs = sum(sp.runs for sp in specs if sp.source == BlueprintSource.BPC)
        if picked_used or used:
            note = f"{picked_used + len(used)} owned BPC(s) cover {bpc_runs} runs"
            if picked_used:
                note += f" ({picked_used} picked for this plan)"
            incoming_used += sum(b.source_job_id is not None for b in used)
            if incoming_used:
                note += f"; {incoming_used} of them still being made by copy jobs"
            if k_spread is not None:
                note += (
                    f", spread over {len(used)} BPCs so they run in parallel: the plan finishes "
                    f"{_duration(self.saved.get(bp_id, 0.0))} sooner than using the fewest "
                    f"({lay.k_min})"
                )
            source_notes.insert(0, note)

        specs = self.split_long(prod, specs, time_mult, source_notes)

        copy_ids = []
        for n, copies in enumerate(copy_parts, 1):
            assert cp is not None
            work = self.copy_work(bp_id, n, cp, per_copy, copies)
            self.add_job(
                work,
                _JobMeta(
                    me=cp.bpo.me,
                    te=cp.bpo.te,
                    me_reason=Reason(
                        ReasonCode.SOURCE_BPO,
                        f"Copies of the owned BPO so {len(specs) - 1} more jobs run in parallel.",
                    ),
                    source=BlueprintSource.BPO,
                    station=cp.copy_station,
                    materials=(),
                    product_type_id=bp_id,
                    product_quantity=copies,
                    eiv_materials=prod.recipe.materials,
                    cost_multiplier=cp.copy_bonuses.cost * bp_cost_mult,
                    base_share=c.COST_PERCENTAGE,
                ),
            )
            copy_ids.append(work.job_id)

        job_ids = list(copy_ids)
        for i, sp in enumerate(specs, 1):
            mats = f.job_materials(prod.recipe.materials, sp.runs, sp.me, mat_mult)
            work = self.mfg_work(
                prod, sp, f"{prod.activity.value}:{bp_id}:{i}", time_mult, {m.type_id for m in mats}
            )
            if sp.source == BlueprintSource.INVENTION:
                work.depends_on.extend(invention_job_ids)
            if sp.source in (BlueprintSource.BPO, BlueprintSource.COPY):
                work.depends_on.extend(copy_ids)
            self.add_job(
                work,
                _JobMeta(
                    me=sp.me,
                    te=sp.te,
                    me_reason=sp.me_reason,
                    source=sp.source,
                    station=station,
                    materials=mats,
                    product_type_id=product_type_id,
                    product_quantity=sp.runs * (prod.recipe.product_quantity or 1),
                    eiv_materials=prod.recipe.materials,
                    cost_multiplier=bonuses.cost * bp_cost_mult,
                ),
            )
            job_ids.append(work.job_id)

        if copy_parts:
            n_copies = sum(copy_parts)
            note = (
                f"{n_copies} {_plural(n_copies, 'copy', 'copies')} of {per_copy} "
                f"{_plural(per_copy, 'run', 'runs')} made first, "
                f"so {n_copies + 1} jobs run in parallel: the plan finishes "
                f"{_duration(self.saved.get(bp_id, 0.0))} sooner than with the BPO alone"
            )
            extra = self.extra_materials(prod, specs, one_job, mat_mult)
            if extra:
                note += f"; per-job rounding uses {extra}"
            source_notes.append(note)
            self.copy_job_ids[bp_id] = copy_ids

        sources = tuple(dict.fromkeys(sp.source for sp in specs))
        code = {
            BlueprintSource.BPO: ReasonCode.SOURCE_BPO,
            BlueprintSource.BPC: ReasonCode.SOURCE_BPC,
            BlueprintSource.COPY: ReasonCode.SOURCE_COPY,
            BlueprintSource.BOUGHT: ReasonCode.SOURCE_BOUGHT,
            BlueprintSource.INVENTION: ReasonCode.SOURCE_INVENTION,
            BlueprintSource.MISSING: ReasonCode.SOURCE_MISSING,
        }[sources[-1]]
        self.bp_plans.append(
            BlueprintPlan(
                type_id=bp_id,
                name=self.name(bp_id),
                activity=prod.activity,
                product_type_id=product_type_id,
                runs=runs,
                sources=sources,
                source_reason=Reason(code, _sentence("; ".join(source_notes))),
                station=station_choice,
                job_ids=tuple(job_ids + invention_job_ids),
                invention=invention,
            )
        )

    def override(self, specs: list[_Spec], lay: _Layout) -> list[_Spec]:
        """ME / TE set by you replace every job's own."""
        c_ = lay.choice
        if lay.prod.activity == Activity.REACTION or (
            c_.me_override is None and c_.te_override is None
        ):
            return list(specs)
        out = []
        for sp in specs:
            new_me = c_.me_override if c_.me_override is not None else sp.me
            new_te = c_.te_override if c_.te_override is not None else sp.te
            why = Reason(
                ReasonCode.ME_OVERRIDE,
                f"ME {new_me} / TE {new_te} set by you (blueprint gives ME {sp.me} / TE {sp.te}).",
            )
            out.append(replace(sp, me=new_me, te=new_te, me_reason=why))
        return out

    def pool_specs(self, lay: _Layout, k: int | None) -> tuple[list[_Spec], list[OwnedBlueprint]]:
        """Jobs on the owned BPCs (not picked) for `lay.pool_need` runs. `k` None: the fewest
        BPCs, each used up in order. Otherwise at least `k` BPCs (more if their runs fall
        short), runs shared so the jobs are as even as the BPCs allow."""
        need = lay.pool_need
        if need <= 0:
            return [], []
        if k is None:
            takes = []
            for b in lay.pool:
                if need <= 0:
                    break
                t = min(b.runs, need)
                if t > 0:
                    takes.append((b, t))
                    need -= t
        else:
            n = k
            while sum(b.runs for b in lay.pool[:n]) < need:
                n += 1
            chosen = lay.pool[:n]
            takes = [
                (b, t)
                for b, t in zip(chosen, _water_fill([b.runs for b in chosen], need), strict=True)
                if t > 0
            ]
        specs = [
            _Spec(
                t,
                b.me,
                b.te,
                BlueprintSource.BPC,
                Reason(ReasonCode.ME_OWNED_BPC, self.bpc_text(b)),
                _item_lock(b),
            )
            for b, t in takes
        ]
        return specs, [b for b, _ in takes]

    def layout_specs(self, lay: _Layout, k_spread: int | None, k_copy: int):
        """A blueprint's manufacturing specs for the given spread and BPO split, before the
        30-day split: (specs, copies per copy job, runs per copy, the unsplit BPO specs or
        None, owned BPCs used)."""
        pool_specs, used = self.pool_specs(lay, k_spread)
        specs = self.override(lay.prefix + pool_specs + lay.suffix, lay)
        copy_parts: list[int] = []
        per_copy = 0
        one_job = None
        if lay.cp is not None and k_copy > 1:
            i = next(i for i, sp in enumerate(specs) if sp.source == BlueprintSource.BPO)
            one_job = self.split_long(lay.prod, specs, lay.time_mult, [])
            layout, copy_parts, per_copy = _bpo_layout(lay.cp, k_copy)
            specs = specs[:i] + layout + specs[i + 1 :]
        return specs, copy_parts, per_copy, one_job, used

    def bpc_text(self, b: OwnedBlueprint) -> str:
        stats = f"ME {b.me} / TE {b.te}, {b.runs} runs"
        if b.source_job_id is not None:
            when = (
                "finished: deliver it first"
                if b.available_in <= 0
                else f"ready in {_duration(b.available_in)}"
            )
            return f"Copy being made by job {b.source_job_id}: {stats}; {when}."
        kind = "BPC picked for this plan" if b.item_id in self.picked else "Owned BPC"
        return f"{kind} {b.item_id}: {stats}."

    def split_long(
        self, prod: _Producer, specs: list[_Spec], time_mult: float, notes: list[str]
    ) -> list[_Spec]:
        """Jobs on an original (BPO, reaction formula, or a BPO you do not own yet) may not run
        longer than 30 days; copies are limited only by their runs. [client]"""
        is_reaction = prod.activity == Activity.REACTION
        out = []
        for sp in specs:
            if sp.source in (BlueprintSource.BPO, BlueprintSource.MISSING):
                te_factor = 1.0 if is_reaction else 1 - sp.te / 100
                cap = f.max_runs(prod.activity, prod.recipe.time_seconds, te_factor * time_mult)
                if sp.runs > cap:
                    notes.append(
                        f"split into jobs of at most {cap} runs (30-day job limit, before skills)"
                    )
                out.extend(replace(sp, runs=chunk) for chunk in _split(sp.runs, cap))
            else:
                out.append(sp)
        return out

    def mfg_work(
        self, prod: _Producer, sp: _Spec, job_id: str, time_mult: float, dep_items: set[TypeId]
    ) -> WorkJob:
        te_factor = 1.0 if prod.activity == Activity.REACTION else 1 - sp.te / 100
        return WorkJob(
            job_id=job_id,
            activity=prod.activity,
            blueprint_type_id=prod.blueprint_type_id,
            runs=sp.runs,
            time_per_run=prod.recipe.time_seconds,
            time_multiplier=te_factor * time_mult,
            skills=prod.recipe.skills,
            dep_items=dep_items,
            skill_time_bonuses=self.inp.game.skill_time_bonuses,
            lock=sp.lock,
        )

    def copy_work(self, bp_id: TypeId, n: int, cp: _CopyPlan, per_copy: int, copies: int):
        return WorkJob(
            job_id=f"copying:{bp_id}:{n}",
            activity=Activity.COPYING,
            blueprint_type_id=bp_id,
            runs=per_copy,
            copies=copies,
            time_per_run=cp.copy_recipe.time_seconds,
            time_multiplier=cp.copy_bonuses.time,
            skills=cp.copy_recipe.skills,
            lock=cp.bpo.lock,
        )

    def trial_jobs(self, bp_id: TypeId, k_spread: int | None, k_copy: int) -> list[WorkJob]:
        """All manufacturing and auto-copy jobs of one blueprint for the given spread and BPO
        split, for timing only: item dependencies are left in `dep_items` for the caller."""
        lay = self.layouts[bp_id]
        specs, parts, per_copy, _, _ = self.layout_specs(lay, k_spread, k_copy)
        specs = self.split_long(lay.prod, specs, lay.time_mult, [])
        copies = []
        if lay.cp is not None:
            copies = [self.copy_work(bp_id, n, lay.cp, per_copy, x) for n, x in enumerate(parts, 1)]
        dep_items = {m.type_id for m in lay.prod.recipe.materials}
        out = list(copies)
        for i, sp in enumerate(specs, 1):
            job_id = f"{lay.prod.activity.value}:{bp_id}:{i}"
            work = self.mfg_work(lay.prod, sp, job_id, lay.time_mult, dep_items)
            if sp.source in (BlueprintSource.BPO, BlueprintSource.COPY):
                work.depends_on.extend(j.job_id for j in copies)
            if sp.source == BlueprintSource.INVENTION:
                work.depends_on.extend(lay.invention_job_ids)
            out.append(work)
        return out

    def extra_materials(self, prod, specs, one_job, mat_mult) -> str:
        """Material used by the split jobs beyond the unsplit BPO jobs, as text."""
        extra: dict[TypeId, int] = defaultdict(int)
        for sign, group in ((1, specs), (-1, one_job)):
            for sp in group:
                for m in f.job_materials(prod.recipe.materials, sp.runs, sp.me, mat_mult):
                    extra[m.type_id] += sign * m.quantity
        extra = {t: q for t, q in extra.items() if q > 0}
        if not extra:
            return ""
        units = sum(extra.values())
        prices = [self.price(t) for t in extra]
        if all(p is not None for p in prices):
            isk = sum(q * (self.price(t) or 0.0) for t, q in extra.items())
            return f"{units:,} more units of materials ({isk:,.0f} ISK)"
        return f"{units:,} more units of materials"

    # -- invention -----------------------------------------------------------

    def best_inventor(self, recipe: Recipe):
        enc = next(
            (s.skill_id for s in recipe.skills if s.skill_id in c.ENCRYPTION_SKILL_IDS),
            None,
        )
        sci = tuple(s.skill_id for s in recipe.skills if s.skill_id not in c.ENCRYPTION_SKILL_IDS)
        base = recipe.probability or 0.0
        eligible = [
            ch
            for ch in self.inp.characters
            if Activity.INVENTION in ch.activities and f.skills_met(ch, recipe.skills)
        ]
        best: Character | None = None
        best_p = f.invention_probability(base, None, enc, sci, 1.0)
        for ch in eligible:
            p = f.invention_probability(base, ch, enc, sci, 1.0)
            if best is None or p > best_p:
                best, best_p = ch, p
        if best:
            why = Reason(
                ReasonCode.SCHEDULED,
                f"Chance uses {best.name}, the best of {len(eligible)} eligible inventor(s).",
            )
        else:
            why = Reason(
                ReasonCode.UNSCHEDULED_NO_CHARACTER,
                "No character can invent this; chance uses no skills.",
            )
        return best, enc, sci, why

    def plan_invention(self, t2_bp_id, runs, choice, mat_mult, t2_recipe):
        t1_bp_id, inv = self.invented_from[t2_bp_id]
        inventor, enc, sci, p_reason = self.best_inventor(inv)
        base_p = inv.probability or 0.0
        in_progress = self.inp.started_attempts.get(t2_bp_id, 0)
        datacore_cost = 0.0
        for m in inv.materials:
            datacore_cost += m.quantity * (self.price(m.type_id) or 0.0)

        options: list[tuple[DecryptorOption, Decryptor | None]] = []
        for dec in (None, *self.inp.game.decryptors):
            runs_per = inv.product_quantity + (dec.run_modifier if dec else 0)
            p = f.invention_probability(
                base_p, inventor, enc, sci, dec.probability_multiplier if dec else 1.0
            )
            if runs_per <= 0 or p <= 0:
                continue
            me = c.T2_BASE_ME + (dec.me_modifier if dec else 0)
            te = c.T2_BASE_TE + (dec.te_modifier if dec else 0)
            bpcs = math.ceil(runs / runs_per)
            # Attempts already running for this plan count toward the expected total.
            attempts = max(0, math.ceil(bpcs / p) - in_progress)
            dec_price = (self.price(dec.type_id) or 0.0) if dec else 0.0
            input_cost = attempts * (datacore_cost + dec_price)
            material_cost = 0.0
            for r in _split(runs, runs_per):
                for m in f.job_materials(t2_recipe.materials, r, me, mat_mult):
                    material_cost += m.quantity * (self.price(m.type_id) or 0.0)
            options.append(
                (
                    DecryptorOption(
                        decryptor_type_id=dec.type_id if dec else None,
                        name=dec.name if dec else "No decryptor",
                        probability=p,
                        me=me,
                        te=te,
                        runs_per_bpc=runs_per,
                        bpcs_needed=bpcs,
                        attempts=attempts,
                        invention_input_cost=input_cost,
                        material_cost=material_cost,
                        total_cost=input_cost + material_cost,
                    ),
                    dec,
                )
            )
        if not options:
            self.warn(
                ReasonCode.SOURCE_MISSING,
                f"{self.name(t2_bp_id)}: invention chance is 0; cannot plan invention.",
            )
            return None, [], []

        picked = None
        if choice.decryptor == "none":
            picked = next((o for o in options if o[1] is None), None)
            why = "No decryptor (your choice)."
        elif choice.decryptor != "auto":
            picked = next((o for o in options if o[1] and o[1].type_id == choice.decryptor), None)
            why = "Decryptor set by you."
            if picked is None:
                self.warn(
                    ReasonCode.DECRYPTOR_CHOSEN,
                    f"Decryptor {choice.decryptor} is not available; choosing automatically.",
                )
        if picked is None:
            picked = min(options, key=lambda o: (o[0].total_cost, o[0].attempts))
            opt = picked[0]
            if all(o.total_cost == 0 for o, _ in options):
                text = (
                    f"{opt.name}: no prices for invention inputs or T2 materials, so the "
                    f"fewest attempts ({opt.attempts}) of {len(options)} options."
                )
            else:
                text = (
                    f"{opt.name}: lowest invention inputs ({opt.invention_input_cost:,.0f}) "
                    f"plus direct T2 materials ({opt.material_cost:,.0f}) of {len(options)} options."
                )
            reason = Reason(ReasonCode.DECRYPTOR_AUTO, text)
        else:
            reason = Reason(ReasonCode.DECRYPTOR_CHOSEN, why)
        opt, dec = picked

        # Invention needs T1 copies: each attempt consumes one copy run, and one invention job
        # uses one copy. A copy holds at most the T1 blueprint's max runs, and an invention
        # job at most 500 runs and 30 days (before skills). [client]
        t1 = self.inp.game.blueprints.get(t1_bp_id)
        t1_owned = self.owned.get(t1_bp_id, [])
        t1_bpos = [b for b in t1_owned if not b.is_copy]
        t1_cost_mult = t1.job_cost_multiplier if t1 else 1.0
        t1_mfg = t1.manufacturing.materials if t1 and t1.manufacturing else ()
        inv_station, inv_bonuses, _ = self.choose_station(Activity.INVENTION, None, t1_bp_id)
        inv_cap = f.max_runs(Activity.INVENTION, inv.time_seconds, inv_bonuses.time)
        per_copy = max(1, min(t1.max_production_limit if t1 else 1, inv_cap))

        # T1 copies on hand (not in a job) and copies an open copy job is making are used
        # first, soonest available first; copy jobs make the rest.
        t1_bpcs = sorted(
            (b for b in t1_owned if b.is_copy and b.job_activity_id is None),
            key=lambda b: (b.available_in, -b.runs, b.item_id),
        )
        on_hand: list[tuple[int, OwnedBlueprint]] = []
        left = opt.attempts
        for b in t1_bpcs:
            if left <= 0:
                break
            take = min(b.runs, left)
            on_hand.extend((r, b) for r in _split(take, inv_cap))
            left -= take
        copy_runs = list(_split(left, per_copy)) if left > 0 else []

        job_ids: list[str] = []
        copy_job_ids: list[str] = []
        if copy_runs and t1_bpos and t1 and t1.copying:
            # Same pick as manufacturing, so copying and building share the blueprint's lock.
            t1_bpo = _best_bpo(t1_bpos)
            copy_station, copy_bonuses, _ = self.choose_station(Activity.COPYING, None, t1_bp_id)
            copy_cap = f.max_runs(
                Activity.COPYING, t1.copying.time_seconds * per_copy, copy_bonuses.time
            )
            # Every copy gets `per_copy` runs; the last one may have runs to spare.
            for n, copies in enumerate(_split(len(copy_runs), copy_cap), 1):
                copy_job_id = f"copying:{t1_bp_id}:for:{t2_bp_id}:{n}"
                self.add_job(
                    WorkJob(
                        job_id=copy_job_id,
                        activity=Activity.COPYING,
                        blueprint_type_id=t1_bp_id,
                        runs=per_copy if len(copy_runs) > 1 else copy_runs[0],
                        copies=copies,
                        time_per_run=t1.copying.time_seconds,
                        time_multiplier=copy_bonuses.time,
                        skills=t1.copying.skills,
                        lock=_item_lock(t1_bpo),
                    ),
                    _JobMeta(
                        me=0,
                        te=0,
                        me_reason=Reason(
                            ReasonCode.SOURCE_BPO, "Copy of owned T1 BPO for invention."
                        ),
                        source=BlueprintSource.BPO,
                        station=copy_station,
                        materials=(),
                        product_type_id=t1_bp_id,
                        product_quantity=copies,
                        eiv_materials=t1_mfg,
                        cost_multiplier=copy_bonuses.cost * t1_cost_mult,
                        base_share=c.COST_PERCENTAGE,
                    ),
                )
                copy_job_ids.append(copy_job_id)
            job_ids.extend(copy_job_ids)
        copy_source = BlueprintSource.BPC
        if copy_runs and not copy_job_ids:
            copy_source = BlueprintSource.MISSING
            self.warn(
                ReasonCode.SOURCE_MISSING,
                f"{self.name(t2_bp_id)}: invention needs {left} more T1 copy runs of "
                f"{self.name(t1_bp_id)}; no T1 BPO to copy and T1 BPCs fall short.",
            )

        # (attempts, T1 copy used or None for one a planned copy job makes)
        inv_jobs: list[tuple[int, OwnedBlueprint | None]] = [
            *on_hand,
            *((r, None) for r in copy_runs),
        ]
        for i, (r, used) in enumerate(inv_jobs, 1):
            mats = [Material(m.type_id, m.quantity * r) for m in inv.materials]
            if dec:
                mats.append(Material(dec.type_id, r))
            for m in mats:
                self.decisions.setdefault(
                    m.type_id,
                    (
                        ItemDecision.BUY,
                        Reason(ReasonCode.BUY_INVENTION_INPUT, "Invention input."),
                        None,
                    ),
                )
            job_id = f"invention:{t1_bp_id}:for:{t2_bp_id}:{i}"
            why = f"{r} attempts."
            if used is not None:
                why = f"{r} attempts on a T1 copy. {self.bpc_text(used)}"
            self.add_job(
                WorkJob(
                    job_id=job_id,
                    activity=Activity.INVENTION,
                    blueprint_type_id=t1_bp_id,
                    runs=r,
                    time_per_run=inv.time_seconds,
                    time_multiplier=inv_bonuses.time,
                    skills=inv.skills,
                    depends_on=[] if used is not None else list(copy_job_ids),
                    lock=_item_lock(used) if used is not None else None,
                ),
                _JobMeta(
                    me=0,
                    te=0,
                    me_reason=Reason(ReasonCode.SOURCE_INVENTION, why),
                    source=BlueprintSource.BPC if used is not None else copy_source,
                    station=inv_station,
                    materials=tuple(mats),
                    product_type_id=t2_bp_id,
                    product_quantity=0,
                    # Invention cost is based on the EIV of the T2 product. [client]
                    eiv_materials=t2_recipe.materials,
                    cost_multiplier=inv_bonuses.cost * t1_cost_mult,
                    base_share=c.COST_PERCENTAGE,
                ),
            )
            job_ids.append(job_id)

        dec_note = f"base ME {c.T2_BASE_ME} / TE {c.T2_BASE_TE}"
        if dec:
            dec_note += f" + {dec.name} ({dec.me_modifier:+d} / {dec.te_modifier:+d})"
        specs = [
            _Spec(
                r,
                opt.me,
                opt.te,
                BlueprintSource.INVENTION,
                Reason(ReasonCode.ME_INVENTED, f"Invented BPC: {dec_note}."),
            )
            for r in _split(runs, opt.runs_per_bpc)
        ]
        inv_plan = InventionPlan(
            t1_blueprint_type_id=t1_bp_id,
            decryptor_type_id=dec.type_id if dec else None,
            reason=reason,
            probability=opt.probability,
            probability_reason=p_reason,
            runs_per_bpc=opt.runs_per_bpc,
            bpcs_needed=opt.bpcs_needed,
            attempts=opt.attempts,
            options=tuple(o for o, _ in options),
            attempts_in_progress=in_progress,
        )
        return inv_plan, specs, job_ids

    # -- 4/5. finish -----------------------------------------------------------

    def run(self) -> PlanResult:
        for t in self.build_order():
            self.plan_item(t)

        # BUY items: everything decided but not built.
        for t, (decision, reason, cat) in self.decisions.items():
            if decision != ItemDecision.BUY:
                continue
            # A bought item can still have started units: a job built it for this plan anyway.
            started, used, needed, over = self.cover(t)
            self.item_rows[t] = ItemPlan(
                type_id=t,
                name=self.name(t),
                decision=decision,
                reason=reason,
                line_quantity=self.line_qty[t],
                input_quantity=self.input_qty[t],
                on_hand_used=used,
                produced=0,
                surplus=0,
                to_buy=needed,
                blueprint_type_id=self.producers[t].blueprint_type_id
                if t in self.producers
                else None,
                build_category=cat,
                started=started,
                over_plan=over,
            )

        for job in self.jobs:
            for item in sorted(job.dep_items):
                job.depends_on.extend(self.jobs_by_product.get(item, []))

        total = schedule(self.jobs, self.inp.characters, self.busy)
        self.item_rows = {
            t: row for t, row in self.item_rows.items() if row.line_quantity or row.input_quantity
        }
        jobs = [self.freeze(j) for j in sorted(self.jobs, key=lambda j: (j.start, j.job_id))]
        self.add_copy_fees(jobs)
        shopping = self.shopping_list()
        return PlanResult(
            items=tuple(sorted(self.item_rows.values(), key=lambda i: (i.name, i.type_id))),
            blueprints=tuple(sorted(self.bp_plans, key=lambda b: (b.name, b.type_id))),
            jobs=tuple(jobs),
            shopping_list=shopping,
            costs=self.costs(shopping, jobs),
            total_seconds=total,
            warnings=tuple(self.warnings),
        )

    def add_copy_fees(self, jobs: list[PlannedJob]) -> None:
        """Fees are known only after scheduling (alpha tax depends on who runs the job), so
        the auto-copy fee is added to the blueprint's reason here."""
        fees = {j.job_id: j.cost.fee for j in jobs}
        for i, b in enumerate(self.bp_plans):
            ids = self.copy_job_ids.get(b.type_id)
            if not ids:
                continue
            parts = [fees[x] for x in ids]
            fee = "unknown" if None in parts else f"{sum(p or 0.0 for p in parts):,.0f} ISK"
            text = b.source_reason.text.removesuffix(".") + f"; copy job fee {fee}."
            self.bp_plans[i] = replace(b, source_reason=Reason(b.source_reason.code, text))

    def freeze(self, job: WorkJob) -> PlannedJob:
        meta = self.meta[job.job_id]
        return PlannedJob(
            job_id=job.job_id,
            activity=job.activity,
            blueprint_type_id=job.blueprint_type_id,
            runs=job.runs,
            me=meta.me,
            te=meta.te,
            me_reason=meta.me_reason,
            source=meta.source,
            station_id=meta.station.station_id if meta.station else None,
            materials=meta.materials,
            product_type_id=meta.product_type_id,
            product_quantity=meta.product_quantity,
            depends_on=tuple(job.depends_on),
            cost=self.job_cost(job, meta),
            schedule=ScheduledSlot(
                character_id=job.character.character_id if job.character else None,
                start_seconds=job.start,
                end_seconds=job.end,
                reason=job.schedule_reason,
            ),
            copies=job.copies if job.activity == Activity.COPYING else 0,
        )

    def job_cost(self, job: WorkJob, meta: _JobMeta) -> JobCost:
        """Install cost split as in the client (industry/job.py). Copying uses the T1
        product's EIV x 2% x runs per copy x copies; invention the T2 product's EIV x 2% x
        attempts."""
        eiv = f.estimated_item_value(meta.eiv_materials, job.runs * job.copies, self.adjusted())
        station = meta.station
        if station is None:
            return JobCost(
                eiv,
                None,
                Reason(ReasonCode.FEE_NOT_MODELLED, "No station; fee unknown."),
            )
        system = self.inp.systems.get(station.system_id)
        index = system.cost_indices.get(job.activity, 0.0) if system else 0.0
        alpha = bool(job.character and job.character.is_alpha)
        safe = f.is_safe_sec(system.security if system else None)
        fee = f.job_fee(
            eiv * meta.base_share, index, meta.cost_multiplier, station.facility_tax, alpha, safe
        )
        share = "" if meta.base_share == 1.0 else f" x {meta.base_share:.0%}"
        text = (
            f"Base {fee.base:,} (EIV {eiv:,.0f}{share}): job cost {fee.job_cost:,} "
            f"(SCI {index:.4f} x modifiers {meta.cost_multiplier:.4f}"
            + (f" + alpha {c.ALPHA_CLONE_TAX:.2%}" if alpha else "")
            + f"), tax {fee.facility_tax:,} ({station.facility_tax}%), "
            f"SCC {fee.scc_surcharge:,} ({c.SCC_SURCHARGE:.0%})"
            + (f", safe-sec tax {fee.security_tax:,}" if safe else "")
            + "."
        )
        return JobCost(
            eiv,
            float(fee.total),
            Reason(ReasonCode.FEE_COMPUTED, text),
            base=float(fee.base),
            job_cost=float(fee.job_cost),
            facility_tax=float(fee.facility_tax),
            scc_surcharge=float(fee.scc_surcharge),
            security_tax=float(fee.security_tax),
        )

    def shopping_list(self) -> tuple[ShoppingItem, ...]:
        out = []
        for row in self.item_rows.values():
            if row.decision != ItemDecision.BUY or row.to_buy <= 0:
                continue
            unit = self.price(row.type_id)
            out.append(
                ShoppingItem(
                    type_id=row.type_id,
                    name=row.name,
                    quantity=row.to_buy,
                    unit_price=unit,
                    total_price=unit * row.to_buy if unit is not None else None,
                    reason=row.reason,
                    volume=self.volume(row.type_id) * row.to_buy,
                )
            )
        # Extra BPOs are on the market; bought BPCs are not (contracts), so only BPOs go here.
        for kind, bp_id, count, unit in self.purchases:
            if kind == "bpo":
                out.append(
                    ShoppingItem(
                        type_id=bp_id,
                        name=self.name(bp_id),
                        quantity=count,
                        unit_price=unit,
                        total_price=unit * count if unit is not None else None,
                        reason=Reason(ReasonCode.BUY_BLUEPRINT, "Extra BPO (your choice)."),
                        volume=self.volume(bp_id) * count,
                    )
                )
        return tuple(sorted(out, key=lambda s: (s.name, s.type_id)))

    def costs(self, shopping, jobs) -> CostSummary:
        materials = invention = blueprints = 0.0
        unpriced = []
        for s in shopping:
            if s.total_price is None:
                unpriced.append(s.type_id)
            elif s.reason.code == ReasonCode.BUY_INVENTION_INPUT:
                invention += s.total_price
            elif s.reason.code == ReasonCode.BUY_BLUEPRINT:
                blueprints += s.total_price
            else:
                materials += s.total_price
        for kind, bp_id, count, unit in self.purchases:
            if kind != "bpc":
                continue
            if unit is None:
                self.warn(
                    ReasonCode.PRICE_MISSING,
                    f"{self.name(bp_id)}: no price set for the {count} bought BPC(s); "
                    "left out of totals.",
                )
            else:
                blueprints += unit * count
        fees: dict[Activity, float] = defaultdict(float)
        for j in jobs:
            if j.cost.fee is not None:
                fees[j.activity] += j.cost.fee
        if unpriced:
            self.warn(
                ReasonCode.PRICE_MISSING,
                f"{len(unpriced)} shopping item(s) have no price and are left out of totals.",
            )
        return CostSummary(
            materials=materials,
            invention_inputs=invention,
            job_fees=dict(fees),
            blueprints=blueprints,
            total=materials + invention + blueprints + sum(fees.values()),
            unpriced_type_ids=tuple(sorted(unpriced)),
        )


def _search_parallel(
    base: _Planner,
) -> tuple[dict[TypeId, int], dict[TypeId, int], dict[TypeId, float]]:
    """Greedy search over the base plan's blueprints, longest first, on two settings each:
    how many owned BPCs to spread the runs over (from the fewest + 1 up), and how many ways
    to split an owned BPO with copies (2, 3, ...); both at most the total manufacturing
    slots. Each setting stops after two tries in a row that do not beat the best so far. A
    change is kept if the plan finishes at least MIN_SPLIT_GAIN sooner, or if the blueprint's
    own jobs do without the plan finishing later: two blueprints that end together only
    shorten the plan when both change. Repeats while a pass changes something (at most 3
    passes), then drops every setting whose removal would cost the plan less than
    MIN_SPLIT_GAIN. Options are timed by re-scheduling only.
    Returns (BPCs to spread over, BPO splits, seconds the plan would lose without each
    blueprint's settings)."""
    slots = sum(
        f.slots(ch, Activity.MANUFACTURING)
        for ch in base.inp.characters
        if Activity.MANUFACTURING in ch.activities
    )
    if slots < 2:
        return {}, {}, {}
    can_spread = {
        bp_id: lay
        for bp_id, lay in base.layouts.items()
        if lay.pool_need > 0 and len(lay.pool) > lay.k_min
    }
    if not can_spread and not base.copy_plans:
        return {}, {}, {}
    old_ids: dict[TypeId, list[str]] = defaultdict(list)
    length: dict[TypeId, float] = defaultdict(float)
    for j in base.jobs:
        lay = base.layouts.get(j.blueprint_type_id)
        if lay is not None and j.activity == lay.prod.activity:
            old_ids[j.blueprint_type_id].append(j.job_id)
            length[j.blueprint_type_id] += j.duration(None)

    def total(
        spread: dict[TypeId, int], parallel: dict[TypeId, int], bp: TypeId | None = None
    ) -> tuple[float, float]:
        """(plan finish, finish of blueprint `bp`'s manufacturing jobs)."""
        new: list[WorkJob] = []
        mapping: dict[str, list[str]] = {}
        for bp_id in set(spread) | set(parallel):
            jobs = base.trial_jobs(bp_id, spread.get(bp_id), parallel.get(bp_id, 1))
            new.extend(jobs)
            ids = [j.job_id for j in jobs if j.activity != Activity.COPYING]
            for old in old_ids[bp_id]:
                mapping[old] = ids

        def expand(ids):
            return list(dict.fromkeys(x for i in ids for x in mapping.get(i, [i])))

        jobs = [
            replace(j, depends_on=expand(j.depends_on))
            for j in base.jobs
            if j.job_id not in mapping
        ]
        for j in new:
            deps = list(j.depends_on)
            for item in sorted(j.dep_items):
                deps.extend(base.jobs_by_product.get(item, []))
            jobs.append(replace(j, depends_on=expand(deps)))
        finish = schedule(jobs, base.inp.characters, base.busy)
        mine = [j.end for j in jobs if j.blueprint_type_id == bp and j.activity != Activity.COPYING]
        return finish, max(mine, default=0.0)

    spread: dict[TypeId, int] = {}
    parallel: dict[TypeId, int] = {}
    best = total(spread, parallel)[0]

    def improve(bp_id, values, attempt) -> int | None:
        """Try `values` in order through `attempt(k) -> (plan finish, blueprint finish)`."""
        nonlocal best
        _, own0 = total(spread, parallel, bp_id)
        best_k, best_key, misses = None, (best, own0), 0
        for k in values:
            key = attempt(k)
            if key < best_key:
                best_k, best_key, misses = k, key, 0
            else:
                misses += 1
                if misses >= 2:
                    break
        if best_k is None or best_key[0] > best:
            return None
        if best_key[0] <= best - MIN_SPLIT_GAIN or best_key[1] <= own0 - MIN_SPLIT_GAIN:
            best = best_key[0]
            return best_k
        return None

    order = sorted(base.layouts, key=lambda bp_id: (-length[bp_id], bp_id))
    for _ in range(3):
        changed = False
        for bp_id in order:
            lay = can_spread.get(bp_id)
            if lay is not None:
                k0 = spread.get(bp_id, lay.k_min)
                k = improve(
                    bp_id,
                    range(k0 + 1, min(len(lay.pool), slots) + 1),
                    lambda k, b=bp_id: total({**spread, b: k}, parallel, b),
                )
                if k is not None:
                    spread[bp_id], changed = k, True
            cp = base.copy_plans.get(bp_id)
            if cp is not None:
                k0 = parallel.get(bp_id, 1)
                k = improve(
                    bp_id,
                    range(k0 + 1, min(cp.runs, slots) + 1),
                    lambda k, b=bp_id: total(spread, {**parallel, b: k}, b),
                )
                if k is not None:
                    parallel[bp_id], changed = k, True
        if not changed:
            break

    def without(bp_id) -> float:
        return total(
            {b: k for b, k in spread.items() if b != bp_id},
            {b: k for b, k in parallel.items() if b != bp_id},
        )[0]

    # Drop settings that do not pay for themselves in plan time, weakest first.
    while True:
        best = total(spread, parallel)[0]
        saved = {bp_id: without(bp_id) - best for bp_id in set(spread) | set(parallel)}
        weak = [b for b, v in saved.items() if v < MIN_SPLIT_GAIN]
        if not weak:
            break
        drop = min(weak, key=lambda b: (saved[b], b))
        spread.pop(drop, None)
        parallel.pop(drop, None)
    return spread, parallel, saved


def _duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    d, rest = divmod(minutes, 24 * 60)
    h, m = divmod(rest, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _job_note(b: OwnedBlueprint) -> str:
    activity = c.JOB_ACTIVITY_NAMES.get(b.job_activity_id or 0, "an industry")
    if b.job_ends_in <= 0:
        return f"the BPO is in a finished {activity} job: deliver it before these jobs start"
    return f"the BPO is in a {activity} job for {_duration(b.job_ends_in)}; these jobs start after"


def _sentence(text: str) -> str:
    """First letter upper case, the rest as written (str.capitalize lowercases "BPO")."""
    return text[:1].upper() + text[1:] + "."


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _best_bpo(bpos: list[OwnedBlueprint]) -> OwnedBlueprint:
    return max(bpos, key=lambda b: (b.me, b.te, -b.item_id))


def _item_lock(b: OwnedBlueprint) -> str:
    return f"item:{b.item_id}"


def _water_fill(caps: list[int], need: int) -> list[int]:
    """Share `need` runs over BPCs holding `caps` runs: each gets min(cap, level) for the
    lowest level that covers the need, trimmed by one from the last full shares."""
    lo, hi = 1, max(caps)
    while lo < hi:
        mid = (lo + hi) // 2
        if sum(min(c, mid) for c in caps) >= need:
            hi = mid
        else:
            lo = mid + 1
    out = [min(c, lo) for c in caps]
    excess = sum(out) - need
    for i in reversed(range(len(out))):
        if excess <= 0:
            break
        if out[i] == lo:
            out[i] -= 1
            excess -= 1
    return out


def _even(total: int, parts: int) -> list[int]:
    """`total` split into `parts` sizes differing by at most one, largest first."""
    base, rest = divmod(total, parts)
    return [base + 1] * rest + [base] * (parts - rest)


def _split(total: int, size: int):
    """Split `total` runs into chunks of at most `size`."""
    full, rest = divmod(total, size)
    yield from [size] * full
    if rest:
        yield rest
