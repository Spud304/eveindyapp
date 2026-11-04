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

Prices: an ore or mineral with an order `book` (sell orders, cheapest first) is bought through it:
each order is a price tier with its units as the cap, so big buys pay the higher orders and no
more can be bought than is on sale. Without a book, its flat `price` is used with no cap. Order
minimum quantities are ignored.

The mix is the least ISK spent on ore such that every needed mineral is produced, over whole
batches (scipy HiGHS). Mixes over LP_ROUNDING_BATCHES batches use the linear answer rounded up
(at most one batch per ore over the cheapest; exact integer solving took seconds on a
dreadnought plan); smaller ones are solved as integers. The floor per material is handled by
solving without it, checking with it, and raising the target of any mineral that came up short
(it loses at most one unit per ore used), then solving again.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .pricing import Book, book_cost
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
    price: float | None  # per unit, used when there is no `book`
    volume: float = 0.0  # m3 per unit
    book: Book | None = None  # sell orders; () means none on sale


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
    # The owner's reprocessing tax: charged in ISK on what comes out, at CCP's adjusted price
    # (reprocessing/util.py: round(adjusted price x recovered x take, 2) per material). [client]
    tax_percent: float = 0.0


@dataclass(frozen=True, slots=True)
class OreLine:
    type_id: TypeId
    name: str
    batches: int
    quantity: int  # units to buy
    unit_price: float  # average paid per unit
    total: float
    efficiency: float
    reason: Reason
    volume: float = 0.0  # m3 for the whole quantity
    top_price: float | None = None  # dearest order bought from (with a book)
    on_sale: int | None = None  # units on sale (with a book)
    tax: float = 0.0  # reprocessing tax on its output, in ISK (not in `total`)


@dataclass(frozen=True, slots=True)
class MineralLine:
    type_id: TypeId
    needed: int
    produced: int
    surplus: int
    unit_price: float | None  # average paid per unit for `needed`
    buy_cost: float | None  # buying `needed` directly; None if no price or not enough on sale
    volume: float = 0.0  # m3 of `needed`
    on_sale: int | None = None  # units on sale (with a book)


