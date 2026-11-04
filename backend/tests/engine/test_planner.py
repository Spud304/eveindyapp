from dataclasses import replace
from itertools import pairwise

import pytest

from engine import PlanError
from engine.formulas import StationBonuses
from engine.planner import _bpo_layout, _CopyPlan, _Spec, _water_fill
from engine.types import (
    Activity,
    BlueprintChoice,
    BlueprintData,
    BlueprintSource,
    BuildCategory,
    BuildRules,
    GameData,
    ItemDecision,
    Material,
    PlanLine,
    Price,
    ReasonCode,
    Recipe,
    SkillRequirement,
    SolarSystem,
)

from .data import (
    ACCELERANT,
    ADV_COMPONENT_TE_RIG,
    BLUEPRINTS,
    BP_COMP_A,
    BP_HULL,
    BP_T1_MOD,
    BP_T2_MOD,
    COMP_A,
    COMPOSITE,
    COMPOSITE_ME_RIG,
    COPY_TIME_RIG,
    DATACORE,
    DECRYPTOR,
    ENCRYPTION,
    F_COMPOSITE,
    F_INTERMEDIATE,
    HS_SYSTEM,
    HULL,
    HULL_B,
    INTERMEDIATE,
    MEDIUM_SHIP_ME_RIG,
    MEX,
    MOON_GOO,
    PYE,
    SCIENCE_1,
    SCIENCE_2,
    SYSTEMS,
    T1_MOD,
    T2_MOD,
    TRIT,
    athanor,
    azbel,
    bpc,
    bpo,
    character,
    game,
    lab,
    make_input,
    raitaru,
)
from .invariants import checked_plan as plan


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


# --- which blueprint makes a product -------------------------------------------


def _game_with(extra: BlueprintData, first: bool) -> GameData:
    """The test game data plus `extra`, inserted before or after the others, so a test
    can show the choice does not depend on load order."""
    base = game()
    ordered = [extra, *base.blueprints.values()] if first else [*base.blueprints.values(), extra]
    return replace(base, blueprints={b.type_id: b for b in ordered})


@pytest.mark.parametrize("first", [True, False])
def test_unpublished_reaction_formula_is_not_the_producer(first):
    # Like "Test Reaction Blueprint" 45732 next to the Tungsten Carbide formula 46207:
    # unpublished, a lower type id, and a different recipe for the same product.
    test_formula = BlueprintData(
        F_COMPOSITE - 2,
        1,
        reaction=Recipe(
            time_seconds=360,
            materials=(Material(MOON_GOO, 1),),
            product_type_id=COMPOSITE,
            product_quantity=20,
        ),
        published=False,
    )
    r = plan(
        make_input(
            [(COMPOSITE, 200)],
            game=_game_with(test_formula, first),
            blueprints=(bpo(F_COMPOSITE), bpo(F_INTERMEDIATE)),
        )
    )
    assert not jobs_for(r, test_formula.type_id)
    assert jobs_for(r, F_COMPOSITE)[0].materials == (Material(INTERMEDIATE, 100),)
    assert item(r, INTERMEDIATE).build_category == BuildCategory.REACTION_INTERMEDIATE


@pytest.mark.parametrize("first", [True, False])
def test_unpublished_manufacturing_blueprint_is_not_the_producer(first):
    old = BlueprintData(
        BP_HULL - 2, 10, manufacturing=_mfg_recipe(HULL, [(TRIT, 1)]), published=False
    )
    r = plan(make_input([(HULL, 1)], game=_game_with(old, first), blueprints=(bpo(BP_HULL),)))
    assert not jobs_for(r, old.type_id)
    assert jobs_for(r, BP_HULL, Activity.MANUFACTURING)


@pytest.mark.parametrize("published", [True, False])
@pytest.mark.parametrize("first", [True, False])
def test_invention_source_is_chosen_by_published_then_type_id(first, published):
    t1 = BLUEPRINTS[BP_T1_MOD]
    other = replace(t1, type_id=BP_T1_MOD - 2, published=published)
    r = plan(t2_input(game=_game_with(other, first)))
    expected = other.type_id if published else BP_T1_MOD
    assert bp(r, BP_T2_MOD).invention.t1_blueprint_type_id == expected


