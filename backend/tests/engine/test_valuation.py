import pytest

from engine.types import BlueprintChoice, Price
from engine.valuation import plan_value

from .data import (
    BP_COMP_A,
    BP_FUEL,
    BP_HULL,
    BP_HULL_B,
    BP_T1_MOD,
    DATACORE,
    ENCRYPTION,
    FUEL,
    HULL,
    HULL_B,
    MEX,
    PYE,
    SCIENCE_1,
    SCIENCE_2,
    T2_MOD,
    TRIT,
    bpo,
    character,
    lab,
    make_input,
    raitaru,
)
from .invariants import checked_plan as plan

PRICES = {
    TRIT: Price(5.0, 5.0),
    PYE: Price(10.0, 10.0),
    MEX: Price(50.0, 50.0),
    DATACORE: Price(1_000.0, 1_000.0),
}


def consumed(r, inp) -> float:
    """Everything the plan uses up, in ISK: stock at market price, the shopping list, fees and
    bought BPCs."""
    stock = sum(
        i.on_hand_used * inp.prices[i.type_id].unit_price for i in r.items if i.on_hand_used
    )
    fees = sum(j.cost.fee or 0.0 for j in r.jobs)
    bpcs = sum((c.bpc_price or 0) * c.buy_bpcs for c in inp.choices.values())
    return stock + r.costs.materials + r.costs.invention_inputs + fees + bpcs


def checked_value(inp):
    r = plan(inp)
    v = plan_value(r, inp)
    assert sum(line.total for line in v.lines) + v.left_over == pytest.approx(consumed(r, inp))
    return r, v


def test_stock_and_bought_inputs_roll_up_to_the_line():
    inp = make_input(
        [(HULL, 1)],
        blueprints=(bpo(BP_HULL), bpo(BP_COMP_A)),
        stations=(raitaru(),),
        assets={TRIT: 50},
        prices=PRICES,
    )
    r, v = checked_value(inp)
    (line,) = v.lines
    trit = next(i for i in line.inputs if i.type_id == TRIT)
    used = next(i for i in r.items if i.type_id == TRIT)
    assert trit.from_stock == pytest.approx(50) and trit.stock_value == pytest.approx(250)
    assert trit.to_buy == pytest.approx(used.to_buy)
    assert line.stock == pytest.approx(250)
    assert line.job_fees > 0
    assert line.total == pytest.approx(line.stock + line.bought + line.job_fees)
    assert line.per_unit == pytest.approx(line.total)


def test_a_shared_component_stack_is_split_by_what_each_line_uses():
    # Hull uses 7 Comp A, Hull B 5: one Comp A job feeds both.
    inp = make_input(
        [(HULL, 1), (HULL_B, 1)],
        blueprints=(bpo(BP_HULL), bpo(BP_HULL_B), bpo(BP_COMP_A)),
        stations=(raitaru(),),
        prices=PRICES,
    )
    _, v = checked_value(inp)
    hull, hull_b = v.lines
    pye = {line.type_id: next(i for i in line.inputs if i.type_id == PYE) for line in v.lines}
    assert pye[HULL].to_buy / pye[HULL_B].to_buy == pytest.approx(7 / 5)
    assert next(i for i in hull_b.inputs if i.type_id == MEX).to_buy > 0
    assert all(i.type_id != MEX for i in hull.inputs)


def test_surplus_is_left_over_not_charged_to_the_line():
    inp = make_input([(FUEL, 1)], blueprints=(bpo(BP_FUEL),), stations=(raitaru(),), prices=PRICES)
    r, v = checked_value(inp)
    (line,) = v.lines
    fuel = next(i for i in r.items if i.type_id == FUEL)
    assert fuel.produced == 40 and fuel.surplus == 39
    assert v.left_over == pytest.approx(39 * line.total)


def test_copy_and_invention_go_into_the_invented_item():
    skills = {ENCRYPTION: 5, SCIENCE_1: 5, SCIENCE_2: 5}
    inp = make_input(
        [(T2_MOD, 5)],
        blueprints=(bpo(BP_T1_MOD), bpo(BP_COMP_A)),
        characters=(character(skills=skills),),
        stations=(raitaru(), lab()),
        prices=PRICES,
    )
    r, v = checked_value(inp)
    (line,) = v.lines
    datacores = next(i for i in line.inputs if i.type_id == DATACORE)
    # Attempts beyond the runs the line needs leave invented runs over; their share of the
    # datacores is left over.
    assert 0 < datacores.buy_value <= r.costs.invention_inputs + 1e-6
    assert line.total + v.left_over == pytest.approx(consumed(r, inp))


def test_bought_bpcs_are_charged_to_their_jobs():
    inp = make_input(
        [(HULL, 2)],
        blueprints=(bpo(BP_COMP_A),),
        stations=(raitaru(),),
        prices=PRICES,
        choices={BP_HULL: BlueprintChoice(buy_bpcs=1, bpc_runs=2, bpc_price=1_000_000.0)},
    )
    _, v = checked_value(inp)
    assert v.lines[0].blueprints == pytest.approx(1_000_000.0)


def test_unpriced_inputs_are_named():
    inp = make_input(
        [(HULL_B, 1)], blueprints=(bpo(BP_HULL_B), bpo(BP_COMP_A)), stations=(raitaru(),)
    )
    v = plan_value(plan(inp), inp)
    assert set(v.lines[0].unpriced_type_ids) == {TRIT, PYE, MEX}
    assert v.unpriced_type_ids == (TRIT, PYE, MEX)
