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

from collections import defaultdict
from dataclasses import dataclass, field

from apps.accounts.models import User
from apps.sde import gamedata
from engine import PlanError, plan
from engine.types import (
    BlueprintChoice,
    BuildCategory,
    BuildRules,
    GameData,
    PlanInput,
    PlanResult,
    Price,
)
from engine.types import Character as EngineCharacter
from engine.types import OwnedBlueprint as EngineBlueprint
from engine.types import PlanLine as EnginePlanLine
from engine.types import SolarSystem as EngineSystem
from engine.types import Station as EngineStation

from . import inputs, tracker
from .inputs import AssetBucket
from .models import Plan, PlanLine
from .stations import engine_station


@dataclass
class AccountData:
    """Everything a plan run needs that does not depend on the plan."""

    game: GameData
    stations: dict[int, EngineStation]  # by Station pk
    station_locations: dict[int, int | None]  # Station pk -> structure / NPC station id
    systems: dict[int, EngineSystem]
    characters: tuple[EngineCharacter, ...]
    blueprints: tuple[EngineBlueprint, ...]
    prices: dict[int, Price]
    default_rules: BuildRules
    buckets: dict[AssetBucket, int]
    # BPC item id -> the plan whose line picked it; other plans do not see it.
    picked: dict[int, int] = field(default_factory=dict)
    # Copies open copy jobs are making, with the plan the job is linked to (None: any plan).
    incoming: list[tuple[EngineBlueprint, int | None]] = field(default_factory=list)


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


def load(user: User) -> AccountData:
    rows = list(user.stations.filter(enabled=True))
    return AccountData(
        game=gamedata.game_data(),
        stations={s.pk: engine_station(s) for s in rows},
        station_locations={s.pk: s.location_id for s in rows},
        systems=inputs.systems(s.system_id for s in rows),
        characters=inputs.characters(user),
        blueprints=inputs.owned_blueprints(user),
        prices=inputs.prices(),
        default_rules=inputs.build_rules(user),
        buckets=inputs.asset_buckets(user),
        picked=picked_blueprints(user),
        incoming=inputs.incoming_copies(user),
    )


def picked_blueprints(user: User) -> dict[int, int]:
    out: dict[int, int] = {}
    for plan_id, ids in (
        PlanLine.objects.filter(plan__user=user)
        .exclude(blueprint_item_ids=[])
        .values_list("plan_id", "blueprint_item_ids")
    ):
        for item_id in ids:
            out.setdefault(item_id, plan_id)
    return out


def effective_rules(default: BuildRules, p: Plan) -> BuildRules:
    blacklist = (set(default.item_blacklist) | {int(t) for t in p.blacklist_add}) - {
        int(t) for t in p.blacklist_remove
    }
    buy = set(default.buy_categories)
    for cat, mode in (p.category_overrides or {}).items():
        if mode == "buy":
            buy.add(BuildCategory(cat))
        elif mode == "build":
            buy.discard(BuildCategory(cat))
    return BuildRules(item_blacklist=frozenset(blacklist), buy_categories=frozenset(buy))


def plan_stations(p: Plan, data: AccountData) -> list[int]:
    if p.station_ids:
        return [sid for sid in p.station_ids if sid in data.stations]
    return list(data.stations)


def plan_scope(p: Plan, data: AccountData) -> tuple[set[int], set[str] | None]:
    """(locations whose stock counts, hangar flags that count or None for all)."""
    locations = {
        data.station_locations[sid]
        for sid in plan_stations(p, data)
        if data.station_locations.get(sid) is not None
    }
    locations |= {int(loc) for loc in p.extra_location_ids}
    flags = set(p.hangar_flags) if p.hangar_flags else None
    return locations, flags


def _in_scope(bucket: AssetBucket, locations: set[int], flags: set[str] | None) -> bool:
    _, loc, flag = bucket
    return loc in locations and (flags is None or flag in flags)


