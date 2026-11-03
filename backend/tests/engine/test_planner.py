import pytest

from engine import PlanError, plan
from engine.types import (
    Activity,
    BlueprintChoice,
    BlueprintSource,
    BuildCategory,
    BuildRules,
    ItemDecision,
    Price,
    ReasonCode,
)

from .data import (
    ACCELERANT,
    ADV_COMPONENT_TE_RIG,
    BP_COMP_A,
    BP_HULL,
    BP_T1_MOD,
    BP_T2_MOD,
    COMP_A,
    COMPOSITE,
    COMPOSITE_ME_RIG,
    DATACORE,
    DECRYPTOR,
    ENCRYPTION,
    F_COMPOSITE,
    F_INTERMEDIATE,
    HULL,
    HULL_B,
    INTERMEDIATE,
    MEDIUM_SHIP_ME_RIG,
    MEX,
    MOON_GOO,
    PYE,
    SCIENCE_1,
    SCIENCE_2,
    T2_MOD,
    TRIT,
    athanor,
    azbel,
    bpc,
    bpo,
    character,
    game,
    make_input,
    raitaru,
)


def item(result, type_id):
    return next(i for i in result.items if i.type_id == type_id)


def bp(result, type_id):
    return next(b for b in result.blueprints if b.type_id == type_id)


def jobs_for(result, bp_id, activity=None):
    return [
        j
        for j in result.jobs
        if j.blueprint_type_id == bp_id and (activity is None or j.activity == activity)
    ]


def buy(result, type_id):
    return next((s.quantity for s in result.shopping_list if s.type_id == type_id), 0)


# --- materials and merging ---------------------------------------------------


def test_me_rounding_is_per_job():
    r = plan(make_input([(COMP_A, 10)], blueprints=(bpo(BP_COMP_A, me=10),)))
    assert buy(r, TRIT) == 27
    assert buy(r, PYE) == 90


def test_shared_components_merge_across_lines():
    r = plan(
        make_input(
            [(HULL, 1), (HULL_B, 1)],
            blueprints=(bpo(BP_COMP_A), bpo(BP_HULL), bpo(2003)),
        )
    )
    comp = bp(r, BP_COMP_A)
    assert comp.runs == 12
    assert len(jobs_for(r, BP_COMP_A)) == 1
    assert buy(r, TRIT) == 100 + 36
    assert buy(r, MEX) == 50


def test_assets_cover_inputs_but_not_plan_lines():
    r = plan(
        make_input(
            [(HULL, 1)],
            blueprints=(bpo(BP_COMP_A), bpo(BP_HULL)),
            assets={COMP_A: 5, HULL: 3, TRIT: 10},
        )
    )
    assert item(r, HULL).produced == 1
    assert item(r, HULL).on_hand_used == 0
    assert item(r, COMP_A).on_hand_used == 5
    assert bp(r, BP_COMP_A).runs == 2
    assert buy(r, TRIT) == 100 + 6 - 10


def test_items_with_no_demand_are_omitted():
    r = plan(
        make_input(
            [(HULL, 1)],
            blueprints=(bpo(BP_COMP_A), bpo(BP_HULL)),
            assets={COMP_A: 7},
        )
    )
    assert all(i.type_id != PYE for i in r.items)
    assert all(b.type_id != BP_COMP_A for b in r.blueprints)


def test_line_without_blueprint_is_bought_with_warning():
    r = plan(make_input([(TRIT, 5)]))
    assert item(r, TRIT).reason.code == ReasonCode.LINE_NOT_BUILDABLE
    assert buy(r, TRIT) == 5
    assert any(w.code == ReasonCode.LINE_NOT_BUILDABLE for w in r.warnings)


def test_non_positive_quantity_rejected():
    with pytest.raises(PlanError):
        plan(make_input([(HULL, 0)]))


# --- build rules ---------------------------------------------------------------


def test_blacklist_stops_the_tree():
    r = plan(
        make_input(
            [(HULL, 1)],
            blueprints=(bpo(BP_HULL),),
            rules=BuildRules(item_blacklist=frozenset({COMP_A})),
        )
    )
    assert item(r, COMP_A).decision == ItemDecision.BUY
    assert item(r, COMP_A).reason.code == ReasonCode.BUY_BLACKLIST
    assert buy(r, COMP_A) == 7
    assert buy(r, PYE) == 0