def _mfg_recipe(product, mats):
    return Recipe(
        time_seconds=100,
        materials=tuple(Material(t, q) for t, q in mats),
        product_type_id=product,
        product_quantity=1,
    )


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
    cost = jobs_for(omega, BP_HULL)[0].cost
    assert cost.estimated_item_value == eiv
    # 7500 x 0.05 x 0.96 = 360; tax 1% = 75; SCC 4% = 300
    assert (cost.job_cost, cost.facility_tax, cost.scc_surcharge) == (360, 75, 300)
    assert cost.fee == 735
    # alpha adds 7500 x 0.25% = 18.75 to the job cost before it is rounded: 378.75 -> 379
    assert jobs_for(alpha, BP_HULL)[0].cost.fee == 379 + 75 + 300
    assert omega.costs.job_fees[Activity.MANUFACTURING] == 735


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


def test_t1_copying_and_t1_manufacturing_share_the_bpo():
    # The plan builds T1 modules and copies the same T1 BPO for invention.
    inv = t2_input()
    r = plan(
        make_input(
            [(T2_MOD, 20), (T1_MOD, 50)],
            blueprints=inv.blueprints,
            characters=(character(1, skills=INVENTOR), character(2, skills=INVENTOR)),
        )
    )
    on_bpo = sorted(
        [
            *jobs_for(r, BP_T1_MOD, Activity.COPYING),
            *jobs_for(r, BP_T1_MOD, Activity.MANUFACTURING),
        ],
        key=lambda j: j.schedule.start_seconds,
    )
    assert len(on_bpo) == 2
    assert on_bpo[1].schedule.start_seconds >= on_bpo[0].schedule.end_seconds


def test_t3_from_relics_is_not_planned_as_invention():
    # A relic: an invention activity and nothing to copy or build.
    t1 = BLUEPRINTS[BP_T1_MOD]
    relic = BlueprintData(9999, 1, invention=t1.invention)
    blueprints = {k: v for k, v in BLUEPRINTS.items() if k != BP_T1_MOD} | {9999: relic}
    r = plan(make_input([(T2_MOD, 10)], game=replace(game(), blueprints=blueprints)))
    assert bp(r, BP_T2_MOD).invention is None
    assert [j.source for j in jobs_for(r, BP_T2_MOD)] == [BlueprintSource.MISSING]
    assert any("reverse engineering" in w.text for w in r.warnings)
    assert not jobs_for(r, 9999)


def test_a_copy_with_more_than_thirty_days_of_runs_is_split_on_the_same_item():
    # 1000 s a run: 30 days is 2,592 runs; the job check applies to copies too. [client]
    r = plan(make_input([(HULL, 3000)], blueprints=(bpc(BP_HULL, 3000), bpo(BP_COMP_A))))
    jobs = sorted(
        jobs_for(r, BP_HULL, Activity.MANUFACTURING), key=lambda j: j.schedule.start_seconds
    )
    assert sorted(j.runs for j in jobs) == [408, 2592]
    assert {j.blueprint_item_id for j in jobs} == {BP_HULL * 10 + 3000}
    assert jobs[1].schedule.start_seconds >= jobs[0].schedule.end_seconds  # one copy, one job


def test_invention_runs_only_on_the_inventors_whose_chance_was_used():
    # The weak inventor has 5 science slots and would take jobs if allowed; the strong one 1.
    weak = character(2, "Weak", skills={ENCRYPTION: 1, SCIENCE_1: 1, SCIENCE_2: 1, 3406: 4})
    r = plan(t2_input(characters=(character(skills=INVENTOR), weak)))
    inv = bp(r, BP_T2_MOD).invention
    assert "Invention jobs run only on Builder" in inv.probability_reason.text
    inv_jobs = jobs_for(r, BP_T1_MOD, Activity.INVENTION)
    assert inv_jobs and {j.schedule.character_id for j in inv_jobs} == {1}
    assert all("1 eligible character" in j.schedule.reason.text for j in inv_jobs)
    # Copying is not pinned: the weak character may still make the T1 copies.
    copy_reason = jobs_for(r, BP_T1_MOD, Activity.COPYING)[0].schedule.reason.text
    assert "2 eligible character" in copy_reason


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


def test_auto_decryptor_without_prices_says_so():
    r = plan(t2_input(game=game([ACCELERANT])))
    inv = bp(r, BP_T2_MOD).invention
    assert "no prices" in inv.reason.text
    assert inv.attempts == min(o.attempts for o in inv.options)


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


