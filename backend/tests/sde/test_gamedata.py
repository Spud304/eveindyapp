import pytest

from apps.sde import gamedata
from apps.sde.jsonl import ZipSource
from apps.sde.loader import import_source
from engine.types import Activity, ModifierKind, SecurityClass

from .conftest import BUILD, make_sde_zip, names, tiny_records

pytestmark = pytest.mark.django_db

RAITARU, M_RIG, REACTOR_RIG, ACCELERANT = 35825, 37146, 46496, 34201


def industry_records():
    """tiny_records plus a Raitaru, two rigs and a decryptor, values as in build 3667080."""
    r = tiny_records()
    r["categories"].update(
        {
            35: {"name": names("Decryptors")},
            65: {"name": names("Structure")},
            66: {"name": names("Structure Module")},
        }
    )
    r["groups"].update(
        {
            1304: {"categoryID": 35, "name": names("Generic Decryptor"), "published": True},
            1404: {"categoryID": 65, "name": names("Engineering Complex"), "published": True},
            1826: {
                "categoryID": 66,
                "name": names("Rig M - Basic Medium Ship ME"),
                "published": True,
            },
            1939: {
                "categoryID": 66,
                "name": names("Reactor Rig L - Efficiency"),
                "published": True,
            },
        }
    )
    r["types"].update(
        {
            RAITARU: {"groupID": 1404, "name": names("Raitaru"), "published": True},
            M_RIG: {
                "groupID": 1826,
                "name": names("M-Set Basic Medium Ship ME I"),
                "published": True,
            },
            REACTOR_RIG: {
                "groupID": 1939,
                "name": names("L-Set Reactor Efficiency I"),
                "published": True,
            },
            ACCELERANT: {"groupID": 1304, "name": names("Accelerant Decryptor"), "published": True},
        }
    )

    def dogma(values):
        return {"dogmaAttributes": [{"attributeID": a, "value": v} for a, v in values.items()]}

    r["typeDogma"] = {
        RAITARU: dogma({2600: 0.99, 2601: 0.97, 2602: 0.85}),
        M_RIG: dogma({2355: 1.0, 2356: 1.9, 2357: 2.1, 2593: 0.0, 2594: -2.0, 2595: 0.0}),
        REACTOR_RIG: dogma({2356: 1.0, 2357: 1.1, 2713: -20.0, 2714: -2.0}),
        ACCELERANT: dogma({1112: 1.2, 1113: 2.0, 1114: 10.0, 1124: 1.0}),
        3397: dogma({1982: -1.0}),  # Advanced Medium Ship Construction
        691: dogma({1954: 0.0}),  # a blueprint with a job cost multiplier
    }
    r["industryModifierSources"] = {
        RAITARU: {
            "manufacturing": {
                "cost": [{"dogmaAttributeID": 2601}],
                "material": [{"dogmaAttributeID": 2600}],
                "time": [{"dogmaAttributeID": 2602}],
            },
            "copying": {"time": [{"dogmaAttributeID": 2602}]},
            "researchTime": {"time": [{"dogmaAttributeID": 2602}]},
        },
        M_RIG: {"manufacturing": {"material": [{"dogmaAttributeID": 2546, "filterID": 7}]}},
        REACTOR_RIG: {
            "reaction": {
                "material": [{"dogmaAttributeID": 2718, "filterID": 18}],
                "time": [{"dogmaAttributeID": 2717, "filterID": 18}],
            }
        },
    }
    r["industryTargetFilters"] = {
        7: {"groupIDs": [26, 28, 419, 463, 1201, 4902, 5087], "name": "Medium T1 Ships"},
        18: {"groupIDs": [428, 429, 4932], "name": "Composite Reactions"},
    }
    return r


@pytest.fixture
def imported(tmp_path, sde_dir):
    path = tmp_path / f"eve-online-static-data-{BUILD}-jsonl.zip"
    path.write_bytes(make_sde_zip(industry_records()))
    with ZipSource(path) as source:
        import_source(source, build=BUILD)
    gamedata._game_data.cache_clear()
    gamedata._structure.cache_clear()
    gamedata._rig.cache_clear()
    gamedata._filter.cache_clear()


def test_game_data_types_and_blueprints(imported):
    g = gamedata.game_data()
    rifter = g.types[587]
    assert (rifter.name, rifter.group_id, rifter.category_id) == ("Rifter", 25, 6)
    bp = g.blueprints[691]
    assert bp.max_production_limit == 30
    assert bp.manufacturing.product_type_id == 587 and bp.manufacturing.time_seconds == 6000
    assert [(m.type_id, m.quantity) for m in bp.manufacturing.materials] == [(34, 32000)]
    assert [(s.skill_id, s.level) for s in bp.manufacturing.skills] == [(3380, 1)]
    assert bp.copying.time_seconds == 4800 and bp.copying.product_type_id is None
    (inv,) = bp.invention
    assert inv.product_type_id == 11371 and inv.probability == 0.3


def test_reimporting_the_same_build_refreshes_cached_game_data(imported, tmp_path):
    before = gamedata.game_data()
    assert gamedata.game_data() is before  # cached
    records = industry_records()
    records["typeDogma"][691] = {"dogmaAttributes": [{"attributeID": 1954, "value": 0.5}]}
    path = tmp_path / "again.zip"
    path.write_bytes(make_sde_zip(records))
    with ZipSource(path) as source:
        import_source(source, build=BUILD, files=["typeDogma"], raw_only=True)
    after = gamedata.game_data()
    assert after is not before
    assert after.blueprints[691].job_cost_multiplier == 0.5


def test_skill_time_bonuses_and_blueprint_cost_multiplier(imported):
    g = gamedata.game_data()
    assert g.skill_time_bonuses == {3397: -1.0}
    assert g.blueprints[691].job_cost_multiplier == 0.0


def test_decryptors_from_dogma(imported):
    (d,) = gamedata.game_data().decryptors
    assert (d.name, d.probability_multiplier, d.me_modifier, d.te_modifier, d.run_modifier) == (
        "Accelerant Decryptor",
        1.2,
        2,
        10,
        1,
    )


def test_structure_modifiers_from_sources_and_dogma(imported):
    s = gamedata.structure(RAITARU)
    mods = {(m.activity, m.kind): m.multiplier for m in s.modifiers}
    assert mods == {
        (Activity.MANUFACTURING, ModifierKind.COST): 0.97,
        (Activity.MANUFACTURING, ModifierKind.MATERIAL): 0.99,
        (Activity.MANUFACTURING, ModifierKind.TIME): 0.85,
        (Activity.COPYING, ModifierKind.TIME): 0.85,
    }  # researchTime is not a planned activity


def test_engineering_rig_uses_rig_bonus_attribute_and_filter(imported):
    rig = gamedata.rig(M_RIG)
    (b,) = rig.bonuses
    assert (b.activity, b.kind, b.percent) == (Activity.MANUFACTURING, ModifierKind.MATERIAL, 2.0)
    assert b.target.name == "Medium T1 Ships" and 28 in b.target.group_ids
    assert rig.security_multipliers[SecurityClass.LOW] == 1.9


def test_reactor_rig_uses_reactor_attributes(imported):
    rig = gamedata.rig(REACTOR_RIG)
    got = {(b.kind, b.percent) for b in rig.bonuses}
    assert got == {(ModifierKind.MATERIAL, 2.0), (ModifierKind.TIME, 20.0)}
    assert SecurityClass.HIGH not in rig.security_multipliers


def test_unknown_structure(imported):
    with pytest.raises(gamedata.UnknownStructure):
        gamedata.structure(123456789)
