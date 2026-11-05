from types import SimpleNamespace as NS

from apps.planning.hauling import Move, moves
from engine.types import Activity, ItemType, Material

TRIT = 34
TYPES = {TRIT: ItemType(TRIT, "Tritanium", 18, 4, volume=0.01)}
# Station pk -> location id
LOCS = {1: 100, 2: 200}


def result(jobs, used, built=()):
    """`jobs`: (station, Tritanium used); `built`: (station, Tritanium made)."""
    return NS(
        jobs=[
            *(NS(station_id=s, materials=[Material(TRIT, q)], activity=None) for s, q in jobs),
            *(
                NS(
                    station_id=s,
                    materials=[],
                    activity=Activity.MANUFACTURING,
                    product_type_id=TRIT,
                    product_quantity=q,
                )
                for s, q in built
            ),
        ],
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
        Move(TRIT, 600, 1, 6.0, from_location=400, from_hangar="CorpSAG3"),
        Move(TRIT, 50, 1, 0.5, from_location=300, from_hangar="CorpSAG3"),
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


def test_items_built_at_another_station_are_carried_to_the_jobs_using_them():
    (m,) = moves(result([(2, 300)], 0, built=[(1, 300)]), {}, LOCS, TYPES)
    assert m == Move(TRIT, 300, 2, 3.0, from_station=1)


def test_what_a_station_builds_covers_its_own_jobs_first():
    # Station 1 builds 500 and uses 200; station 2 uses 300 and has 100 in stock.
    stock = {(TRIT, 200, "Hangar"): 100}
    found = moves(result([(1, 200), (2, 300)], 100, built=[(1, 500)]), stock, LOCS, TYPES)
    assert found == [Move(TRIT, 200, 2, 2.0, from_station=1)]


def test_a_station_without_a_location_gets_built_moves_but_no_stock_moves():
    stock = {(TRIT, 300, "Hangar"): 1_000}
    locs = {1: 100, 2: None}
    found = moves(result([(2, 500)], 200, built=[(1, 300)]), stock, locs, TYPES)
    assert found == [Move(TRIT, 300, 2, 3.0, from_station=1)]