def test_copy_and_invention_use_lab_station_time_bonuses():
    r = plan(t2_input(stations=(lab((COPY_TIME_RIG,)),)))
    copy = jobs_for(r, BP_T1_MOD, Activity.COPYING)[0]
    inv = jobs_for(r, BP_T1_MOD, Activity.INVENTION)[0]
    assert copy.station_id == inv.station_id == 5
    # 600 s x 5 runs x Raitaru 0.85 x rig 0.8 (no skills)
    assert copy.schedule.end_seconds - copy.schedule.start_seconds == pytest.approx(
        600 * 5 * 0.85 * 0.8
    )
    # 3600 s x 5 attempts x Raitaru 0.85 (copy rig does not apply to invention)
    assert inv.schedule.end_seconds - inv.schedule.start_seconds == pytest.approx(3600 * 5 * 0.85)
    assert inv.cost.reason.code == ReasonCode.FEE_COMPUTED  # no prices, so 0


def test_copy_and_invention_fees():
    # T1 module EIV/run = 5 Trit x 10 = 50; T2 module EIV/run = 10 x 10 + 2 x 1000 = 2100
    prices = {TRIT: Price(None, 10.0), COMP_A: Price(None, 1000.0)}
    systems = {
        **SYSTEMS,
        HS_SYSTEM: SolarSystem(
            HS_SYSTEM, "High", 0.9, {Activity.COPYING: 0.10, Activity.INVENTION: 0.10}
        ),
    }
    r = plan(t2_input(stations=(lab(),), prices=prices, systems=systems))
    copy = jobs_for(r, BP_T1_MOD, Activity.COPYING)[0]
    inv = jobs_for(r, BP_T1_MOD, Activity.INVENTION)[0]
    # copy base = 50 x 2% x 5 runs x 1 copy = 5; job cost 5 x 0.10 x Raitaru 0.97 = 0.485 -> 0
    assert copy.cost.base == 5 and copy.cost.job_cost == 0 and copy.cost.scc_surcharge == 0
    # invention base = 2100 x 2% x 5 attempts = 210; job cost 210 x 0.1 x 0.97 = 20.37 -> 20
    assert inv.cost.base == 210 and inv.cost.job_cost == 20
    assert inv.cost.scc_surcharge == 8  # 210 x 4% = 8.4
    assert r.costs.job_fees[Activity.INVENTION] == inv.cost.fee


def test_bpo_job_split_at_thirty_days():
    # Hull: 1000 s/run, no TE, no station -> 2592 runs per job at most
    r = plan(make_input([(HULL, 6000)], blueprints=(bpo(BP_HULL), bpo(BP_COMP_A))))
    hull_jobs = jobs_for(r, BP_HULL)
    assert [j.runs for j in hull_jobs] == [2592, 2592, 816]
    assert "30-day job limit" in bp(r, BP_HULL).source_reason.text


def test_jobs_on_one_bpo_run_one_after_another():
    # One BPO is in one job at a time, even with free slots on other characters.
    r = plan(
        make_input(
            [(HULL, 6000)],
            blueprints=(bpo(BP_HULL), bpo(BP_COMP_A)),
            characters=(character(1), character(2), character(3)),
        )
    )
    on_bpo = sorted(
        (
            j
            for j in jobs_for(r, BP_HULL)
            if j.activity == Activity.COPYING or j.source == BlueprintSource.BPO
        ),
        key=lambda j: j.schedule.start_seconds,
    )
    assert len(on_bpo) >= 3
    for before, after in pairwise(on_bpo):
        assert after.schedule.start_seconds >= before.schedule.end_seconds


def test_missing_blueprint_jobs_run_one_after_another():
    r = plan(make_input([(HULL, 6000)], characters=(character(1), character(2))))
    hull = sorted(jobs_for(r, BP_HULL), key=lambda j: j.schedule.start_seconds)
    assert len(hull) == 3
    for before, after in pairwise(hull):
        assert after.schedule.start_seconds >= before.schedule.end_seconds


def test_owned_bpcs_of_one_blueprint_run_in_parallel():
    r = plan(
        make_input(
            [(HULL, 20)],
            blueprints=(bpc(BP_HULL, 10, item_id=1), bpc(BP_HULL, 10, item_id=2), bpo(BP_COMP_A)),
            characters=(character(1), character(2)),
        )
    )
    starts = {j.schedule.start_seconds for j in jobs_for(r, BP_HULL)}
    comp_end = max(j.schedule.end_seconds for j in jobs_for(r, BP_COMP_A))
    assert starts == {comp_end}


