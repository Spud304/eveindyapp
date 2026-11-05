"""What has to be carried between locations before a plan's jobs can start.

Two kinds of move:
- stock: a plan counts the stock at all its stations (and extra locations) as one pile, so
  the engine can use Megacyte from two structures for jobs at a third;
- built: an item made at one station and used by jobs at another (the engine picks stations
  per blueprint, and prefers the one where the item is used only when materials tie).

Each item is split the same way every time. A station's jobs are covered first by what is
made there, then by stock already there; what is still missing comes from what is made at
other stations, then from the biggest stacks elsewhere. Only the quantity the plan takes
from stock (`ItemPlan.on_hand_used`) is placed; bought items are not.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from engine.types import Activity, ItemType, PlanResult

from .inputs import AssetBucket

PRODUCING = (Activity.MANUFACTURING, Activity.REACTION)


@dataclass(frozen=True)
class Move:
    type_id: int
    quantity: int
    to_station: int  # Station pk the consuming jobs run at
    volume: float
    from_station: int | None = None  # built: the Station pk that makes it
    from_location: int | None = None  # stock: where it is
    from_hangar: str = ""  # stock: its hangar flag


def moves(
    result: PlanResult,
    stock: Mapping[AssetBucket, int],
    station_locations: Mapping[int, int | None],
    types: Mapping[int, ItemType],
) -> list[Move]:
    """The moves that bring what a plan's jobs use to the stations they run at."""
    at: dict[int, dict[tuple[int, str], int]] = defaultdict(dict)
    for (type_id, loc, flag), qty in stock.items():
        if qty > 0:
            at[type_id][(loc, flag)] = qty
    demand: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    made: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for job in result.jobs:
        if job.station_id is None:
            continue
        for m in job.materials:
            demand[m.type_id][job.station_id] += m.quantity
        if job.activity in PRODUCING and job.product_type_id is not None:
            made[job.product_type_id][job.station_id] += job.product_quantity

    out: list[Move] = []
    for item in result.items:
        if item.type_id in demand:
            out += _item_moves(
                item.type_id,
                dict(demand[item.type_id]),
                dict(made.get(item.type_id, {})),
                dict(at.get(item.type_id, {})),
                item.on_hand_used,
                station_locations,
                types[item.type_id].volume if item.type_id in types else 0.0,
            )
    return out


def _item_moves(
    t: int,
    need: dict[int, int],  # station -> quantity its jobs use
    built: dict[int, int],  # station -> quantity made there
    left: dict[tuple[int, str], int],  # (location, hangar) -> stock
    used: int,  # how much of the stock the plan takes
    station_locations: Mapping[int, int | None],
    unit: float,
) -> list[Move]:
    out: list[Move] = []

    def take_stock(sid: int, key: tuple[int, str]) -> int:
        nonlocal used
        take = min(need[sid], left[key], used)
        left[key] -= take
        need[sid] -= take
        used -= take
        return take

    # At the station: what is made there, then stock already there.
    for sid in sorted(need):
        take = min(need[sid], built.get(sid, 0))
        if take:
            built[sid] -= take
            need[sid] -= take
        loc = station_locations.get(sid)
        if loc is not None:
            for key in sorted(k for k in left if k[0] == loc):
                take_stock(sid, key)

    short = sorted((sid for sid in need if need[sid] > 0), key=lambda s: (-need[s], s))
    # From other stations that make it.
    for sid in short:
        for src in sorted((s for s in built if built[s] > 0), key=lambda s: (-built[s], s)):
            take = min(need[sid], built[src])
            if take <= 0:
                break
            built[src] -= take
            need[sid] -= take
            out.append(Move(t, take, sid, take * unit, from_station=src))
    # From stock elsewhere, biggest stacks first. A station with no known location cannot
    # be told apart from the stock's location, so it gets no stock moves.
    sources = sorted((k for k in left if left[k] > 0), key=lambda k: (-left[k], k))
    for sid in short:
        if station_locations.get(sid) is None:
            continue
        for key in sources:
            if take := take_stock(sid, key):
                out.append(
                    Move(t, take, sid, take * unit, from_location=key[0], from_hangar=key[1])
                )
    return out
