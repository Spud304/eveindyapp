from types import SimpleNamespace as NS

from apps.planning.hauling import Move, moves
from engine.types import ItemType, Material

TRIT = 34
TYPES = {TRIT: ItemType(TRIT, "Tritanium", 18, 4, volume=0.01)}
# Station pk -> location id
LOCS = {1: 100, 2: 200}


def result(jobs, used):
    return NS(
        jobs=[NS(station_id=s, materials=[Material(TRIT, q)]) for s, q in jobs],
        items=[NS(type_id=TRIT, on_hand_used=used)],
    )


def test_stock_at_the_station_covers_its_jobs_first():
    stock = {(TRIT, 100, "Hangar"): 500, (TRIT, 300, "CorpSAG3"): 1_000}
    assert moves(result([(1, 400)], 400), stock, LOCS, TYPES) == []


def test_the_rest_comes_from_the_biggest_stacks_elsewhere():
    stock = {
        (TRIT, 100, "Hangar"): 300,
        (TRIT, 300, "CorpSAG3"): 50,
        (TRIT, 400, "CorpSAG3"): 600,
    }
    assert moves(result([(1, 1_000)], 1_000), stock, LOCS, TYPES) == [
        Move(TRIT, 600, 400, "CorpSAG3", 1, 6.0),
        Move(TRIT, 50, 300, "CorpSAG3", 1, 0.5),
    ]


def test_only_the_stock_the_plan_uses_is_moved():
    # 1,000 needed, 700 from stock (the rest bought): 200 local, 500 carried.
    stock = {(TRIT, 100, "Hangar"): 200, (TRIT, 300, "Hangar"): 5_000}
    (m,) = moves(result([(1, 1_000)], 700), stock, LOCS, TYPES)
    assert (m.quantity, m.from_location, m.to_station) == (500, 300, 1)


def test_one_stations_spare_stock_feeds_another():
    stock = {(TRIT, 100, "Hangar"): 900, (TRIT, 200, "Hangar"): 0}
    (m,) = moves(result([(1, 400), (2, 300)], 700), stock, LOCS, TYPES)
    assert (m.quantity, m.from_location, m.to_station) == (300, 100, 2)
