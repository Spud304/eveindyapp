"""Opt-in purchase options for one blueprint: buy BPCs, or an extra BPO.

Each option is the whole plan computed again with that purchase added to the blueprint's
`BlueprintChoice`, so the time saved is the scheduler's finish time and the cost change is the
plan's own totals (materials, fees) moving, not a separate formula. Computed on request only:
one plan run per candidate."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

from . import formulas as f
from .planner import _duration, plan
from .types import Activity, BlueprintChoice, PlanInput, PlanResult, Reason, ReasonCode, TypeId

MAX_BPCS = 20  # most bought BPCs one option suggests


@dataclass(frozen=True, slots=True)
class PurchaseOption:
    kind: Literal["bpcs", "bpo"]
    count: int  # added on top of what the choice already buys
    runs_per_bpc: int | None  # bpcs only
    me: int
    te: int
    total_seconds: float  # plan finish with this purchase
    seconds_saved: float
    cost_change: float  # change in materials and fees, without the purchase itself
    purchase_cost: float | None  # None: no price (BPCs sell on contracts; set one)
    choice: BlueprintChoice  # the blueprint's choice with this purchase, to save
    reason: Reason


@dataclass(frozen=True, slots=True)
class BlueprintOptions:
    blueprint_type_id: TypeId
    total_seconds: float  # plan finish with the current choices
    options: tuple[PurchaseOption, ...]
    note: str = ""  # why there are no options, when there are none


def purchase_options(
    inp: PlanInput, bp_id: TypeId, base: PlanResult | None = None
) -> BlueprintOptions:
    base = base or plan(inp)
    bp = next((b for b in base.blueprints if b.type_id == bp_id), None)
    if bp is None or bp.activity != Activity.MANUFACTURING:
        return BlueprintOptions(bp_id, base.total_seconds, (), "Only manufacturing blueprints.")
    data = inp.game.blueprints.get(bp_id)
    current = inp.choices.get(bp_id, BlueprintChoice())
    slots = sum(
        f.slots(ch, Activity.MANUFACTURING)
        for ch in inp.characters
        if Activity.MANUFACTURING in ch.activities
    )

    def run(choice: BlueprintChoice) -> PlanResult:
        return plan(replace(inp, choices={**inp.choices, bp_id: choice}))

    def option(kind, count, runs, me, te, choice, result, purchase) -> PurchaseOption:
        saved = base.total_seconds - result.total_seconds
        cost = (result.costs.total - result.costs.blueprints) - (
            base.costs.total - base.costs.blueprints
        )
        what = (
            f"Buy {count} BPC(s) of {runs} runs (ME {me} / TE {te})"
            if kind == "bpcs"
            else f"Buy {count} extra BPO (ME {me} / TE {te})"
        )
        when = f"finishes {_duration(saved)} sooner" if saved > 0 else "does not finish sooner"
        price = f"{purchase:,.0f} ISK" if purchase is not None else "price not set"
        text = f"{what}: the plan {when}; materials and fees {cost:+,.0f} ISK; {price}."
        return PurchaseOption(
            kind,
            count,
            runs,
            me,
            te,
            result.total_seconds,
            saved,
            cost,
            purchase,
            choice,
            Reason(ReasonCode.SOURCE_BOUGHT, text),
        )

    options = []
    max_runs = data.max_production_limit if data else 1
    best = None
    misses = 0
    for n in range(1, min(MAX_BPCS, max(slots, 1), bp.runs) + 1):
        total = current.buy_bpcs + n
        runs = current.bpc_runs or max(1, min(max_runs, math.ceil(bp.runs / (total + 1))))
        choice = replace(current, buy_bpcs=total, bpc_runs=runs)
        result = run(choice)
        if best is None or result.total_seconds < best[2].total_seconds:
            best, misses = (n, choice, result), 0
        else:
            misses += 1
            if misses >= 2:
                break
    if best is not None:
        n, choice, result = best
        price = n * current.bpc_price if current.bpc_price is not None else None
        options.append(
            option("bpcs", n, choice.bpc_runs, choice.bpc_me, choice.bpc_te, choice, result, price)
        )

    # T2 originals are not sold, so no extra BPO for blueprints made by invention.
    invented = any(
        inv.product_type_id == bp_id for b in inp.game.blueprints.values() for inv in b.invention
    )
    if not invented:
        choice = replace(current, extra_bpos=current.extra_bpos + 1)
        p = inp.prices.get(bp_id)
        options.append(
            option(
                "bpo",
                1,
                None,
                choice.bpo_me,
                choice.bpo_te,
                choice,
                run(choice),
                p.unit_price if p else None,
            )
        )
    return BlueprintOptions(bp_id, base.total_seconds, tuple(options))
