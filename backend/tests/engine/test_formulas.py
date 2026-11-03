import pytest

from engine import formulas as f
from engine.types import Activity, Material, SecurityClass, SkillRequirement

from .data import (
    ADV_COMPONENT_TE_RIG,
    COMP_A,
    COMPOSITE,
    COMPOSITE_ME_RIG,
    COPY_TIME_RIG,
    HULL,
    MEDIUM_SHIP_ME_RIG,
    T2_MOD,
    TYPES,
    athanor,
    azbel,
    character,
    raitaru,
    tatara,
)


@pytest.mark.parametrize(
    ("sec", "expected"),
    [
        (1.0, SecurityClass.HIGH),
        (0.45, SecurityClass.HIGH),
        (0.449, SecurityClass.LOW),
        (0.04, SecurityClass.LOW),  # displays as 0.1 in game
        (0.0, SecurityClass.NULL),
        (-0.5, SecurityClass.NULL),
    ],
)
def test_security_class(sec, expected):
    assert f.security_class(sec) == expected


def test_job_materials_rounds_whole_job_not_per_run():
    # 3 x 10 runs x 0.9 = 27; per-run rounding would give ceil(2.7) x 10 = 30.
    assert f.job_materials((Material(34, 3),), 10, 10, 1.0) == (Material(34, 27),)


def test_job_materials_never_below_one_per_run():
    assert f.job_materials((Material(34, 1),), 10, 10, 0.9) == (Material(34, 10),)


def test_job_materials_ignores_float_noise():
    # 100 x 0.99 x 0.962 = 95.238 -> 96 regardless of float error in the product
    assert f.job_materials((Material(34, 100),), 1, 0, 0.99 * 0.962) == (Material(34, 96),)


def test_station_me_rig_applies_security_multiplier():
    b = f.station_bonuses(
        azbel((MEDIUM_SHIP_ME_RIG,)), Activity.MANUFACTURING, TYPES[HULL], SecurityClass.LOW
    )
    assert b.material == pytest.approx(0.99 * (1 - 0.038))
    assert b.time == pytest.approx(0.80)
    assert b.cost == pytest.approx(0.96)


def test_station_m_set_te_rig_is_counted():
    b = f.station_bonuses(
        raitaru((ADV_COMPONENT_TE_RIG,)), Activity.MANUFACTURING, TYPES[COMP_A], SecurityClass.HIGH
    )
    assert b.material == pytest.approx(0.99)
    assert b.time == pytest.approx(0.85 * 0.8)
    assert "time -20.00% (Components)" in b.description


def test_rig_outside_its_target_filter_is_ignored():
    b = f.station_bonuses(
        azbel((MEDIUM_SHIP_ME_RIG,)), Activity.MANUFACTURING, TYPES[T2_MOD], SecurityClass.LOW
    )
    assert b.material == pytest.approx(0.99)


def test_structure_modifiers_only_for_their_activity():
    b = f.station_bonuses(raitaru(), Activity.REACTION, TYPES[COMPOSITE], SecurityClass.LOW)
    assert (b.material, b.time, b.cost) == (1.0, 1.0, 1.0)


def test_engineering_complex_time_and_copy_rig_apply_to_copying():
    b = f.station_bonuses(raitaru((COPY_TIME_RIG,)), Activity.COPYING, None, SecurityClass.HIGH)
    assert b.time == pytest.approx(0.85 * 0.8)
    assert b.cost == pytest.approx(0.97)


def test_tatara_reaction_time():
    b = f.station_bonuses(tatara(), Activity.REACTION, TYPES[COMPOSITE], SecurityClass.NULL)
    assert b.time == pytest.approx(0.75)


def test_reactor_rig_has_no_highsec_multiplier_entry_defaults_to_one():
    b = f.station_bonuses(
        athanor((COMPOSITE_ME_RIG,)), Activity.REACTION, TYPES[COMPOSITE], SecurityClass.HIGH
    )
    assert b.material == pytest.approx(0.98)


def test_job_fee_parts_as_in_the_client():
    fee = f.job_fee(1000.0, 0.05, 0.96, 1.0, is_alpha=False, safe_sec=False)
    assert (fee.base, fee.job_cost, fee.facility_tax, fee.scc_surcharge, fee.security_tax) == (
        1000,
        48,
        10,
        40,
        0,
    )
    assert fee.total == 98


def test_job_fee_alpha_tax_is_additive_on_base():
    # alpha adds base x 0.25% to the job cost even with no cost index
    fee = f.job_fee(10_000.0, 0.0, 1.0, 0.0, is_alpha=True, safe_sec=False)
    assert fee.job_cost == 25 and fee.total == 25 + 400


def test_job_fee_safe_sec_tax():
    fee = f.job_fee(10_000.0, 0.01, 1.0, 0.0, is_alpha=False, safe_sec=True)
    assert fee.security_tax == 500


def test_each_fee_part_rounds_half_up():
    # base 12.5 -> 13; tax 13 x 10% = 1.3 -> 1; SCC 13 x 4% = 0.52 -> 1
    fee = f.job_fee(12.5, 0.0, 1.0, 10.0, is_alpha=False, safe_sec=False)
    assert (fee.base, fee.facility_tax, fee.scc_surcharge) == (13, 1, 1)
    assert f.round_half_up(2.5) == 3 and f.round_half_up(3.5) == 4


@pytest.mark.parametrize(("sec", "safe"), [(1.0, True), (0.95, True), (0.946, False), (0.5, False)])
def test_safe_sec_threshold(sec, safe):
    assert f.is_safe_sec(sec) is safe


def test_max_runs_thirty_days_before_skills():
    # 6000 s per run x TE 20% x Raitaru 0.85 = 4080 s -> ceil(2,592,000 / 4080) = 636
    assert f.max_runs(Activity.MANUFACTURING, 6000, 0.8 * 0.85) == 636
    assert f.max_runs(Activity.INVENTION, 60, 1.0) == 500  # science cap
    assert f.max_runs(Activity.MANUFACTURING, 1, 1.0) == 1_000_000


def test_required_skill_time_multiplier():
    ch = character(skills={3397: 5, 11433: 4})
    reqs = (SkillRequirement(3397, 1), SkillRequirement(11433, 1), SkillRequirement(3380, 1))
    bonuses = {3397: -1.0, 11433: -1.0}  # Industry (3380) has no attr 1982
    assert f.required_skill_time_multiplier(reqs, bonuses, ch) == pytest.approx(0.95 * 0.96)


def test_skill_time_multiplier_manufacturing():
    ch = character(skills={3380: 5, 3388: 5})
    assert f.skill_time_multiplier(Activity.MANUFACTURING, ch) == pytest.approx(0.8 * 0.85)


def test_skill_time_multiplier_copying_uses_science():
    ch = character(skills={3402: 5, 3388: 5})
    assert f.skill_time_multiplier(Activity.COPYING, ch) == pytest.approx(0.75 * 0.85)


def test_slots_from_skills():
    ch = character(skills={3387: 5, 24625: 4, 3406: 3, 45748: 2})
    assert f.slots(ch, Activity.MANUFACTURING) == 10
    assert f.slots(ch, Activity.INVENTION) == 4
    assert f.slots(ch, Activity.REACTION) == 3


def test_invention_probability_additive_skill_bonus():
    ch = character(skills={21790: 4, 11433: 4, 11442: 4})
    p = f.invention_probability(0.34, ch, 21790, (11433, 11442), 1.2)
    assert p == pytest.approx(0.34 * (1 + 8 / 30 + 4 / 40) * 1.2)