def test_invention_jobs_split_by_thirty_days():
    # 3600 s per attempt -> 720 attempts per job; capped at 500 for invention
    r = plan(t2_input())
    assert all(j.runs <= 500 for j in jobs_for(r, BP_T1_MOD, Activity.INVENTION))


def test_required_skill_shortens_manufacturing_time():
    g = game()
    req = SkillRequirement(3397, 1)
    hull = g.blueprints[BP_COMP_A]
    blueprints = dict(g.blueprints)
    blueprints[BP_COMP_A] = BlueprintData(
        hull.type_id,
        hull.max_production_limit,
        manufacturing=Recipe(
            time_seconds=100,
            materials=hull.manufacturing.materials,
            skills=(req,),
            product_type_id=COMP_A,
            product_quantity=1,
        ),
    )
    g2 = GameData(types=g.types, blueprints=blueprints, skill_time_bonuses={3397: -1.0})
    r = plan(
        make_input(
            [(COMP_A, 10)],
            game=g2,
            blueprints=(bpo(BP_COMP_A),),
            characters=(character(skills={3397: 5}),),
        )
    )
    job = jobs_for(r, BP_COMP_A)[0]
    assert job.schedule.end_seconds == pytest.approx(100 * 10 * 0.95)


# --- auto-copy -----------------------------------------------------------------

FIVE_MFG_SLOTS = {3387: 4}


def test_auto_copy_while_the_bpo_waits_for_inputs():
    # Comp A: 70 runs x 100 s = 7000 s on one BPO. Unsplit, the hull starts after it:
    # 7000 + 10 x 1000 = 17000 s. Split 5 ways, the BPO copies 4 x 2 runs (4 x 2 x 800 =
    # 6400 s) while Comp A builds, then 5 jobs of 2 runs finish at 7000 + 2000 = 9000 s.
    r = plan(
        make_input(
            [(HULL, 10)],
            blueprints=(bpo(BP_HULL), bpo(BP_COMP_A)),
            characters=(character(skills=FIVE_MFG_SLOTS),),
        )
    )
    assert r.total_seconds == 9000
    [copy] = jobs_for(r, BP_HULL, Activity.COPYING)
    assert (copy.copies, copy.runs, copy.schedule.start_seconds) == (4, 2, 0)
    assert copy.cost.base == 0  # no adjusted prices in this input
    mfg = jobs_for(r, BP_HULL, Activity.MANUFACTURING)
    assert sorted(j.source for j in mfg) == [BlueprintSource.BPO] + [BlueprintSource.COPY] * 4
    assert all(j.runs == 2 and j.schedule.start_seconds == 7000 for j in mfg)
    assert all(copy.job_id in j.depends_on for j in mfg)
    plan_bp = bp(r, BP_HULL)
    assert plan_bp.sources == (BlueprintSource.BPO, BlueprintSource.COPY)
    assert plan_bp.source_reason.code == ReasonCode.SOURCE_COPY
    assert "4 copies of 2 runs" in plan_bp.source_reason.text
    assert "finishes 2h 13m sooner" in plan_bp.source_reason.text  # 17000 - 9000 s
    assert plan_bp.source_reason.text.endswith("; copy job fee unknown.")  # no station


def test_no_auto_copy_when_the_saving_is_small():
    # Inputs are bought, so the BPO could start at once. Unsplit: 10000 s. The best split
    # (5 runs copied in 4000 s, then 5 + 5 runs) ends at 9000 s: under an hour saved.
    r = plan(
        make_input(
            [(HULL, 10)],
            blueprints=(bpo(BP_HULL),),
            characters=(character(skills=FIVE_MFG_SLOTS),),
            rules=BuildRules(item_blacklist=frozenset({COMP_A})),
        )
    )
    assert r.total_seconds == 10000
    assert jobs_for(r, BP_HULL, Activity.COPYING) == []
    assert [j.source for j in jobs_for(r, BP_HULL)] == [BlueprintSource.BPO]


def test_no_auto_copy_with_one_manufacturing_slot():
    r = plan(make_input([(HULL, 10)], blueprints=(bpo(BP_HULL), bpo(BP_COMP_A))))
    assert jobs_for(r, BP_HULL, Activity.COPYING) == []
    assert r.total_seconds == 17000


