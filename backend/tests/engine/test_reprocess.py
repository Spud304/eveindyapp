import pytest

from engine.reprocess import (
    Ore,
    OreClass,
    Refinery,
    RefineryRig,
    book_cost,
    character_yield,
    cheapest_mix,
    produced,
    station_efficiency,
)
from engine.types import Material, SecurityClass

TRIT, PYE, MEX = 34, 35, 36
REPROCESSING, EFFICIENCY, SIMPLE = 3385, 3389, 60377
BONUS = {REPROCESSING: 3.0, EFFICIENCY: 2.0, SIMPLE: 2.0}
GENERAL = (REPROCESSING, EFFICIENCY)
ALL_V = {REPROCESSING: 5, EFFICIENCY: 5, SIMPLE: 5}
SEC = {SecurityClass.HIGH: 1.0, SecurityClass.LOW: 1.06, SecurityClass.NULL: 1.12}
T2_ORE_RIG = RefineryRig(46634, "Asteroid T2", frozenset({OreClass.ASTEROID}), 0.53, SEC)


def ore(type_id, mats, price, cls=OreClass.ASTEROID, portion=100, skill=SIMPLE, volume=0.0):
    return Ore(
        type_id,
        f"Ore {type_id}",
        cls,
        portion,
        tuple(Material(t, q) for t, q in mats),
        skill,
        price,
        volume,
    )


def test_station_efficiency_rig_security_and_hull():
    tatara = Refinery("Tatara", 5.5, SecurityClass.NULL, (T2_ORE_RIG,))
    value, text = station_efficiency(tatara, OreClass.ASTEROID)
    assert value == pytest.approx(0.53 * 1.12 * 1.055)
    assert "Asteroid T2" in text
    # The rig does not cover moon ore: base 0.50 with the hull bonus.
    assert station_efficiency(tatara, OreClass.MOON)[0] == pytest.approx(0.50 * 1.055)


def test_character_yield_multiplies_skills():
    o = ore(1, [(TRIT, 400)], 10.0)
    assert character_yield(o, ALL_V, BONUS, GENERAL) == pytest.approx(1.15 * 1.10 * 1.10)
    assert character_yield(o, {}, BONUS, GENERAL) == 1.0


def test_output_is_floored_per_material():
    o = ore(1, [(TRIT, 400), (PYE, 3)], 10.0)
    assert produced(o, 2, 0.5) == {TRIT: 400, PYE: 3}
    assert produced(o, 1, 0.5) == {TRIT: 200, PYE: 1}


def test_cheapest_mix_covers_every_mineral_in_whole_batches():
    cheap_trit = ore(1, [(TRIT, 400)], 1.0)  # 100 ISK per batch for 400 Tritanium
    mixed = ore(2, [(TRIT, 100), (PYE, 300)], 2.0)  # 200 ISK for 100 Tritanium + 300 Pyerite
    pricey = ore(3, [(PYE, 300)], 5.0)
    mix = cheapest_mix(
        {TRIT: 1000, PYE: 600},
        [cheap_trit, mixed, pricey],
        Refinery("NPC", 0.0, SecurityClass.HIGH),
        {},
        BONUS,
        GENERAL,
        {TRIT: 4.0, PYE: 10.0},
    )
    assert mix.feasible
    made = {m.type_id: m.produced for m in mix.minerals}
    assert made[TRIT] >= 1000 and made[PYE] >= 600
    # At 50%: 4 batches of mixed give 200 Trit + 600 Pye; 4 of cheap give 800 Trit.
    assert {line.type_id: line.batches for line in mix.ores} == {1: 4, 2: 4}
    assert mix.ore_cost == pytest.approx(4 * 100 + 4 * 200)
    assert mix.mineral_cost == pytest.approx(1000 * 4 + 600 * 10)


def test_floor_losses_are_made_up():
    # 7 per batch at 50% = 3.5 -> floored. Need 7: the linear answer (2 batches) gives 7.0,
    # but floor(7 x 2 x 0.5) = 7 too; need 10 needs 3 batches (floor 10.5 = 10).
    o = ore(1, [(MEX, 7)], 1.0)
    mix = cheapest_mix(
        {MEX: 10}, [o], Refinery("NPC", 0.0, SecurityClass.HIGH), {}, BONUS, GENERAL, {}
    )
    assert mix.ores[0].batches == 3
    assert mix.minerals[0].produced == 10


