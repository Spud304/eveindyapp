"""Run an account's plans with asset reservation.

Reservations are computed, not stored. Plans with `reserve_assets` run first, in priority
order (lower number first, then id). Each sees the stock left by the plans before it; what
its engine run takes from stock (`ItemPlan.on_hand_used`) becomes its claim and leaves the
pool. Plans without `reserve_assets` then run against what is left and claim nothing, so
they never block each other.

The pool is kept per (item, location, hangar), because plans can build at different
stations and count different hangars. A plan claims only from buckets inside its own
location and hangar filter, in a fixed order (location id, then hangar), so results are
repeatable.

Because claims come from the plan's remaining demand, they shrink on their own once the
tracker (step 5) reduces that demand as jobs start.
"""

import dataclasses
from collections import defaultdict
from dataclasses import dataclass, field

from apps.accounts.models import User
from engine import PlanError, plan
from engine.types import BuildRules, PlanInput, PlanResult, PlanWarning, ReasonCode

from . import tracker
from .inputs import AccountData, AssetBucket, in_scope, load, plan_input, plan_scope
from .models import Plan


@dataclass
class Holder:
    plan_id: int
    plan_name: str
    quantity: int


@dataclass
class PlanRun:
    plan: Plan
    input: PlanInput | None
    result: PlanResult | None
    error: str = ""
    rules: BuildRules | None = None
    # type id -> quantity this plan reserved (reserving plans only)
    claims: dict[int, int] = field(default_factory=dict)
    # type id -> stock in this plan's scope that earlier reserving plans hold
    held_elsewhere: dict[int, list[Holder]] = field(default_factory=dict)
    # The stock in this plan's scope it ran against, per bucket (for the hauling list).
    stock: dict[AssetBucket, int] = field(default_factory=dict)


def _claim(
    pool: dict[AssetBucket, int],
    used: dict[int, int],
    locations: set[int],
    flags: set[str] | None,
) -> dict[AssetBucket, int]:
    taken: dict[AssetBucket, int] = {}
    for bucket in sorted(b for b in pool if in_scope(b, locations, flags)):
        need = used.get(bucket[0], 0)
        if need <= 0 or pool[bucket] <= 0:
            continue
        take = min(need, pool[bucket])
        pool[bucket] -= take
        used[bucket[0]] = need - take
        taken[bucket] = take
    return taken


def _run(
    p: Plan, data: AccountData, pool: dict[AssetBucket, int], bpc_used: dict[int, int]
) -> PlanRun:
    progress = tracker.progress_inputs(p, data.game)
    inp = plan_input(p, data, pool, progress=progress, bpc_used=bpc_used)
    rules = inp.rules
    if not inp.lines:
        return PlanRun(p, inp, None, "plan has no lines", rules)
    try:
        result = plan(inp)
    except PlanError as exc:
        return PlanRun(p, inp, None, str(exc), rules)
    locations, flags = plan_scope(p, data)
    stock = {b: q for b, q in pool.items() if q > 0 and in_scope(b, locations, flags)}
    if lost := tracker.unreadable_links(p):
        warning = PlanWarning(
            ReasonCode.SOURCE_MISSING,
            f"{len(lost)} linked job(s) belong to a character or corporation this account can "
            "no longer read; they still count as started but their status no longer updates. "
            "Unlink them on the Progress tab if they are gone.",
        )
        result = dataclasses.replace(result, warnings=(*result.warnings, warning))
    return PlanRun(p, inp, result, rules=rules, stock=stock)


def run_plans(user: User, plans: list[Plan] | None = None, data: AccountData | None = None):
    """Run every plan of the account (or the given ones; reserving plans always run, since
    they decide what the others see). Returns {plan id: PlanRun}."""
    data = data or load(user)
    all_plans = list(user.plans.prefetch_related("lines"))
    wanted = {p.pk for p in (plans if plans is not None else all_plans)}
    pool = dict(data.buckets)
    ledger: list[tuple[Plan, dict[AssetBucket, int]]] = []
    runs: dict[int, PlanRun] = {}

    def holders(p: Plan, run: PlanRun) -> None:
        locations, flags = plan_scope(p, data)
        held: dict[int, dict[int, Holder]] = defaultdict(dict)
        for other, taken in ledger:
            if other.pk == p.pk:
                break  # only plans that claimed before this one
            for bucket, qty in taken.items():
                if in_scope(bucket, locations, flags):
                    h = held[bucket[0]].setdefault(other.pk, Holder(other.pk, other.name, 0))
                    h.quantity += qty
        run.held_elsewhere = {t: list(hs.values()) for t, hs in held.items()}

    # Reserving plans also take BPC runs, so a later plan cannot count the same runs; BPO
    # time is not divided between plans, so a BPO two of them use is only flagged.
    bpc_used: dict[int, int] = defaultdict(int)
    bpo_users: dict[int, list[str]] = defaultdict(list)

    reserving = [p for p in all_plans if p.reserve_assets]  # ordered by priority, id
    if not any(p.pk in wanted and not p.reserve_assets for p in all_plans):
        # Only reserving plans asked for: the ones after the last of them cannot change it.
        last = max((i for i, p in enumerate(reserving) if p.pk in wanted), default=-1)
        reserving = reserving[: last + 1]

    for p in reserving:
        run = _run(p, data, pool, bpc_used)
        holders(p, run)
        taken: dict[AssetBucket, int] = {}
        if run.result is not None:
            used = {i.type_id: i.on_hand_used for i in run.result.items if i.on_hand_used}
            locations, flags = plan_scope(p, data)
            taken = _claim(pool, used, locations, flags)
            for (type_id, _, _), qty in taken.items():
                run.claims[type_id] = run.claims.get(type_id, 0) + qty
            _take_blueprints(run, bpc_used, bpo_users)
        ledger.append((p, taken))
        runs[p.pk] = run

    for p in all_plans:
        if p.reserve_assets or p.pk not in wanted:
            continue
        run = _run(p, data, pool, bpc_used)
        holders(p, run)
        runs[p.pk] = run
    return {pid: r for pid, r in runs.items() if pid in wanted}


def _take_blueprints(
    run: PlanRun, bpc_used: dict[int, int], bpo_users: dict[int, list[str]]
) -> None:
    """Record the BPC runs a reserving plan's jobs use, and warn when its jobs use a BPO an
    earlier reserving plan also schedules (both plans assume the BPO is free for them)."""
    assert run.input is not None and run.result is not None
    owned = {b.item_id: b for b in run.input.blueprints}
    shared: dict[str, set[str]] = defaultdict(set)
    seen_bpos = set()
    for job in run.result.jobs:
        b = owned.get(job.blueprint_item_id) if job.blueprint_item_id is not None else None
        if b is None:
            continue
        if b.is_copy:
            bpc_used[b.item_id] += job.runs  # invention: one copy run per attempt
        elif b.item_id not in seen_bpos:
            seen_bpos.add(b.item_id)
            for other in bpo_users[b.item_id]:
                shared[other].add(run.input.game.types[b.type_id].name)
            bpo_users[b.item_id].append(run.plan.name)
    if shared:
        warnings = [
            PlanWarning(
                ReasonCode.SOURCE_BPO,
                f"Plan {other} also schedules {', '.join(sorted(names))} from t=0; plans do not "
                "share a BPO's time, so this plan's schedule assumes it is free.",
            )
            for other, names in sorted(shared.items())
        ]
        run.result = dataclasses.replace(run.result, warnings=(*run.result.warnings, *warnings))