def test_no_auto_copy_for_owned_bpcs():
    r = plan(
        make_input(
            [(HULL, 10)],
            blueprints=(bpc(BP_HULL, 10), bpo(BP_COMP_A)),
            characters=(character(skills=FIVE_MFG_SLOTS),),
        )
    )
    assert jobs_for(r, BP_HULL, Activity.COPYING) == []


def test_owned_bpcs_are_used_before_the_bpo():
    r = plan(
        make_input(
            [(HULL, 25)],
            blueprints=(
                bpo(BP_HULL, me=10),
                bpc(BP_HULL, 10, me=10, item_id=1),
                bpc(BP_HULL, 10, me=10, item_id=2),
                bpo(BP_COMP_A),
            ),
        )
    )
    hull = jobs_for(r, BP_HULL)
    assert sorted((j.source, j.runs) for j in hull) == [
        (BlueprintSource.BPC, 10),
        (BlueprintSource.BPC, 10),
        (BlueprintSource.BPO, 5),
    ]
    assert bp(r, BP_HULL).source_reason.text == (
        "2 owned BPC(s) cover 20 runs; owned BPO for 5 runs."
    )


def test_bpcs_with_lower_me_than_the_bpo_are_not_used():
    r = plan(
        make_input(
            [(HULL, 10)],
            blueprints=(bpo(BP_HULL, me=10), bpc(BP_HULL, 10, me=8), bpo(BP_COMP_A)),
        )
    )
    assert [j.source for j in jobs_for(r, BP_HULL)] == [BlueprintSource.BPO]
    assert "1 owned BPC(s) with lower ME than the BPO (ME 10) not used" in (
        bp(r, BP_HULL).source_reason.text
    )


def test_auto_copy_keeps_owned_bpc_jobs():
    r = plan(
        make_input(
            [(HULL, 30)],
            blueprints=(bpo(BP_HULL), bpc(BP_HULL, 10, item_id=1), bpo(BP_COMP_A)),
            characters=(character(skills=FIVE_MFG_SLOTS),),
        )
    )
    ids = [j.job_id for j in r.jobs]
    assert len(ids) == len(set(ids))
    hull = jobs_for(r, BP_HULL, Activity.MANUFACTURING)
    assert [j.runs for j in hull if j.source == BlueprintSource.BPC] == [10]
    assert sum(j.runs for j in hull) == 30
    assert jobs_for(r, BP_HULL, Activity.COPYING)  # the BPO's 20 runs are still split


def test_picked_bpcs_are_used_first_in_the_order_picked():
    # Five 9-run BPCs picked out of six; the unpicked 10-run one has better ME.
    nine = [bpc(BP_HULL, 9, me=8, item_id=i) for i in range(1, 7)]
    best = bpc(BP_HULL, 10, me=10, item_id=99)
    r = plan(
        make_input(
            [],
            lines=(PlanLine("l0", HULL, 45, (5, 4, 3, 2, 1)),),
            blueprints=(*nine, best, bpo(BP_HULL, me=10), bpo(BP_COMP_A)),
        )
    )
    hull = jobs_for(r, BP_HULL)
    assert [(j.source, j.runs, j.me) for j in hull] == [(BlueprintSource.BPC, 9, 8)] * 5
    assert "5 owned BPC(s) cover 45 runs (5 picked for this plan)" in (
        bp(r, BP_HULL).source_reason.text
    )
    assert hull[0].me_reason.text.startswith("BPC picked for this plan 5:")


def test_picked_bpcs_cover_their_runs_and_other_sources_the_rest():
    r = plan(
        make_input(
            [],
            lines=(PlanLine("l0", HULL, 9, (1,)), PlanLine("l1", HULL, 5)),
            blueprints=(bpc(BP_HULL, 9, item_id=1), bpo(BP_HULL), bpo(BP_COMP_A)),
        )
    )
    assert sorted((j.source, j.runs) for j in jobs_for(r, BP_HULL)) == [
        (BlueprintSource.BPC, 9),
        (BlueprintSource.BPO, 5),
    ]


