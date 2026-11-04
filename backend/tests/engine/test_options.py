from engine import purchase_options
from engine.types import Activity, BlueprintChoice, BuildRules, Price

from .data import BP_HULL, BP_T2_MOD, COMP_A, HULL, bpo, character, make_input
from .test_planner import INVENTOR, t2_input

FIVE_SLOTS = {3387: 4}
NO_COMP = BuildRules(item_blacklist=frozenset({COMP_A}))


def hull_input(**kw):
    kw.setdefault("blueprints", (bpo(BP_HULL),))
    return make_input([(HULL, 10)], characters=(character(skills=FIVE_SLOTS),), rules=NO_COMP, **kw)


def test_bpc_option_finds_the_fastest_count():
    # One BPO: 10 x 1000 s. Five bought BPCs of 2 runs (TE 20: 2 x 800 s) cover all 10 runs
    # in parallel: 1600 s. Four plus the BPO's 2 runs at TE 0 would end at 2000 s.
    opts = purchase_options(hull_input(), BP_HULL)
    assert opts.total_seconds == 10000
    bpcs = next(o for o in opts.options if o.kind == "bpcs")
    assert (bpcs.count, bpcs.runs_per_bpc, bpcs.total_seconds) == (5, 2, 1600)
    assert bpcs.seconds_saved == 8400
    assert bpcs.purchase_cost is None  # BPCs have no market price
    assert bpcs.choice == BlueprintChoice(buy_bpcs=5, bpc_runs=2)
    assert "the plan finishes 2h 20m sooner" in bpcs.reason.text
    assert "price not set" in bpcs.reason.text


def test_bpc_option_uses_the_price_you_set():
    choices = {BP_HULL: BlueprintChoice(bpc_price=3_000_000.0)}
    bpcs = next(
        o
        for o in purchase_options(hull_input(choices=choices), BP_HULL).options
        if o.kind == "bpcs"
    )
    assert bpcs.purchase_cost == 5 * 3_000_000


def test_extra_bpo_option_is_priced_from_the_market():
    prices = {BP_HULL: Price(5_000_000.0, None)}
    bpo_opt = next(
        o for o in purchase_options(hull_input(prices=prices), BP_HULL).options if o.kind == "bpo"
    )
    assert (bpo_opt.count, bpo_opt.me, bpo_opt.te) == (1, 0, 0)
    assert bpo_opt.total_seconds == 5000  # 5 + 5 runs in parallel
    assert bpo_opt.purchase_cost == 5_000_000
    assert bpo_opt.choice == BlueprintChoice(extra_bpos=1)


def test_no_extra_bpo_for_invented_blueprints():
    inp = t2_input(characters=(character(skills={**INVENTOR, **FIVE_SLOTS}),))
    kinds = [o.kind for o in purchase_options(inp, BP_T2_MOD).options]
    assert "bpo" not in kinds


def test_options_only_for_manufacturing():
    opts = purchase_options(hull_input(), 999999)
    assert opts.options == () and opts.note
    assert Activity.MANUFACTURING  # imported for the message only
