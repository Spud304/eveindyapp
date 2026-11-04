"""Compressed ore calculator: the cheapest compressed ore to buy and reprocess for a mineral
shortfall.

Yield per ore, as the client computes it (reprocessing/util.py, ui/util.py) [client]:
- efficiency = min(1, station efficiency x character yield);
- character yield = product over the ore's processing skill (SDE attr 790 on the ore), Reprocessing
  and Reprocessing Efficiency of (1 + level x the skill's attr 379 / 100), times implants;
- each material out = floor(quantity per batch x batches x efficiency); only whole batches of
  `portion_size` units are reprocessed.

Station efficiency comes from the server, so it is not in client code. Used here [SDE][community]:
the best reprocessing rig for the ore class gives its `refiningYieldMultiplier` (attr 717: 0.51 T1,
0.53 T2) times its security modifier (attrs 2355-2357: 1.0 / 1.06 / 1.12); without one, 0.50. Then
x (1 + the hull's strRefiningYieldBonus (attr 2722: Athanor 2, Tatara 5.5) / 100).

The mix is an integer programme over whole batches (scipy's HiGHS MILP): least ISK spent on ore
such that every needed mineral is produced. Mixes over LP_ROUNDING_BATCHES batches use the linear
answer rounded up (at most one batch per ore over the cheapest; exact solving took seconds on
a dreadnought plan). The floor per material is handled by solving without
it, checking with it, and raising the target of any mineral that came up short (it loses at most
one unit per ore used), then solving again.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .types import Material, Reason, ReasonCode, SecurityClass, TypeId

NO_RIG_MULTIPLIER = 0.50
LP_ROUNDING_BATCHES = 1000  # above this many batches, round the linear answer up


class OreClass(StrEnum):
    ASTEROID = "asteroid"
    MOON = "moon"
    ICE = "ice"


@dataclass(frozen=True, slots=True)
class Ore:
    type_id: TypeId
    name: str
    ore_class: OreClass
    portion_size: int  # units reprocessed per batch
    materials: tuple[Material, ...]  # per batch, before efficiency
    skill_id: TypeId | None  # its processing skill (attr 790)
    price: float | None  # per unit


@dataclass(frozen=True, slots=True)
class RefineryRig:
    type_id: TypeId
    name: str
    ore_classes: frozenset[OreClass]  # what it bonuses
    multiplier: float  # attr 717
    security_multipliers: Mapping[SecurityClass, float]


@dataclass(frozen=True, slots=True)
class Refinery:
    name: str
    hull_bonus_percent: float  # attr 2722
    security: SecurityClass
    rigs: tuple[RefineryRig, ...] = ()


@dataclass(frozen=True, slots=True)
class OreLine:
    type_id: TypeId
    name: str
    batches: int
    quantity: int  # units to buy
    unit_price: float
    total: float
    efficiency: float
    reason: Reason


@dataclass(frozen=True, slots=True)
class MineralLine:
    type_id: TypeId
    needed: int
    produced: int
    surplus: int
    unit_price: float | None
    buy_cost: float | None  # buying `needed` directly


@dataclass(frozen=True, slots=True)
class OreMix:
    ores: tuple[OreLine, ...]
    minerals: tuple[MineralLine, ...]
    ore_cost: float
    mineral_cost: float | None  # buying the needed minerals directly; None if a price is missing
    station_reason: Reason
    warnings: tuple[str, ...] = ()
    feasible: bool = True


def station_efficiency(refinery: Refinery, ore_class: OreClass) -> tuple[float, str]:
    best, text = NO_RIG_MULTIPLIER, "no reprocessing rig for this ore (0.50)"
    for rig in refinery.rigs:
        if ore_class not in rig.ore_classes:
            continue
        value = rig.multiplier * rig.security_multipliers.get(refinery.security, 1.0)
        if value > best:
            best = value
            text = (
                f"{rig.name} ({rig.multiplier:.2f} x {refinery.security.value}-sec "
                f"{rig.security_multipliers.get(refinery.security, 1.0):.2f})"
            )
    hull = 1 + refinery.hull_bonus_percent / 100
    return best * hull, f"{text} x hull {hull:.3f}"


def character_yield(
    ore: Ore,
    skills: Mapping[TypeId, int],
    skill_bonus: Mapping[TypeId, float],
    general_skills: tuple[TypeId, ...],
    implant_percent: float = 0.0,
) -> float:
    out = 1.0
    for skill in (ore.skill_id, *general_skills):
        if skill is None:
            continue
        out *= 1 + skills.get(skill, 0) * skill_bonus.get(skill, 0.0) / 100
    return out * (1 + implant_percent / 100)


def produced(ore: Ore, batches: int, efficiency: float) -> dict[TypeId, int]:
    return {m.type_id: math.floor(m.quantity * batches * efficiency) for m in ore.materials}


def cheapest_mix(
    need: Mapping[TypeId, int],
    ores: list[Ore],
    refinery: Refinery,
    skills: Mapping[TypeId, int],
    skill_bonus: Mapping[TypeId, float],
    general_skills: tuple[TypeId, ...],
    mineral_prices: Mapping[TypeId, float | None],
    implant_percent: float = 0.0,
) -> OreMix:
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, linprog, milp

    need = {m: q for m, q in need.items() if q > 0}
    warnings = []
    usable = [
        o
        for o in ores
        if o.price and o.portion_size > 0 and any(m.type_id in need for m in o.materials)
    ]
    unpriced = [o.name for o in ores if not o.price and any(m.type_id in need for m in o.materials)]
    if unpriced:
        warnings.append(f"{len(unpriced)} ore(s) have no price and are left out.")
    eff = {}
    station_text = {}
    for o in usable:
        st, text = station_efficiency(refinery, o.ore_class)
        station_text[o.ore_class] = text
        cy = character_yield(o, skills, skill_bonus, general_skills, implant_percent)
        eff[o.type_id] = min(1.0, st * cy)
    station_reason = Reason(
        ReasonCode.STATION_BEST,
        f"{refinery.name}: "
        + "; ".join(f"{cls.value} {t}" for cls, t in sorted(station_text.items())),
    )
    minerals = sorted(need)

    def mineral_lines(made: dict[TypeId, int]) -> tuple[MineralLine, ...]:
        rows = []
        for m in sorted(set(need) | set(made)):
            p = mineral_prices.get(m)
            n = need.get(m, 0)
            rows.append(
                MineralLine(
                    m, n, made.get(m, 0), max(0, made.get(m, 0) - n), p, p * n if p else None
                )
            )
        return tuple(rows)

    direct = [mineral_prices.get(m) for m in minerals]
    mineral_cost = (
        sum(p * need[m] for m, p in zip(minerals, direct, strict=True))
        if all(p is not None for p in direct)
        else None
    )
    if not need:
        return OreMix((), (), 0.0, 0.0, station_reason, tuple(warnings))
    if not usable:
        return OreMix(
            (),
            mineral_lines({}),
            0.0,
            mineral_cost,
            station_reason,
            (*warnings, "No priced ore yields these minerals."),
            feasible=False,
        )

    cost = np.array([o.price * o.portion_size for o in usable])
    yield_matrix = np.array(
        [
            [
                sum(mt.quantity for mt in o.materials if mt.type_id == m) * eff[o.type_id]
                for o in usable
            ]
            for m in minerals
        ]
    )
    target = {m: need[m] for m in minerals}
    for _ in range(20):
        lower = np.array([target[m] for m in minerals], dtype=float)
        # Linear first: fast. Large mixes are rounded up (at most one extra batch per ore);
        # only small ones, where a batch matters, are solved as integers.
        res = linprog(cost, A_ub=-yield_matrix, b_ub=-lower, bounds=(0, None), method="highs")
        if res.status == 0 and res.x is not None and res.x.sum() < LP_ROUNDING_BATCHES:
            res = milp(
                c=cost,
                constraints=LinearConstraint(yield_matrix, lb=lower, ub=np.inf),
                integrality=np.ones(len(usable)),
                bounds=Bounds(0, np.inf),
            )
        if res.status != 0 or res.x is None:
            return OreMix(
                (),
                mineral_lines({}),
                0.0,
                mineral_cost,
                station_reason,
                (*warnings, f"No ore mix found ({res.message})."),
                feasible=False,
            )
        batches = [math.ceil(x - 1e-6) for x in res.x]
        made: dict[TypeId, int] = {}
        for o, b in zip(usable, batches, strict=True):
            if b:
                for m, q in produced(o, b, eff[o.type_id]).items():
                    made[m] = made.get(m, 0) + q
        short = {m: need[m] - made.get(m, 0) for m in minerals if made.get(m, 0) < need[m]}
        if not short:
            break
        for m, gap in short.items():
            target[m] += gap
    else:
        warnings.append("Rounding left a mineral short after 20 tries; check the totals.")

    lines = []
    for o, b in zip(usable, batches, strict=True):
        if not b:
            continue
        e = eff[o.type_id]
        lines.append(
            OreLine(
                o.type_id,
                o.name,
                b,
                b * o.portion_size,
                o.price,
                o.price * b * o.portion_size,
                e,
                Reason(
                    ReasonCode.BUY_RULE,
                    f"{b} batch(es) of {o.portion_size} at {e:.2%} efficiency.",
                ),
            )
        )
    lines.sort(key=lambda line: -line.total)
    return OreMix(
        tuple(lines),
        mineral_lines(made),
        sum(line.total for line in lines),
        mineral_cost,
        station_reason,
        tuple(warnings),
    )
