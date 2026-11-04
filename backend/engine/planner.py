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
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

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


def plan(inp: PlanInput) -> PlanResult:
    return _Planner(inp).run()


@dataclass(frozen=True)
class _Producer:
    blueprint_type_id: TypeId
    activity: Activity
    recipe: Recipe


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
    def __init__(self, inp: PlanInput):
        self.inp = inp
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
        for ob in inp.blueprints:
            self.owned[ob.type_id].append(ob)

        self.line_qty: dict[TypeId, int] = defaultdict(int)
        for line in inp.lines:
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
        bpcs = sorted((b for b in owned if b.is_copy), key=lambda b: (-b.me, -b.te, b.item_id))
        is_reaction = prod.activity == Activity.REACTION

        # (runs, me, te, source, me_reason)
        specs: list[tuple[int, int, int, BlueprintSource, Reason]] = []
        source_notes: list[str] = []
        invention: InventionPlan | None = None
        invention_job_ids: list[str] = []
        remaining = runs

        def me_reason(code: ReasonCode, text: str) -> Reason:
            if is_reaction:
                return Reason(ReasonCode.ME_REACTION, "Reaction formulas have no ME/TE.")
            return Reason(code, text)

        if bpos:
            b = max(bpos, key=lambda b: (b.me, b.te, -b.item_id))
            specs.append(
                (
                    runs,
                    b.me,
                    b.te,
                    BlueprintSource.BPO,
                    me_reason(
                        ReasonCode.ME_OWNED_BPO,
                        f"Owned BPO ME {b.me} / TE {b.te} (best of {len(bpos)}).",
                    ),
                )
            )
            source_notes.append("owned BPO")
            remaining = 0
        else:
            for b in bpcs:
                if remaining <= 0:
                    break
                take = min(b.runs, remaining)
                if take <= 0:
                    continue
                specs.append(
                    (
                        take,
                        b.me,
                        b.te,
                        BlueprintSource.BPC,
                        me_reason(
                            ReasonCode.ME_OWNED_BPC,
                            f"Owned BPC {b.item_id}: ME {b.me} / TE {b.te}, {b.runs} runs.",
                        ),
                    )
                )
                remaining -= take
            if specs:
                source_notes.append(f"{len(specs)} owned BPC(s) cover {runs - remaining} runs")

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
                (
                    remaining,
                    0,
                    0,
                    BlueprintSource.MISSING,
                    me_reason(
                        ReasonCode.ME_MISSING_BLUEPRINT,
                        "No owned blueprint; planned at ME 0 / TE 0 until you add one.",
                    ),
                )
            )
            source_notes.append(f"{remaining} runs need a blueprint you do not own")
            self.warn(
                ReasonCode.SOURCE_MISSING,
                f"{self.name(bp_id)}: no owned blueprint for {remaining} runs.",
            )

        if not is_reaction and (choice.me_override is not None or choice.te_override is not None):
            overridden = []
            for r, me, te, src, why in specs:
                new_me = choice.me_override if choice.me_override is not None else me
                new_te = choice.te_override if choice.te_override is not None else te
                why = Reason(
                    ReasonCode.ME_OVERRIDE,
                    f"ME {new_me} / TE {new_te} set by you (blueprint gives ME {me} / TE {te}).",
                )
                overridden.append((r, new_me, new_te, src, why))
            specs = overridden

        # Jobs on an original (BPO, reaction formula, or a BPO you do not own yet) may not
        # run longer than 30 days; copies are limited only by their runs. [client]
        split_specs = []
        for r, me, te, src, why in specs:
            if src in (BlueprintSource.BPO, BlueprintSource.MISSING):
                te_factor = 1.0 if is_reaction else 1 - te / 100
                cap = f.max_runs(prod.activity, prod.recipe.time_seconds, te_factor * time_mult)
                if r > cap:
                    source_notes.append(
                        f"split into jobs of at most {cap} runs (30-day job limit, before skills)"
                    )
                split_specs.extend((chunk, me, te, src, why) for chunk in _split(r, cap))
            else:
                split_specs.append((r, me, te, src, why))
        specs = split_specs
        bp_data = self.inp.game.blueprints.get(bp_id)
        bp_cost_mult = bp_data.job_cost_multiplier if bp_data else 1.0

        job_ids = []
        for i, (r, me, te, src, why) in enumerate(specs, 1):
            job_id = f"{prod.activity.value}:{bp_id}:{i}"
            mats = f.job_materials(prod.recipe.materials, r, me, mat_mult)
            te_factor = 1.0 if is_reaction else 1 - te / 100
            work = WorkJob(
                job_id=job_id,
                activity=prod.activity,
                blueprint_type_id=bp_id,
                runs=r,
                time_per_run=prod.recipe.time_seconds,
                time_multiplier=te_factor * time_mult,
                skills=prod.recipe.skills,
                dep_items={m.type_id for m in mats},
                skill_time_bonuses=self.inp.game.skill_time_bonuses,
            )
            if src == BlueprintSource.INVENTION:
                work.depends_on.extend(invention_job_ids)
            self.add_job(
                work,
                _JobMeta(
                    me=me,
                    te=te,
                    me_reason=why,
                    source=src,
                    station=station,
                    materials=mats,
                    product_type_id=product_type_id,
                    product_quantity=r * (prod.recipe.product_quantity or 1),
                    eiv_materials=prod.recipe.materials,
                    cost_multiplier=bonuses.cost * bp_cost_mult,
                ),
            )
            job_ids.append(job_id)

        sources = tuple(dict.fromkeys(s[3] for s in specs))
        code = {
            BlueprintSource.BPO: ReasonCode.SOURCE_BPO,
            BlueprintSource.BPC: ReasonCode.SOURCE_BPC,
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
                source_reason=Reason(code, "; ".join(source_notes).capitalize() + "."),
                station=station_choice,
                job_ids=tuple(job_ids + invention_job_ids),
                invention=invention,
            )
        )

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
        copy_runs = list(_split(opt.attempts, per_copy))
        job_ids: list[str] = []
        copy_job_ids: list[str] = []
        if t1_bpos and t1 and t1.copying:
            copy_station, copy_bonuses, _ = self.choose_station(Activity.COPYING, None, t1_bp_id)
            copy_cap = f.max_runs(Activity.COPYING, t1.copying.time_seconds, copy_bonuses.time)
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
        t1_source = BlueprintSource.BPC
        if not copy_job_ids and sum(b.runs for b in t1_owned if b.is_copy) < opt.attempts:
            t1_source = BlueprintSource.MISSING
            self.warn(
                ReasonCode.SOURCE_MISSING,
                f"{self.name(t2_bp_id)}: invention needs {opt.attempts} T1 copy runs of "
                f"{self.name(t1_bp_id)}; no T1 BPO to copy and owned T1 BPCs fall short.",
            )

        for i, r in enumerate(copy_runs, 1):
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
            self.add_job(
                WorkJob(
                    job_id=job_id,
                    activity=Activity.INVENTION,
                    blueprint_type_id=t1_bp_id,
                    runs=r,
                    time_per_run=inv.time_seconds,
                    time_multiplier=inv_bonuses.time,
                    skills=inv.skills,
                    depends_on=list(copy_job_ids),
                ),
                _JobMeta(
                    me=0,
                    te=0,
                    me_reason=Reason(ReasonCode.SOURCE_INVENTION, f"{r} attempts."),
                    source=t1_source,
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
            (
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

        total = schedule(self.jobs, self.inp.characters)
        self.item_rows = {
            t: row for t, row in self.item_rows.items() if row.line_quantity or row.input_quantity
        }
        jobs = [self.freeze(j) for j in sorted(self.jobs, key=lambda j: (j.start, j.job_id))]
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
                )
            )
        return tuple(sorted(out, key=lambda s: (s.name, s.type_id)))

    def costs(self, shopping, jobs) -> CostSummary:
        materials = invention = 0.0
        unpriced = []
        for s in shopping:
            if s.total_price is None:
                unpriced.append(s.type_id)
            elif s.reason.code == ReasonCode.BUY_INVENTION_INPUT:
                invention += s.total_price
            else:
                materials += s.total_price
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
            total=materials + invention + sum(fees.values()),
            unpriced_type_ids=tuple(sorted(unpriced)),
        )


def _split(total: int, size: int):
    """Split `total` runs into chunks of at most `size`."""
    full, rest = divmod(total, size)
    yield from [size] * full
    if rest:
        yield rest