@dataclass(frozen=True, slots=True)
class OreMix:
    ores: tuple[OreLine, ...]
    minerals: tuple[MineralLine, ...]
    ore_cost: float
    mineral_cost: float | None  # buying the needed minerals directly; None if not possible
    station_reason: Reason
    warnings: tuple[str, ...] = ()
    feasible: bool = True
    ore_volume: float = 0.0  # m3 of all the ore
    mineral_volume: float = 0.0  # m3 of the needed minerals, bought as they are


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
    mineral_volumes: Mapping[TypeId, float] | None = None,
    mineral_books: Mapping[TypeId, Book] | None = None,
    adjusted_prices: Mapping[TypeId, float | None] | None = None,
) -> OreMix:
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp

    need = {m: q for m, q in need.items() if q > 0}
    vols = mineral_volumes or {}
    books = mineral_books or {}
    mineral_volume = sum(vols.get(m, 0.0) * q for m, q in need.items())
    warnings: list[str] = []

    def priced(o: Ore) -> bool:
        return bool(o.book) if o.book is not None else bool(o.price)

    relevant = [o for o in ores if any(m.type_id in need for m in o.materials)]
    usable = [o for o in relevant if o.portion_size > 0 and priced(o)]
    no_stock = [o for o in relevant if o.book is not None and not o.book]
    no_price = [o for o in relevant if o.book is None and not o.price]
    if no_stock:
        warnings.append(f"{len(no_stock)} ore(s) have nothing on sale and are left out.")
    if no_price:
        warnings.append(f"{len(no_price)} ore(s) have no price and are left out.")

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

    def mineral_line(m: TypeId, made: int) -> MineralLine:
        n = need.get(m, 0)
        book = books.get(m)
        if book is not None:
            cost, _, short = book_cost(book, n)
            buy = cost if not short else None
            unit = cost / n if n and not short else None
            on_sale = sum(u for _, u in book)
        else:
            p = mineral_prices.get(m)
            unit, buy, on_sale = p, (p * n if p is not None else None), None
        return MineralLine(m, n, made, max(0, made - n), unit, buy, vols.get(m, 0.0) * n, on_sale)

    def mineral_lines(made: dict[TypeId, int]) -> tuple[MineralLine, ...]:
        return tuple(mineral_line(m, made.get(m, 0)) for m in sorted(set(need) | set(made)))

    direct = [mineral_line(m, 0) for m in minerals]
    short_minerals = [m.type_id for m in direct if m.buy_cost is None and m.on_sale is not None]
    if short_minerals:
        warnings.append(
            f"{len(short_minerals)} mineral(s) do not have enough on sale to buy as they are."
        )
    mineral_cost = (
        sum(m.buy_cost for m in direct if m.buy_cost is not None)
        if all(m.buy_cost is not None for m in direct)
        else None
    )
    if not need:
        return OreMix((), (), 0.0, 0.0, station_reason, tuple(warnings))

    def infeasible(text: str) -> OreMix:
        return OreMix(
            (),
            mineral_lines({}),
            0.0,
            mineral_cost,
            station_reason,
            (*warnings, text),
            feasible=False,
            mineral_volume=mineral_volume,
        )

    if not usable:
        return infeasible("No ore on sale yields these minerals.")

    # Variables: one batch count per ore, then one per price tier (orders, in batches).
    tiers: list[tuple[int, float, float]] = []  # (ore index, ISK per batch, cap in batches)
    for i, o in enumerate(usable):
        if o.book is None:
            tiers.append((i, o.price * o.portion_size, math.inf))
        else:
            tiers.extend((i, p * o.portion_size, u / o.portion_size) for p, u in o.book)
    n_ore, n_tier = len(usable), len(tiers)
    adjusted = adjusted_prices or {}
    take = refinery.tax_percent / 100

    def tax_on(o: Ore, made: Mapping[TypeId, float]) -> float:
        return sum(round((adjusted.get(m) or 0.0) * q * take, 2) for m, q in made.items())

    # The tax is on what comes out, so it is a cost per batch of each ore (before flooring).
    batch_tax = [
        tax_on(o, {mt.type_id: mt.quantity * eff[o.type_id] for mt in o.materials}) if take else 0.0
        for o in usable
    ]
    cost = np.concatenate([np.array(batch_tax), np.array([t[1] for t in tiers])])
    caps = np.concatenate([np.full(n_ore, np.inf), np.array([t[2] for t in tiers])])
    link = np.zeros((n_ore, n_ore + n_tier))  # tiers of an ore add up to its batches
    for i in range(n_ore):
        link[i, i] = -1.0
    for j, (i, _, _) in enumerate(tiers):
        link[i, n_ore + j] = 1.0
    yields = np.zeros((len(minerals), n_ore + n_tier))
    for r, m in enumerate(minerals):
        for i, o in enumerate(usable):
            yields[r, i] = (
                sum(mt.quantity for mt in o.materials if mt.type_id == m) * eff[o.type_id]
            )
    bounds = Bounds(np.zeros(n_ore + n_tier), caps)

    target = {m: need[m] for m in minerals}
    for _ in range(20):
        lower = np.array([target[m] for m in minerals], dtype=float)
        constraints = [
            LinearConstraint(yields, lb=lower, ub=np.inf),
            LinearConstraint(link, lb=0.0, ub=0.0),
        ]
        res = milp(c=cost, constraints=constraints, bounds=bounds)  # linear: no integrality
        if res.status == 0 and res.x is not None and res.x[:n_ore].sum() < LP_ROUNDING_BATCHES:
            integral = np.concatenate([np.ones(n_ore), np.zeros(n_tier)])
            res = milp(c=cost, constraints=constraints, bounds=bounds, integrality=integral)
        if res.status != 0 or res.x is None:
            return infeasible(f"No ore mix found: {res.message}")
        batches = [math.ceil(x - 1e-6) for x in res.x[:n_ore]]
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
        units = b * o.portion_size
        top = on_sale = None
        if o.book is None:
            total = o.price * units
        else:
            total, top, short_units = book_cost(o.book, units)
            on_sale = sum(u for _, u in o.book)
            if short_units:
                # Rounding up to a whole batch can ask for a little more than is on sale.
                total += short_units * (top or 0.0)
                warnings.append(f"{o.name}: {short_units:,} more units than are on sale.")
        e = eff[o.type_id]
        tax = tax_on(o, produced(o, b, e)) if take else 0.0
        tax_text = f" Reprocessing tax {tax:,.0f} ISK." if tax else ""
        lines.append(
            OreLine(
                o.type_id,
                o.name,
                b,
                units,
                total / units,
                total,
                e,
                Reason(
                    ReasonCode.BUY_RULE,
                    f"{b} batch(es) of {o.portion_size} at {e:.2%} efficiency.{tax_text}",
                ),
                o.volume * units,
                top,
                on_sale,
                tax,
            )
        )
    lines.sort(key=lambda line: -line.total)
    return OreMix(
        tuple(lines),
        mineral_lines(made),
        sum(line.total + line.tax for line in lines),  # buying the ore and reprocessing it
        mineral_cost,
        station_reason,
        tuple(warnings),
        ore_volume=sum(line.volume for line in lines),
        mineral_volume=mineral_volume,
    )
