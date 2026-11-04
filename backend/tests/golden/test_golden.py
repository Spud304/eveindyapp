"""Plans computed from real SDE records, imported through the real importer.

`tests/golden/sde/` holds CCP's own JSONL lines for a few blueprints, structures, rigs and
skills (build in `_sde.jsonl`; `extract.py` makes it). Each expected value below is written out
from those raw numbers with the client's formulas (docs/redesign.md, "Client code"), not from
engine code, so a wrong mapping in `apps/sde/gamedata.py` or a changed SDE shape fails here.

Not yet compared with in-game job windows; when that is done, the numbers go in as such."""

import json
import math
from pathlib import Path

import pytest

from apps.sde import gamedata
from apps.sde.jsonl import DirSource
from apps.sde.loader import import_source
from apps.sde.models import SolarSystem as SdeSystem
from engine import plan
from engine.types import (
    Activity,
    BlueprintChoice,
    BuildCategory,
    BuildRules,
    Character,
    Material,
    ModifierKind,
    OwnedBlueprint,
    PlanInput,
    PlanLine,
    Price,
    SecurityClass,
    SolarSystem,
    Station,
)

pytestmark = pytest.mark.django_db

FIXTURE = Path(__file__).parent / "sde"
D_JVGJ = 30001761  # nullsec: rig security multiplier attr 2357
TRIT, PYE, MEX, ISO = 34, 35, 36, 37
RIFTER, RIFTER_BP = 587, 691
WC, WC_FORMULA, TEST_FORMULA = 16672, 46207, 45732
FUEL, MOON_A, MOON_B = 4051, 16657, 16661
DLA_I, DLA_I_BP, DLA_II, DLA_II_BP = 23527, 23528, 24427, 24428
AZBEL, TATARA = 35826, 35836
SMALL_SHIP_ME, MEDIUM_SHIP_ME, COMPOSITE_ME, INVENTION_TE = 37154, 37146, 46486, 43880
ALL = frozenset(Activity)


@pytest.fixture
def game(sde_dir):
    build = json.loads((FIXTURE / "_sde.jsonl").read_text().splitlines()[0])["buildNumber"]
    import_source(DirSource(FIXTURE), build=build)
    for fn in (gamedata._game_data, gamedata._structure, gamedata._rig, gamedata._filter):
        fn.cache_clear()
    return gamedata.game_data()


def system(cost_index=0.05) -> dict[int, SolarSystem]:
    row = SdeSystem.objects.get(pk=D_JVGJ)
    return {
        D_JVGJ: SolarSystem(D_JVGJ, row.name, row.security, dict.fromkeys(Activity, cost_index))
    }


def station(hull, *rigs, tax=1.0) -> Station:
    return Station(
        1,
        "Golden",
        D_JVGJ,
        gamedata.structure(hull),
        tax,
        ALL,
        tuple(gamedata.rig(r) for r in rigs),
    )


def builder(skills: dict[int, int]) -> Character:
    return Character(1, "Builder", skills, ALL, False)


def materials(job) -> dict[int, int]:
    return {m.type_id: m.quantity for m in job.materials}


def client_quantity(base: int, runs: int, *multipliers: float) -> int:
    """industry/job.py: max(runs, ceil(round(base x modifiers x runs, 2)))."""
    return max(runs, math.ceil(round(base * math.prod(multipliers) * runs, 2)))


# --- manufacturing ---------------------------------------------------------------------------


def rifter_input(game, *rigs):
    return PlanInput(
        lines=(PlanLine("l", RIFTER, 10),),
        game=game,
        stations=(station(AZBEL, *rigs),),
        systems=system(),
        characters=(builder({3380: 5, 3388: 5}),),
        blueprints=(OwnedBlueprint(1, RIFTER_BP, False, -1, 10, 20, 1),),
        prices={
            TRIT: Price(5.0, 4.0),
            PYE: Price(12.0, 10.0),
            MEX: Price(60.0, 50.0),
            ISO: Price(120.0, 100.0),
        },
    )