def test_bpo_in_a_running_job_starts_planned_jobs_when_it_ends():
    busy = replace(bpo(BP_HULL), job_activity_id=5, job_ends_in=5000.0)
    r = plan(
        make_input(
            [(HULL, 2)],
            blueprints=(busy,),
            rules=BuildRules(item_blacklist=frozenset({COMP_A})),
        )
    )
    [hull] = jobs_for(r, BP_HULL)
    assert hull.schedule.start_seconds == 5000
    assert r.total_seconds == 5000 + 2000
    assert "the BPO is in a copying job for 1h 23m; these jobs start after" in (
        bp(r, BP_HULL).source_reason.text
    )


def test_bpo_in_a_finished_job_must_be_delivered():
    done = replace(bpo(BP_HULL), job_activity_id=5, job_ends_in=-60.0)
    r = plan(make_input([(HULL, 1)], blueprints=(done, bpo(BP_COMP_A))))
    assert "the BPO is in a finished copying job: deliver it before these jobs start" in (
        bp(r, BP_HULL).source_reason.text
    )


def test_bpcs_in_jobs_are_not_used():
    in_job = replace(bpc(BP_HULL, 10, item_id=1), job_activity_id=1, job_ends_in=100.0)
    r = plan(
        make_input([(HULL, 5)], blueprints=(in_job, bpc(BP_HULL, 5, item_id=2), bpo(BP_COMP_A)))
    )
    assert [j.runs for j in jobs_for(r, BP_HULL)] == [5]
    assert "1 owned BPC(s) in jobs not used" in bp(r, BP_HULL).source_reason.text


def test_owned_t1_bpcs_are_used_for_invention_before_copying():
    # 5 attempts needed (see test_invention_attempts_and_datacores).
    r = plan(t2_input(blueprints=(bpo(BP_T1_MOD), bpc(BP_T1_MOD, 2, item_id=7), bpo(BP_COMP_A))))
    inv = jobs_for(r, BP_T1_MOD, Activity.INVENTION)
    assert sorted(j.runs for j in inv) == [2, 3]
    on_bpc = next(j for j in inv if j.runs == 2)
    assert on_bpc.source == BlueprintSource.BPC and not on_bpc.depends_on
    [copy] = jobs_for(r, BP_T1_MOD, Activity.COPYING)
    assert copy.copies == 1 and copy.runs == 3


def test_copies_being_made_cover_invention():
    incoming = replace(bpc(BP_T1_MOD, 300, item_id=-1), source_job_id=77, available_in=7200.0)
    r = plan(t2_input(blueprints=(bpo(BP_T1_MOD), incoming, bpo(BP_COMP_A))))
    assert jobs_for(r, BP_T1_MOD, Activity.COPYING) == []
    [inv] = jobs_for(r, BP_T1_MOD, Activity.INVENTION)
    assert inv.runs == 5 and inv.schedule.start_seconds == 7200
    assert "Copy being made by job 77" in inv.me_reason.text
    assert "ready in 2h 0m" in inv.me_reason.text


def test_copies_being_made_are_used_for_manufacturing():
    incoming = replace(bpc(BP_HULL, 10, item_id=-1), source_job_id=78, available_in=3000.0)
    r = plan(
        make_input(
            [(HULL, 10)],
            blueprints=(bpo(BP_HULL), incoming),
            rules=BuildRules(item_blacklist=frozenset({COMP_A})),
        )
    )
    [hull] = jobs_for(r, BP_HULL)
    assert hull.source == BlueprintSource.BPC and hull.schedule.start_seconds == 3000
    assert hull.me_reason.text.startswith("Copy being made by job 78")
    assert "1 owned BPC(s) cover 10 runs; 1 of them still being made by copy jobs" in (
        bp(r, BP_HULL).source_reason.text
    )


def test_finished_copy_job_must_be_delivered():
    ready = replace(bpc(BP_HULL, 10, item_id=-1), source_job_id=79, available_in=-5.0)
    r = plan(make_input([(HULL, 10)], blueprints=(ready, bpo(BP_COMP_A))))
    assert jobs_for(r, BP_HULL)[0].me_reason.text.endswith("finished: deliver it first.")