def _choices(p: Plan) -> dict[int, BlueprintChoice]:
    out = {}
    for bp_id, c in (p.choices or {}).items():
        dec = c.get("decryptor", "auto")
        out[int(bp_id)] = BlueprintChoice(
            me_override=c.get("me"),
            te_override=c.get("te"),
            decryptor=dec if dec in ("auto", "none") else int(dec),
            buy_bpcs=c.get("buy_bpcs", 0),
            bpc_runs=c.get("bpc_runs"),
            bpc_me=c.get("bpc_me", 10),
            bpc_te=c.get("bpc_te", 20),
            bpc_price=c.get("bpc_price"),
            extra_bpos=c.get("extra_bpos", 0),
            bpo_me=c.get("bpo_me", 0),
            bpo_te=c.get("bpo_te", 0),
        )
    return out


def plan_input(
    p: Plan, data: AccountData, pool: dict[AssetBucket, int], incoming: bool = True
) -> PlanInput:
    """`incoming`: include copies open copy jobs are making (those linked to this plan or to
    no plan). Off for the tracker's base run, which must still plan the copy jobs."""
    locations, flags = plan_scope(p, data)
    assets: dict[int, int] = defaultdict(int)
    for bucket, qty in pool.items():
        if qty > 0 and _in_scope(bucket, locations, flags):
            assets[bucket[0]] += qty
    stations = plan_stations(p, data)
    started, started_attempts = tracker.progress_inputs(p, data.game)
    return PlanInput(
        lines=tuple(
            EnginePlanLine(str(ln.pk), ln.type_id, ln.quantity, tuple(ln.blueprint_item_ids))
            for ln in p.lines.all()
        ),
        game=data.game,
        stations=tuple(data.stations[s] for s in stations),
        systems=data.systems,
        characters=data.characters,
        blueprints=(
            *(b for b in data.blueprints if data.picked.get(b.item_id, p.pk) == p.pk),
            *(b for b, plan_id in data.incoming if incoming and plan_id in (None, p.pk)),
        ),
        assets=dict(assets),
        prices=data.prices,
        rules=effective_rules(data.default_rules, p),
        choices=_choices(p),
        started=started,
        started_attempts=started_attempts,
    )


def _claim(
    pool: dict[AssetBucket, int],
    used: dict[int, int],
    locations: set[int],
    flags: set[str] | None,
) -> dict[AssetBucket, int]:
    taken: dict[AssetBucket, int] = {}
    for bucket in sorted(b for b in pool if _in_scope(b, locations, flags)):
        need = used.get(bucket[0], 0)
        if need <= 0 or pool[bucket] <= 0:
            continue
        take = min(need, pool[bucket])
        pool[bucket] -= take
        used[bucket[0]] = need - take
        taken[bucket] = take
    return taken


def _run(p: Plan, data: AccountData, pool: dict[AssetBucket, int]) -> PlanRun:
    inp = plan_input(p, data, pool)
    rules = inp.rules
    if not inp.lines:
        return PlanRun(p, inp, None, "plan has no lines", rules)
    try:
        return PlanRun(p, inp, plan(inp), rules=rules)
    except PlanError as exc:
        return PlanRun(p, inp, None, str(exc), rules)


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
                if _in_scope(bucket, locations, flags):
                    h = held[bucket[0]].setdefault(other.pk, Holder(other.pk, other.name, 0))
                    h.quantity += qty
        run.held_elsewhere = {t: list(hs.values()) for t, hs in held.items()}

    for p in [p for p in all_plans if p.reserve_assets]:  # ordered by priority, id
        run = _run(p, data, pool)
        holders(p, run)
        taken: dict[AssetBucket, int] = {}
        if run.result is not None:
            used = {i.type_id: i.on_hand_used for i in run.result.items if i.on_hand_used}
            locations, flags = plan_scope(p, data)
            taken = _claim(pool, used, locations, flags)
            for (type_id, _, _), qty in taken.items():
                run.claims[type_id] = run.claims.get(type_id, 0) + qty
        ledger.append((p, taken))
        runs[p.pk] = run

    for p in all_plans:
        if p.reserve_assets or p.pk not in wanted:
            continue
        run = _run(p, data, pool)
        holders(p, run)
        runs[p.pk] = run
    return {pid: r for pid, r in runs.items() if pid in wanted}