def test_rifter_at_a_rigged_azbel_in_nullsec(game):
    r = plan(rifter_input(game, SMALL_SHIP_ME))
    [job] = [j for j in r.jobs if j.blueprint_type_id == RIFTER_BP]
    assert job.runs == 10
    # Blueprint ME 10, Azbel attr 2600 0.99, small ship rig attr 2594 -2.0 x nullsec 2.1.
    me = (0.90, 0.99, 1 - 2.0 * 2.1 / 100)
    assert materials(job) == {
        TRIT: client_quantity(32000, 10, *me),
        PYE: client_quantity(6000, 10, *me),
        MEX: client_quantity(2500, 10, *me),
        ISO: client_quantity(500, 10, *me),
    }
    # 6000 s x 10 runs x TE 20 x Azbel attr 2602 0.8 x Industry 5 (attr 440 -4) x
    # Advanced Industry 5 (attr 1961 -3); whole seconds.
    seconds = 6000 * 10 * 0.80 * 0.8 * (1 - 0.04 * 5) * (1 - 0.03 * 5)
    assert job.schedule.end_seconds - job.schedule.start_seconds == round(seconds)
    # Fee: EIV = ME 0 materials x adjusted price; job cost x Azbel attr 2601 0.96; tax 1 %;
    # SCC 4 %. Nullsec: no safe-sec tax.
    base = (32000 * 4 + 6000 * 10 + 2500 * 50 + 500 * 100) * 10
    assert (job.cost.base, job.cost.job_cost) == (base, round(base * 0.05 * 0.96))
    assert (job.cost.facility_tax, job.cost.scc_surcharge) == (base * 0.01, base * 0.04)
    assert job.cost.security_tax == 0


def test_a_medium_ship_rig_does_not_apply_to_a_frigate(game):
    r = plan(rifter_input(game, MEDIUM_SHIP_ME))
    [job] = [j for j in r.jobs if j.blueprint_type_id == RIFTER_BP]
    assert materials(job)[TRIT] == client_quantity(32000, 10, 0.90, 0.99)


# --- reactions -------------------------------------------------------------------------------


def test_tungsten_carbide_uses_the_published_formula_at_a_rigged_tatara(game):
    assert not game.blueprints[TEST_FORMULA].published
    r = plan(
        PlanInput(
            lines=(PlanLine("l", WC, 20_000),),
            game=game,
            stations=(station(TATARA, COMPOSITE_ME),),
            systems=system(),
            characters=(builder({45746: 5}),),
            blueprints=(OwnedBlueprint(1, WC_FORMULA, False, -1, 0, 0, 1),),
            rules=BuildRules(buy_categories=frozenset({BuildCategory.FUEL_BLOCKS})),
        )
    )
    assert not [j for j in r.jobs if j.blueprint_type_id == TEST_FORMULA]
    [job] = [j for j in r.jobs if j.blueprint_type_id == WC_FORMULA]
    assert job.activity == Activity.REACTION and job.runs == 2  # 10,000 units a run
    # No blueprint ME for reactions; composite rig attr 2714 -2.0 x nullsec 1.1 (its own 2357).
    me = 1 - 2.0 * 1.1 / 100
    assert materials(job) == {
        FUEL: client_quantity(5, 2, me),
        MOON_A: client_quantity(100, 2, me),
        MOON_B: client_quantity(100, 2, me),
    }
    # 10800 s x 2 runs x Tatara attr 2721 0.75 x Reactions 5 (-4 %/level).
    seconds = 10800 * 2 * 0.75 * (1 - 0.04 * 5)
    assert job.schedule.end_seconds - job.schedule.start_seconds == round(seconds)


# --- invention and T2 manufacturing ----------------------------------------------------------