def test_category_rule_buys_and_names_the_rule():
    r = plan(
        make_input(
            [(HULL, 1)],
            blueprints=(bpo(BP_HULL),),
            rules=BuildRules(buy_categories=frozenset({BuildCategory.ADVANCED_COMPONENTS})),
        )
    )
    row = item(r, COMP_A)
    assert row.reason.code == ReasonCode.BUY_RULE
    assert "advanced_components" in row.reason.text
    assert row.build_category == BuildCategory.ADVANCED_COMPONENTS


def test_plan_line_is_built_even_if_its_category_is_bought():
    r = plan(
        make_input(
            [(COMP_A, 1)],
            blueprints=(bpo(BP_COMP_A),),
            rules=BuildRules(buy_categories=frozenset({BuildCategory.ADVANCED_COMPONENTS})),
        )
    )
    assert item(r, COMP_A).decision == ItemDecision.BUILD


def test_reaction_intermediate_vs_composite_categories():
    r = plan(
        make_input(
            [(COMPOSITE, 200)],
            blueprints=(bpo(F_COMPOSITE),),
            rules=BuildRules(buy_categories=frozenset({BuildCategory.REACTION_INTERMEDIATE})),
        )
    )
    assert item(r, COMPOSITE).build_category == BuildCategory.REACTION_COMPOSITE
    assert item(r, INTERMEDIATE).build_category == BuildCategory.REACTION_INTERMEDIATE
    assert item(r, INTERMEDIATE).reason.code == ReasonCode.BUY_RULE
    assert buy(r, INTERMEDIATE) == 100


def test_reaction_uses_reactor_rig_and_has_no_me():
    r = plan(
        make_input(
            [(COMPOSITE, 200)],
            blueprints=(bpo(F_COMPOSITE), bpo(F_INTERMEDIATE)),
            stations=(athanor((COMPOSITE_ME_RIG,)),),
        )
    )
    job = jobs_for(r, F_COMPOSITE)[0]
    assert job.activity == Activity.REACTION
    assert job.me_reason.code == ReasonCode.ME_REACTION
    # 100 x (1 - 0.02 x 1.1 nullsec) = 97.8 -> 98
    assert job.materials[0].quantity == 98
    assert buy(r, MOON_GOO) == 98


# --- blueprint sources ---------------------------------------------------------


def test_owned_bpcs_used_best_me_first():
    r = plan(
        make_input(
            [(COMP_A, 12)],
            blueprints=(bpc(BP_COMP_A, 5, me=10), bpc(BP_COMP_A, 10, me=8)),
        )
    )
    jobs = sorted(jobs_for(r, BP_COMP_A), key=lambda j: -j.me)
    assert [(j.runs, j.me) for j in jobs] == [(5, 10), (7, 8)]
    assert bp(r, BP_COMP_A).sources == (BlueprintSource.BPC,)


def test_missing_blueprint_planned_at_me0_with_warning():
    r = plan(make_input([(COMP_A, 2)]))
    job = jobs_for(r, BP_COMP_A)[0]
    assert job.source == BlueprintSource.MISSING
    assert job.me == 0
    assert any(w.code == ReasonCode.SOURCE_MISSING for w in r.warnings)


def test_me_override_applies_to_all_jobs():
    r = plan(
        make_input(
            [(HULL, 1)],
            blueprints=(bpo(BP_COMP_A), bpo(BP_HULL, me=10)),
            choices={BP_HULL: BlueprintChoice(me_override=0)},
        )
    )
    job = jobs_for(r, BP_HULL)[0]
    assert job.me == 0
    assert job.me_reason.code == ReasonCode.ME_OVERRIDE
    assert "ME 10" in job.me_reason.text


# --- stations and fees ---------------------------------------------------------


def test_station_picked_by_material_bonus_then_time():
    r = plan(
        make_input(
            [(HULL, 1)],
            blueprints=(bpo(BP_COMP_A), bpo(BP_HULL)),
            stations=(raitaru((ADV_COMPONENT_TE_RIG,)), azbel((MEDIUM_SHIP_ME_RIG,))),
        )
    )
    assert bp(r, BP_HULL).station.station_id == 2  # ME rig wins
    assert bp(r, BP_COMP_A).station.station_id == 1  # same ME, TE rig wins
    assert bp(r, BP_HULL).station.reason.code == ReasonCode.STATION_BEST


