from dataclasses import replace

import pytest

from engine.pricing import market_prices, price_item, reprice, unpriced_warning
from engine.types import Price, ReasonCode

from .data import (
    ACCELERANT,
    BP_COMP_A,
    BP_HULL,
    BP_T2_MOD,
    DATACORE,
    DECRYPTOR,
    HULL,
    PYE,
    TRIT,
    bpo,
    game,
    make_input,
)
from .invariants import checked_plan as plan
from .test_planner import bp, t2_input


def hull_plan():
    prices = {TRIT: Price(4.0, 4.0), PYE: Price(10.0, 10.0)}
    return plan(make_input([(HULL, 1)], blueprints=(bpo(BP_HULL), bpo(BP_COMP_A)), prices=prices))


def item(r, type_id):
    return next(s for s in r.shopping_list if s.type_id == type_id)


def test_shopping_list_priced_through_the_book():
    r = hull_plan()
    trit = item(r, TRIT)
    books = {TRIT: ((3.0, 50), (5.0, 10_000))}
    out = reprice(r, books)
    priced = item(out, TRIT)
    expected = 50 * 3.0 + (trit.quantity - 50) * 5.0
    assert priced.total_price == pytest.approx(expected)
    assert priced.unit_price == pytest.approx(expected / trit.quantity)
    assert (priced.price_source, priced.on_sale) == ("jita", 10_050)
    # Pyerite was not looked up: unchanged, still the average.
    assert item(out, PYE) == item(r, PYE)
    assert out.costs.materials == pytest.approx(expected + item(r, PYE).total_price)
    assert out.costs.total == pytest.approx(out.costs.materials + sum(out.costs.job_fees.values()))


def test_nothing_on_sale_keeps_the_average():
    r = hull_plan()
    priced = item(reprice(r, {TRIT: ()}), TRIT)
    assert priced.total_price == item(r, TRIT).total_price
    assert (priced.price_source, priced.on_sale) == ("average", 0)


def test_not_enough_on_sale_prices_the_rest_at_the_dearest_order():
    r = hull_plan()
    q = item(r, TRIT).quantity
    out = reprice(r, {TRIT: ((3.0, 10), (6.0, 10))})
    assert item(out, TRIT).total_price == pytest.approx(30 + 60 + (q - 20) * 6.0)
    assert any("less on sale at Jita" in w.text for w in out.warnings)


def test_invention_inputs_stay_in_their_own_total():
    r = plan(t2_input(prices={DATACORE: Price(100.0, 100.0)}))
    dc = item(r, DATACORE)
    assert dc.reason.code == ReasonCode.BUY_INVENTION_INPUT
    out = reprice(r, {DATACORE: ((50.0, 10_000),)})
    assert out.costs.invention_inputs == pytest.approx(dc.quantity * 50.0)


def test_price_item_without_a_book_is_unchanged():
    r = hull_plan()
    assert price_item(item(r, TRIT), None) is item(r, TRIT)


# --- market prices for a second planning pass -------------------------------------------------


def test_market_prices_price_the_needed_quantity_through_the_book():
    old = {TRIT: Price(4.0, 4.5), PYE: Price(10.0, 9.0)}
    books = {TRIT: ((3.0, 50), (5.0, 100)), PYE: (), DATACORE: ((7.0, 1),)}
    out = market_prices(old, books, {TRIT: 100, PYE: 10})
    assert out[TRIT] == Price((50 * 3.0 + 50 * 5.0) / 100, 4.5)  # adjusted price kept
    assert out[PYE] == old[PYE]  # nothing on sale: unchanged
    assert out[DATACORE] == Price(7.0, None)  # not on the list yet: one unit


def test_market_prices_short_book_prices_the_rest_at_the_dearer_of_top_and_old():
    out = market_prices({TRIT: Price(9.0, None)}, {TRIT: ((3.0, 10),)}, {TRIT: 20})
    assert out[TRIT].unit_price == pytest.approx((10 * 3.0 + 10 * 9.0) / 20)


def test_market_prices_can_change_the_automatic_decryptor():
    """At the average the decryptor looks too dear; at the market price it pays off. Planning
    again with market prices makes the choice on the prices the shopping list shows."""
    average = {DATACORE: Price(1_000_000.0, None), DECRYPTOR: Price(1e12, None)}
    inp = t2_input(game=game([ACCELERANT]), prices=average)
    first = plan(inp)
    assert bp(first, BP_T2_MOD).invention.decryptor_type_id is None
    priced = market_prices(average, {DECRYPTOR: ((10.0, 1000),)}, {})
    second = plan(replace(inp, prices=priced))
    assert bp(second, BP_T2_MOD).invention.decryptor_type_id == DECRYPTOR


def test_reprice_replaces_the_planners_unpriced_warning():
    r = plan(make_input([(HULL, 1)], blueprints=(bpo(BP_HULL), bpo(BP_COMP_A))))
    assert set(r.costs.unpriced_type_ids) == {TRIT, PYE}
    assert unpriced_warning(2) in r.warnings
    out = reprice(r, {TRIT: ((3.0, 10**9),)})
    assert out.costs.unpriced_type_ids == (PYE,)
    assert unpriced_warning(1) in out.warnings and unpriced_warning(2) not in out.warnings
    everything = reprice(r, {TRIT: ((3.0, 10**9),), PYE: ((5.0, 10**9),)})
    assert not any(w.code == ReasonCode.PRICE_MISSING for w in everything.warnings)