def test_drone_link_augmentor_ii_invention_and_t2_job(game):
    sci_1, sci_2, encryption = 11453, 11446, 23121
    skills = {3380: 5, 3388: 5, 3402: 5, sci_1: 4, sci_2: 4, encryption: 4}
    r = plan(
        PlanInput(
            lines=(PlanLine("l", DLA_II, 10),),
            game=game,
            stations=(station(AZBEL, INVENTION_TE),),
            systems=system(),
            characters=(builder(skills),),
            blueprints=(OwnedBlueprint(1, DLA_I_BP, False, -1, 0, 0, 1),),
            rules=BuildRules(item_blacklist=frozenset({DLA_I})),
            choices={DLA_II_BP: BlueprintChoice(decryptor="none")},
        )
    )
    inv = next(b for b in r.blueprints if b.type_id == DLA_II_BP).invention
    # Base 0.34 x (1 + (4 + 4) / 30 + 4 / 40); one 10-run T2 copy is needed.
    chance = 0.34 * (1 + 8 / 30 + 4 / 40)
    assert inv.probability == pytest.approx(chance)
    assert inv.attempts == math.ceil(1 / chance)
    [inv_job] = [j for j in r.jobs if j.activity == Activity.INVENTION]
    assert materials(inv_job) == {20419: 2 * inv.attempts, 20418: 2 * inv.attempts}
    # 51000 s x attempts x Azbel 0.8 x invention rig attr 2593 -20 x nullsec 2.1 x
    # Advanced Industry 5.
    seconds = 51000 * inv.attempts * 0.8 * (1 - 20 * 2.1 / 100) * (1 - 0.03 * 5)
    assert inv_job.schedule.end_seconds - inv_job.schedule.start_seconds == round(seconds)

    [t2] = [j for j in r.jobs if j.blueprint_type_id == DLA_II_BP]
    assert (t2.me, t2.te, t2.runs) == (2, 4, 10)  # invented copy: ME 2 / TE 4
    me = (0.98, 0.99)
    assert materials(t2) == {
        DLA_I: client_quantity(1, 10, *me),
        9840: client_quantity(12, 10, *me),
        11688: client_quantity(12, 10, *me),
        11483: client_quantity(1, 10, *me),
        11399: client_quantity(5, 10, *me),
    }
    # 7020 s x 10 x TE 4 x Azbel 0.8 x Industry 5 x Advanced Industry 5 x the two required
    # science skills (attr 1982 -1 %/level, level 4 each).
    seconds = 7020 * 10 * 0.96 * 0.8 * 0.8 * 0.85 * (1 - 0.04) * (1 - 0.04)
    assert t2.schedule.end_seconds - t2.schedule.start_seconds == round(seconds)
    assert Material(DLA_I, client_quantity(1, 10, *me)) in t2.materials


# --- rigs whose bonus is not in the usual attributes -------------------------------------------


def bonuses(rig):
    return {
        (b.activity, b.kind, b.target.name if b.target else None): (b.percent, b.security_scaled)
        for b in rig.bonuses
    }


def test_thukker_rigs_read_their_own_bonus_attribute(game):
    # Effect 6887 feeds structure attr 2559 (capital components) from rig attr 2653 (-3.7);
    # effect 6842 scales 2653 by security: 0.1 in high and null, 1.9 in low.
    basic = gamedata.rig(45544)
    assert bonuses(basic) == {
        (Activity.MANUFACTURING, ModifierKind.MATERIAL, "Capital Components"): (3.7, True)
    }
    assert basic.security_multipliers == {
        SecurityClass.HIGH: 0.1,
        SecurityClass.LOW: 1.9,
        SecurityClass.NULL: 0.1,
    }
    # The advanced one: components through 2594 (-2.0), advanced capital ones through 2653.
    assert bonuses(gamedata.rig(45640)) == {
        (Activity.MANUFACTURING, ModifierKind.MATERIAL, "Components"): (2.0, True),
        (Activity.MANUFACTURING, ModifierKind.MATERIAL, "Advanced Capital Components"): (3.7, True),
    }


def test_upwell_outpost_rig_bonuses_do_not_scale_with_security(game):
    # Effects 7099 / 7100: 2600 from 2594 (-1.0), T1 ship time from 2773 (-40); no effect
    # multiplies them by securityModifier.
    assert bonuses(gamedata.rig(47883)) == {
        (Activity.MANUFACTURING, ModifierKind.MATERIAL, None): (1.0, False),
        (Activity.MANUFACTURING, ModifierKind.TIME, "Small T1 Ships"): (40.0, False),
        (Activity.MANUFACTURING, ModifierKind.TIME, "Medium T1 Ships"): (40.0, False),
        (Activity.MANUFACTURING, ModifierKind.TIME, "Large T1 Ships"): (40.0, False),
        (Activity.MANUFACTURING, ModifierKind.TIME, "Capital Ships"): (40.0, False),
    }
