import pytest

from apps.esidata import market
from apps.planning import prices
from apps.planning.prices import jita_plan
from engine.pricing import reprice
from engine.types import Activity, Price
from tests.engine.data import (
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
    character,
    game,
    make_input,
)
from tests.engine.invariants import checked_plan as plan
from tests.engine.test_planner import FIVE_MFG_SLOTS, bp, t2_input

BOOKS = {TRIT: ((3.0, 10**9),), PYE: ((5.0, 10**9),), DECRYPTOR: ((10.0, 1000),)}


@pytest.fixture
def reruns(monkeypatch):
    """Jita books from BOOKS; counts the planning passes `jita_plan` makes."""
    monkeypatch.setattr(market, "jita_sell_books", lambda ids, refresh=False: (BOOKS, set()))
    calls = []

    def counted(inp):
        calls.append(inp)
        return plan(inp)

    monkeypatch.setattr(prices, "plan", counted)
    return calls


def test_a_plan_prices_cannot_change_is_only_repriced(reruns):
    prices_ = {TRIT: Price(4.0, 4.0), PYE: Price(10.0, 10.0)}
    inp = make_input([(HULL, 1)], blueprints=(bpo(BP_HULL), bpo(BP_COMP_A)), prices=prices_)
    first = plan(inp)
    out = jita_plan(inp, first)
    assert reruns == []
    assert out.result == reprice(first, BOOKS)
    assert out.input.prices[TRIT].unit_price == 3.0  # buy options still run at Jita prices


def test_an_auto_copy_split_plans_again(reruns):
    prices_ = {TRIT: Price(4.0, 4.0), PYE: Price(10.0, 10.0)}
    inp = make_input(
        [(HULL, 10)],
        blueprints=(bpo(BP_HULL), bpo(BP_COMP_A)),
        characters=(character(skills=FIVE_MFG_SLOTS),),
        prices=prices_,
    )
    first = plan(inp)
    assert any(j.activity == Activity.COPYING for j in first.jobs)
    jita_plan(inp, first)
    assert len(reruns) == 1


def test_invention_plans_again_and_picks_the_decryptor_on_jita_prices(reruns):
    average = {DATACORE: Price(1_000_000.0, None), DECRYPTOR: Price(1e12, None)}
    inp = t2_input(game=game([ACCELERANT]), prices=average)
    first = plan(inp)
    assert bp(first, BP_T2_MOD).invention.decryptor_type_id is None
    out = jita_plan(inp, first)
    assert len(reruns) == 1
    assert bp(out.result, BP_T2_MOD).invention.decryptor_type_id == DECRYPTOR
