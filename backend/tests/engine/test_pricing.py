import pytest

from engine import plan
from engine.pricing import price_item, reprice
from engine.types import Price, ReasonCode

from .data import BP_COMP_A, BP_HULL, DATACORE, HULL, PYE, TRIT, bpo, make_input
from .test_planner import t2_input


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
