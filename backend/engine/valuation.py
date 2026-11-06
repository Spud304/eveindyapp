"""What goes into each plan line, in ISK: hangar stock used, items to buy, job fees and bought
blueprints, rolled up through the build tree to the line's product.

Every unit of an item carries the average value of all its supply. Stock and bought units are
worth their market price. Built units are worth the jobs that make them: those jobs' material
values, fees and a share of the copy and invention jobs that made their blueprint. Units
already in running jobs (`ItemPlan.started`) are worth what one built unit is worth; their
inputs left the hangars when the job started.

Shared intermediates split by quantity used, so two lines using one component stack pay for
it in proportion. Units built beyond need (`surplus`) and copies or inventions no job uses
carry value too; that is reported as left over, not charged to a line.

Not counted: owned blueprints (originals and copies already in the hangar) and bought extra
BPOs, which are not used up.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from .types import (
    Activity,
    BlueprintSource,
    PlanInput,
    PlannedJob,
    PlanResult,
    TypeId,
)

_PRODUCING = (Activity.MANUFACTURING, Activity.REACTION)
_BLUEPRINT_MAKING = (Activity.COPYING, Activity.INVENTION)

# Value keys; ("su", t) / ("bu", t) count units of t from stock / to buy, ("sv", t) / ("bv", t)
# their ISK, ("nu", t) units of t with no price.
_FEES, _BLUEPRINTS, _STARTED = ("fee",), ("bp",), ("started",)
_ISK = ("sv", "bv", "fee", "bp", "started")

Vec = dict[tuple, float]


@dataclass(frozen=True, slots=True)
class InputValue:
    """One raw input of a line: what comes from stock and what is bought."""

    type_id: TypeId
    name: str
    from_stock: float  # units (fractional when a shared stack is split between lines)
    stock_value: float
    to_buy: float
    buy_value: float


@dataclass(frozen=True, slots=True)
class LineValue:
    line_id: str
    type_id: TypeId
    name: str
    quantity: int
    stock: float  # ISK of hangar stock that goes into it
    bought: float  # ISK of items to buy
    job_fees: float
    blueprints: float  # bought BPCs
    started: float  # units already in running jobs
    total: float
    per_unit: float
    inputs: tuple[InputValue, ...]
    unpriced_type_ids: tuple[TypeId, ...]


@dataclass(frozen=True, slots=True)
class PlanValue:
    lines: tuple[LineValue, ...]
    left_over: float  # value carried by surplus units and unused copies / inventions
    unpriced_type_ids: tuple[TypeId, ...] = field(default=())


def _add(into: Vec, vec: Mapping[tuple, float], times: float = 1.0) -> None:
    for k, v in vec.items():
        into[k] += v * times


def _isk(vec: Mapping[tuple, float]) -> float:
    return sum(v for k, v in vec.items() if k[0] in _ISK)


def plan_value(result: PlanResult, inp: PlanInput) -> PlanValue:
    items = {i.type_id: i for i in result.items}
    names = {t: i.name for t, i in items.items()}
    listed = {s.type_id: s.unit_price for s in result.shopping_list}
    jobs = {j.job_id: j for j in result.jobs}

    def price(t: TypeId) -> float | None:
        p = inp.prices.get(t)
        return p.unit_price if p else None

    def buy_price(t: TypeId) -> float | None:
        return listed[t] if listed.get(t) is not None else price(t)

    producers: dict[TypeId, list[PlannedJob]] = defaultdict(list)
    for j in result.jobs:
        if j.activity in _PRODUCING and j.product_type_id is not None:
            producers[j.product_type_id].append(j)

    def takes_from(pool: PlannedJob, j: PlannedJob) -> bool:
        """A job runs on the blueprint a copy or invention job made."""
        return pool.job_id in j.depends_on and j.blueprint_type_id == pool.product_type_id

    users: dict[str, list[PlannedJob]] = defaultdict(list)  # pool job -> jobs on its output
    for j in result.jobs:
        for d in j.depends_on:
            pool = jobs.get(d)
            if pool and pool.activity in _BLUEPRINT_MAKING and takes_from(pool, j):
                users[d].append(j)
    bought: dict[TypeId, list[PlannedJob]] = defaultdict(list)
    for j in result.jobs:
        if j.source == BlueprintSource.BOUGHT and j.activity in _PRODUCING:
            bought[j.blueprint_type_id].append(j)

    unit_memo: dict[TypeId, Vec] = {}
    job_memo: dict[str, Vec] = {}

    def priced(vec: Vec, kind: str, t: TypeId, units: float, each: float | None) -> None:
        vec[(kind + "u", t)] += units
        if each is None:
            vec[("nu", t)] += units
        else:
            vec[(kind + "v", t)] += units * each

    def unit(t: TypeId) -> Vec:
        """The value of one unit of t as this plan supplies it."""
        if t in unit_memo:
            return unit_memo[t]
        vec: Vec = defaultdict(float)
        item = items.get(t)
        if item is None:  # not an item row: bought as listed
            priced(vec, "b", t, 1, buy_price(t))
            unit_memo[t] = vec
            return vec
        if item.on_hand_used:
            priced(vec, "s", t, item.on_hand_used, price(t))
        if item.to_buy:
            priced(vec, "b", t, item.to_buy, buy_price(t))
        built: Vec = defaultdict(float)
        for j in producers.get(t, ()):
            _add(built, job(j))
        _add(vec, built)
        if item.started:
            each = _isk(built) / item.produced if item.produced else price(t)
            if each is None:
                vec[("nu", t)] += item.started
            else:
                vec[_STARTED] += item.started * each
        supply = item.on_hand_used + item.to_buy + item.produced + item.started
        out: Vec = defaultdict(float)
        if supply:
            _add(out, vec, 1 / supply)
        unit_memo[t] = out
        return out

    def job(j: PlannedJob) -> Vec:
        if j.job_id in job_memo:
            return job_memo[j.job_id]
        vec: Vec = defaultdict(float)
        for m in j.materials:
            _add(vec, unit(m.type_id), m.quantity)
        vec[_FEES] += j.cost.fee or 0.0
        for d in j.depends_on:
            pool = jobs.get(d)
            if pool and any(u.job_id == j.job_id for u in users.get(d, ())):
                runs = sum(u.runs for u in users[d])
                _add(vec, job(pool), j.runs / runs)
        if j.source == BlueprintSource.BOUGHT and j.activity in _PRODUCING:
            choice = inp.choices.get(j.blueprint_type_id)
            if choice and choice.bpc_price and choice.buy_bpcs:
                runs = sum(b.runs for b in bought[j.blueprint_type_id])
                vec[_BLUEPRINTS] += choice.bpc_price * choice.buy_bpcs * j.runs / runs
        job_memo[j.job_id] = vec
        return vec

    lines = []
    for line in inp.lines:
        vec: Vec = defaultdict(float)
        _add(vec, unit(line.type_id), line.quantity)
        lines.append(_line_value(line.line_id, line.type_id, line.quantity, vec, names))

    left_over = sum(i.surplus * _isk(unit(i.type_id)) for i in items.values() if i.surplus)
    left_over += sum(
        _isk(job(j))
        for j in result.jobs
        if j.activity in _BLUEPRINT_MAKING and not users.get(j.job_id)
    )
    unpriced = sorted({t for line in lines for t in line.unpriced_type_ids})
    return PlanValue(tuple(lines), left_over, tuple(unpriced))


def _line_value(
    line_id: str, t: TypeId, quantity: int, vec: Vec, names: Mapping[TypeId, str]
) -> LineValue:
    raw: dict[TypeId, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for key, v in vec.items():
        if key[0] in ("su", "sv", "bu", "bv"):
            raw[key[1]][("su", "sv", "bu", "bv").index(key[0])] += v
    inputs = sorted(
        (
            InputValue(rt, names.get(rt, str(rt)), su, sv, bu, bv)
            for rt, (su, sv, bu, bv) in raw.items()
            if su > 1e-9 or bu > 1e-9
        ),
        key=lambda i: (-(i.stock_value + i.buy_value), i.type_id),
    )
    stock = sum(i.stock_value for i in inputs)
    bought = sum(i.buy_value for i in inputs)
    total = stock + bought + vec[_FEES] + vec[_BLUEPRINTS] + vec[_STARTED]
    return LineValue(
        line_id=line_id,
        type_id=t,
        name=names.get(t, str(t)),
        quantity=quantity,
        stock=stock,
        bought=bought,
        job_fees=vec[_FEES],
        blueprints=vec[_BLUEPRINTS],
        started=vec[_STARTED],
        total=total,
        per_unit=total / quantity if quantity else 0.0,
        inputs=tuple(inputs),
        unpriced_type_ids=tuple(
            sorted({k[1] for k, v in vec.items() if k[0] == "nu" and v > 1e-9})
        ),
    )