def test_no_station_warns_and_has_no_fee():
    r = plan(make_input([(COMP_A, 1)], blueprints=(bpo(BP_COMP_A),)))
    assert bp(r, BP_COMP_A).station.station_id is None
    assert jobs_for(r, BP_COMP_A)[0].cost.fee is None


def test_job_fee_and_alpha_tax():
    prices = {COMP_A: Price(None, 1000.0), TRIT: Price(None, 5.0)}
    common = {
        "blueprints": (bpo(BP_HULL),),
        "stations": (azbel(),),
        "prices": prices,
        "rules": BuildRules(item_blacklist=frozenset({COMP_A})),
    }
    omega = plan(make_input([(HULL, 1)], characters=(character(),), **common))
    alpha = plan(make_input([(HULL, 1)], characters=(character(alpha=True),), **common))
    eiv = 7 * 1000 + 100 * 5
    assert jobs_for(omega, BP_HULL)[0].cost.estimated_item_value == eiv
    assert jobs_for(omega, BP_HULL)[0].cost.fee == pytest.approx(eiv * (0.05 * 0.96 + 0.01 + 0.04))
    assert jobs_for(alpha, BP_HULL)[0].cost.fee == pytest.approx(
        eiv * (0.05 * 0.96 + 0.01 + 0.04 + 0.0025)
    )
    assert omega.costs.job_fees[Activity.MANUFACTURING] == pytest.approx(eiv * 0.098)


def test_costs_total_shopping_and_fees():
    prices = {TRIT: Price(2.0, None), PYE: Price(3.0, None)}
    r = plan(make_input([(COMP_A, 1)], blueprints=(bpo(BP_COMP_A),), prices=prices))
    assert r.costs.materials == 3 * 2.0 + 10 * 3.0
    assert r.costs.total == r.costs.materials


def test_unpriced_items_reported():
    r = plan(make_input([(COMP_A, 1)], blueprints=(bpo(BP_COMP_A),)))
    assert set(r.costs.unpriced_type_ids) == {TRIT, PYE}
    assert any(w.code == ReasonCode.PRICE_MISSING for w in r.warnings)


# --- invention -----------------------------------------------------------------

INVENTOR = {ENCRYPTION: 4, SCIENCE_1: 4, SCIENCE_2: 4}


def t2_input(**kw):
    kw.setdefault("blueprints", (bpo(BP_T1_MOD), bpo(BP_COMP_A)))
    kw.setdefault("characters", (character(skills=INVENTOR),))
    return make_input([(T2_MOD, 20)], **kw)


def test_invented_bpc_base_me_is_plus_two():
    r = plan(t2_input())
    jobs = jobs_for(r, BP_T2_MOD, Activity.MANUFACTURING)
    assert [(j.runs, j.me, j.te) for j in jobs] == [(10, 2, 4), (10, 2, 4)]
    assert jobs[0].me_reason.code == ReasonCode.ME_INVENTED
    # 10 x 10 x 0.98 = 98 per job, plus 3 per Comp A run (ceil(20 x 0.98) per job)
    assert bp(r, BP_COMP_A).runs == 40
    assert buy(r, TRIT) == 2 * 98 + 3 * 40


def test_invention_attempts_and_datacores():
    r = plan(t2_input())
    inv = bp(r, BP_T2_MOD).invention
    p = 0.34 * (1 + 8 / 30 + 4 / 40)
    assert inv.probability == pytest.approx(p)
    assert inv.bpcs_needed == 2
    assert inv.attempts == 5
    assert buy(r, DATACORE) == 10
    assert item(r, DATACORE).reason.code == ReasonCode.BUY_INVENTION_INPUT


def test_invention_job_chain_dependencies():
    r = plan(t2_input())
    copy = jobs_for(r, BP_T1_MOD, Activity.COPYING)
    inv = jobs_for(r, BP_T1_MOD, Activity.INVENTION)
    t2 = jobs_for(r, BP_T2_MOD, Activity.MANUFACTURING)
    assert len(copy) == 1 and copy[0].copies == 1 and copy[0].runs == 5
    assert inv[0].depends_on == (copy[0].job_id,)
    for j in t2:
        assert inv[0].job_id in j.depends_on
        assert j.schedule.start_seconds >= inv[0].schedule.end_seconds