def test_copy_job_layout_respects_thirty_days_per_copy():
    # 1 day per copied run, 10 runs per copy: one job may hold ceil(30 / 10) = 3 copies.
    cp = _CopyPlan(
        prod=None,
        bpo=_Spec(200, 10, 20, BlueprintSource.BPO, None, "item:1"),
        runs=200,
        time_mult=1.0,
        max_per_copy=10,
        copy_recipe=Recipe(time_seconds=86400),
        copy_station=None,
        copy_bonuses=StationBonuses(1.0, 1.0, 1.0, ""),
        cost_mult=1.0,
    )
    specs, parts, per_copy = _bpo_layout(cp, 20)
    assert per_copy == 10
    assert parts == [3, 3, 3, 3, 3, 3, 1]
    assert specs[0].runs == 200 - 19 * 10 and specs[0].lock == "item:1"
    assert all(sp.source == BlueprintSource.COPY and sp.runs == 10 for sp in specs[1:])


# --- spreading runs over owned BPCs --------------------------------------------------------------


def four_hull_bpcs():
    return tuple(bpc(BP_HULL, 10, item_id=i) for i in range(1, 5))


def test_runs_spread_over_more_bpcs_when_slots_are_free():
    # 20 runs: the fewest BPCs is 2 x 10 runs (10000 s); spread over 4 x 5 runs: 5000 s.
    r = plan(
        make_input(
            [(HULL, 20)],
            blueprints=four_hull_bpcs(),
            characters=(character(skills=FIVE_MFG_SLOTS),),
            rules=BuildRules(item_blacklist=frozenset({COMP_A})),
        )
    )
    assert sorted(j.runs for j in jobs_for(r, BP_HULL)) == [5, 5, 5, 5]
    assert r.total_seconds == 5000
    text = bp(r, BP_HULL).source_reason.text
    assert "4 owned BPC(s) cover 20 runs, spread over 4 BPCs so they run in parallel" in text
    assert "finishes 1h 23m sooner than using the fewest (2)" in text


def test_no_spread_with_one_slot():
    r = plan(
        make_input(
            [(HULL, 20)],
            blueprints=four_hull_bpcs(),
            rules=BuildRules(item_blacklist=frozenset({COMP_A})),
        )
    )
    assert sorted(j.runs for j in jobs_for(r, BP_HULL)) == [10, 10]


def test_no_spread_when_the_saving_is_small():
    # 2 runs: 2000 s on one BPC, 1000 s on two; under an hour saved.
    r = plan(
        make_input(
            [(HULL, 2)],
            blueprints=four_hull_bpcs(),
            characters=(character(skills=FIVE_MFG_SLOTS),),
            rules=BuildRules(item_blacklist=frozenset({COMP_A})),
        )
    )
    assert [j.runs for j in jobs_for(r, BP_HULL)] == [2]


def test_water_fill_evens_out_runs():
    assert _water_fill([200, 200, 54, 50], 502) == [199, 199, 54, 50]
    assert _water_fill([10, 10, 10], 20) == [7, 7, 6]
    assert _water_fill([3, 10], 4) == [2, 2]


# --- opt-in purchases -------------------------------------------------------------------------

NO_COMP = BuildRules(item_blacklist=frozenset({COMP_A}))


def test_bought_bpcs_are_used_and_priced():
    choice = BlueprintChoice(buy_bpcs=2, bpc_runs=4, bpc_price=1_000_000.0)
    r = plan(
        make_input(
            [(HULL, 10)],
            blueprints=(bpo(BP_HULL, me=10),),
            choices={BP_HULL: choice},
            rules=NO_COMP,
        )
    )
    hull = jobs_for(r, BP_HULL)
    assert sorted((str(j.source), j.runs, j.me) for j in hull) == [
        ("bought", 4, 10),
        ("bought", 4, 10),
        ("bpo", 2, 10),
    ]
    assert len({j.schedule.start_seconds for j in hull}) == 1  # all in parallel
    assert r.costs.blueprints == 2_000_000
    assert "2 bought BPC(s) of 4 runs (your choice)" in bp(r, BP_HULL).source_reason.text
    assert all(s.type_id != BP_HULL for s in r.shopping_list)  # BPCs sell on contracts


def test_bought_bpcs_without_a_price_warn():
    r = plan(
        make_input(
            [(HULL, 10)],
            blueprints=(bpo(BP_HULL),),
            choices={BP_HULL: BlueprintChoice(buy_bpcs=1)},
            rules=NO_COMP,
        )
    )
    assert r.costs.blueprints == 0
    assert any("no price set for the 1 bought BPC(s)" in w.text for w in r.warnings)
    # Runs default to the blueprint's max production limit (10 for the hull).
    assert [j.runs for j in jobs_for(r, BP_HULL)] == [10]