def test_unpriced_ores_are_left_out_and_infeasible_is_reported():
    mix = cheapest_mix(
        {TRIT: 100},
        [ore(1, [(TRIT, 400)], None)],
        Refinery("NPC", 0, SecurityClass.HIGH),
        {},
        BONUS,
        GENERAL,
        {TRIT: 4.0},
    )
    assert not mix.feasible
    assert any("no price" in w for w in mix.warnings)


def test_volumes_of_ore_and_minerals():
    o = ore(1, [(TRIT, 400)], 1.0, volume=0.001)
    mix = cheapest_mix(
        {TRIT: 1000},
        [o],
        Refinery("NPC", 0.0, SecurityClass.HIGH),
        {},
        BONUS,
        GENERAL,
        {TRIT: 4.0},
        mineral_volumes={TRIT: 0.01},
    )
    # 50%: 200 Tritanium per batch -> 5 batches, 500 units of ore at 0.001 m3.
    assert mix.ores[0].volume == pytest.approx(0.5)
    assert mix.ore_volume == pytest.approx(0.5)
    assert mix.mineral_volume == pytest.approx(10.0)
    assert mix.minerals[0].volume == pytest.approx(10.0)


# --- order books ------------------------------------------------------------------------------

NPC = Refinery("NPC", 0.0, SecurityClass.HIGH)


def booked(type_id, mats, book, portion=100):
    return Ore(
        type_id,
        f"Ore {type_id}",
        OreClass.ASTEROID,
        portion,
        tuple(Material(t, q) for t, q in mats),
        SIMPLE,
        None,
        0.0,
        book,
    )


def test_book_cost_walks_orders_cheapest_first():
    book = ((1.0, 100), (2.0, 50))
    assert book_cost(book, 120) == (100 * 1.0 + 20 * 2.0, 2.0, 0)
    assert book_cost(book, 200) == (200.0, 2.0, 50)


def test_mix_uses_cheap_orders_then_switches_ore():
    # At 50%, a batch of either ore gives 200 Tritanium. Ore 1 has 300 units (3 batches) at
    # 1 ISK, then orders at 5 ISK; ore 2 is 2 ISK with plenty on sale. Need 1000 Tritanium:
    # 3 batches of ore 1 (600) and 2 batches of ore 2 (400).
    cheap_then_dear = booked(1, [(TRIT, 400)], ((1.0, 300), (5.0, 10_000)))
    steady = booked(2, [(TRIT, 400)], ((2.0, 10_000),))
    mix = cheapest_mix({TRIT: 1000}, [cheap_then_dear, steady], NPC, {}, BONUS, GENERAL, {})
    got = {line.type_id: line for line in mix.ores}
    assert {t: line.batches for t, line in got.items()} == {1: 3, 2: 2}
    assert got[1].total == 300 and got[1].top_price == 1.0 and got[1].on_sale == 10_300
    assert mix.ore_cost == 300 + 2 * 100 * 2.0


def test_ore_with_nothing_on_sale_is_left_out():
    mix = cheapest_mix(
        {TRIT: 100},
        [booked(1, [(TRIT, 400)], ()), booked(2, [(TRIT, 400)], ((3.0, 1000),))],
        NPC,
        {},
        BONUS,
        GENERAL,
        {},
    )
    assert [line.type_id for line in mix.ores] == [2]
    assert any("nothing on sale" in w for w in mix.warnings)


def test_minerals_bought_directly_through_their_book():
    mix = cheapest_mix(
        {TRIT: 150},
        [booked(1, [(TRIT, 400)], ((1.0, 1000),))],
        NPC,
        {},
        BONUS,
        GENERAL,
        {},
        mineral_books={TRIT: ((4.0, 100), (6.0, 1000))},
    )
    assert mix.mineral_cost == 100 * 4.0 + 50 * 6.0
    assert mix.minerals[0].unit_price == pytest.approx(700 / 150)
    short = cheapest_mix(
        {TRIT: 150},
        [booked(1, [(TRIT, 400)], ((1.0, 1000),))],
        NPC,
        {},
        BONUS,
        GENERAL,
        {},
        mineral_books={TRIT: ((4.0, 100),)},
    )
    assert short.mineral_cost is None
    assert any("enough on sale" in w for w in short.warnings)