def test_invented_me_flows_into_materials_and_sub_runs():
    r = plan(
        t2_input(
            game=game([ACCELERANT]),
            choices={BP_T2_MOD: BlueprintChoice(decryptor=DECRYPTOR)},
        )
    )
    jobs = jobs_for(r, BP_T2_MOD, Activity.MANUFACTURING)
    assert sorted((j.runs, j.me) for j in jobs) == [(9, 4), (11, 4)]
    # Trit: ceil(110 x 0.96)=106 + ceil(90 x 0.96)=87
    assert buy(r, TRIT) == 106 + 87 + 3 * bp(r, BP_COMP_A).runs
    # Comp A runs follow the invented ME: ceil(22 x .96)=22 + ceil(18 x .96)=18
    assert bp(r, BP_COMP_A).runs == 40
    assert bp(r, BP_T2_MOD).invention.reason.code == ReasonCode.DECRYPTOR_CHOSEN


def test_decryptor_none_choice():
    r = plan(
        t2_input(
            game=game([ACCELERANT]),
            choices={BP_T2_MOD: BlueprintChoice(decryptor="none")},
        )
    )
    assert bp(r, BP_T2_MOD).invention.decryptor_type_id is None
    assert len(bp(r, BP_T2_MOD).invention.options) == 2


def test_auto_decryptor_picks_lowest_total_cost():
    prices = {DATACORE: Price(1_000_000.0, None), DECRYPTOR: Price(10.0, None)}
    r = plan(t2_input(game=game([ACCELERANT]), prices=prices))
    inv = bp(r, BP_T2_MOD).invention
    assert inv.decryptor_type_id == DECRYPTOR
    assert inv.reason.code == ReasonCode.DECRYPTOR_AUTO
    assert inv.attempts == 4
    assert buy(r, DECRYPTOR) == 4


def test_invention_without_t1_blueprint_warns():
    r = plan(t2_input(blueprints=()))
    assert any("T1 copy runs" in w.text for w in r.warnings)
    inv_jobs = jobs_for(r, BP_T1_MOD, Activity.INVENTION)
    assert inv_jobs[0].source == BlueprintSource.MISSING


# --- schedule ------------------------------------------------------------------


def test_components_finish_before_hull_starts():
    r = plan(
        make_input(
            [(HULL, 1)],
            blueprints=(bpo(BP_COMP_A), bpo(BP_HULL)),
            characters=(character(skills={3380: 5, 3388: 5}),),
        )
    )
    comp = jobs_for(r, BP_COMP_A)[0]
    hull = jobs_for(r, BP_HULL)[0]
    assert comp.job_id in hull.depends_on
    assert comp.schedule.end_seconds == pytest.approx(100 * 7 * 0.8 * 0.85)
    assert hull.schedule.start_seconds == comp.schedule.end_seconds
    assert r.total_seconds == hull.schedule.end_seconds


def test_parallel_jobs_use_separate_slots():
    r = plan(
        make_input(
            [(COMP_A, 12)],
            blueprints=(bpc(BP_COMP_A, 5), bpc(BP_COMP_A, 10)),
            characters=(character(skills={3387: 1}),),
        )
    )
    starts = [j.schedule.start_seconds for j in jobs_for(r, BP_COMP_A)]
    assert starts == [0.0, 0.0]


def test_job_unscheduled_when_no_character_may_run_it():
    r = plan(
        make_input(
            [(COMP_A, 1)],
            blueprints=(bpo(BP_COMP_A),),
            characters=(character(activities=frozenset({Activity.COPYING})),),
        )
    )
    job = jobs_for(r, BP_COMP_A)[0]
    assert job.schedule.character_id is None
    assert job.schedule.reason.code == ReasonCode.UNSCHEDULED_NO_CHARACTER


def test_schedule_picks_faster_character():
    r = plan(
        make_input(
            [(COMP_A, 1)],
            blueprints=(bpo(BP_COMP_A),),
            characters=(
                character(1, "Slow"),
                character(2, "Fast", skills={3380: 5}),
            ),
        )
    )
    assert jobs_for(r, BP_COMP_A)[0].schedule.character_id == 2