def test_extra_bpo_shares_runs_and_goes_on_the_shopping_list():
    prices = {BP_HULL: Price(5_000_000.0, None)}
    r = plan(
        make_input(
            [(HULL, 11)],
            blueprints=(bpo(BP_HULL, me=10),),
            choices={BP_HULL: BlueprintChoice(extra_bpos=1)},
            rules=NO_COMP,
            prices=prices,
        )
    )
    assert sorted((str(j.source), j.runs, j.me) for j in jobs_for(r, BP_HULL)) == [
        ("bought", 5, 0),
        ("bpo", 6, 10),  # the owned, researched BPO takes the larger share
    ]
    [bpo_buy] = [s for s in r.shopping_list if s.type_id == BP_HULL]
    assert (bpo_buy.quantity, bpo_buy.total_price) == (1, 5_000_000)
    assert bpo_buy.reason.code == ReasonCode.BUY_BLUEPRINT
    assert r.costs.blueprints == 5_000_000


def test_extra_bpo_replaces_a_missing_blueprint():
    r = plan(
        make_input([(HULL, 3)], choices={BP_HULL: BlueprintChoice(extra_bpos=1)}, rules=NO_COMP)
    )
    assert [str(j.source) for j in jobs_for(r, BP_HULL)] == ["bought"]
    assert not any(w.code == ReasonCode.SOURCE_MISSING for w in r.warnings)


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


# --- progress (started jobs) ---------------------------------------------------------------


def test_started_units_cover_a_plan_line():
    r = plan(make_input([(HULL, 3)], blueprints=(bpo(BP_COMP_A), bpo(BP_HULL)), started={HULL: 1}))
    assert bp(r, BP_HULL).runs == 2
    assert bp(r, BP_COMP_A).runs == 14  # components only for the two hulls still to build
    hull = item(r, HULL)
    assert (hull.started, hull.over_plan) == (1, 0)


def test_started_beyond_the_plan_is_over_plan():
    r = plan(make_input([(HULL, 3)], blueprints=(bpo(BP_HULL),), started={HULL: 5}))
    assert all(b.type_id != BP_HULL for b in r.blueprints)
    hull = item(r, HULL)
    assert (hull.started, hull.over_plan, hull.produced) == (3, 2, 0)
    assert buy(r, COMP_A) == 0  # nothing left to build, so no inputs


def test_started_components_come_before_assets():
    r = plan(
        make_input(
            [(HULL, 1)],
            blueprints=(bpo(BP_COMP_A), bpo(BP_HULL)),
            started={COMP_A: 5},
            assets={COMP_A: 1},
        )
    )
    comp = item(r, COMP_A)
    assert (comp.started, comp.on_hand_used) == (5, 1)
    assert bp(r, BP_COMP_A).runs == 1


def test_started_units_reduce_a_bought_item():
    r = plan(
        make_input(
            [(HULL, 1)],
            blueprints=(bpo(BP_HULL),),
            rules=BuildRules(item_blacklist=frozenset({COMP_A})),
            started={COMP_A: 4},
        )
    )
    assert buy(r, COMP_A) == 3


def test_invention_attempts_in_progress_reduce_what_is_left():
    base = bp(plan(t2_input()), BP_T2_MOD).invention
    r = plan(t2_input(started_attempts={BP_T2_MOD: 3}))
    inv = bp(r, BP_T2_MOD).invention
    assert inv.attempts == base.attempts - 3 and inv.attempts_in_progress == 3
    assert buy(r, DATACORE) == 2 * (base.attempts - 3)


def test_all_attempts_running_plans_no_more_invention():
    r = plan(t2_input(started_attempts={BP_T2_MOD: 50}))
    assert bp(r, BP_T2_MOD).invention.attempts == 0
    assert jobs_for(r, BP_T1_MOD, Activity.INVENTION) == []
    assert jobs_for(r, BP_T1_MOD, Activity.COPYING) == []


def test_shopping_list_has_packaged_volume():
    g = game()
    types = {**g.types, TRIT: replace(g.types[TRIT], volume=0.01)}
    r = plan(
        make_input(
            [(HULL, 1)], game=replace(g, types=types), blueprints=(bpo(BP_HULL), bpo(BP_COMP_A))
        )
    )
    [trit] = [s for s in r.shopping_list if s.type_id == TRIT]
    assert trit.volume == pytest.approx(trit.quantity * 0.01)
