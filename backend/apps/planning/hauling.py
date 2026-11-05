"""Stock a plan uses that is not where its jobs run.

A plan counts the stock at all its stations (and extra locations) as one pile, so the engine
can use Megacyte from two structures for jobs at a third. This module says what has to be
carried where before those jobs can start.

Each item's stock is split the same way every time: stock already at a station covers the
jobs there first, then what is still missing comes from the biggest stacks elsewhere. Only
the quantity the plan takes from stock (`ItemPlan.on_hand_used`) is placed; what is bought
or built is not.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from engine.types import ItemType, PlanResult

from .inputs import AssetBucket


@dataclass(frozen=True)
class Move:
    type_id: int
    quantity: int
    from_location: int
    from_hangar: str
    to_station: int  # Station pk the consuming jobs run at
    volume: float


def moves(
    result: PlanResult,
    stock: Mapping[AssetBucket, int],
    station_locations: Mapping[int, int | None],
    types: Mapping[int, ItemType],
) -> list[Move]:
    """The moves that bring the stock a plan uses to the stations whose jobs use it."""
    at: dict[int, dict[tuple[int, str], int]] = defaultdict(dict)
    for (type_id, loc, flag), qty in stock.items():
        if qty > 0:
            at[type_id][(loc, flag)] = qty
    demand: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for job in result.jobs:
        if job.station_id is None or station_locations.get(job.station_id) is None:
            continue
        for m in job.materials:
            demand[m.type_id][job.station_id] += m.quantity

    out: list[Move] = []
    for item in result.items:
        used = item.on_hand_used
        if not used or item.type_id not in demand:
            continue
        left = dict(at[item.type_id])
        unmet: dict[int, int] = {}
        for sid, need in sorted(demand[item.type_id].items()):
            loc = station_locations[sid]
            for key in sorted(k for k in left if k[0] == loc):
                take = min(need, left[key], used)
                left[key] -= take
                need -= take
                used -= take
            if need:
                unmet[sid] = need
        sources = sorted((k for k in left if left[k] > 0), key=lambda k: (-left[k], k))
        for sid, need in sorted(unmet.items(), key=lambda kv: (-kv[1], kv[0])):
            for key in sources:
                take = min(need, left[key], used)
                if take <= 0:
                    continue
                left[key] -= take
                need -= take
                used -= take
                volume = take * types[item.type_id].volume if item.type_id in types else 0.0
                out.append(Move(item.type_id, take, key[0], key[1], sid, volume))
    return out
