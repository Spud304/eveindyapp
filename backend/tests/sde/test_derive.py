import pytest

from apps.sde.jsonl import ZipSource
from apps.sde.loader import import_source
from apps.sde.models import (
    Blueprint,
    BlueprintActivity,
    BlueprintProduct,
    EveCategory,
    EveGroup,
    EveType,
    SdeRawRecord,
    SolarSystem,
)

from .conftest import BUILD

pytestmark = pytest.mark.django_db


@pytest.fixture
def imported(tiny_zip):
    with ZipSource(tiny_zip) as source:
        return import_source(source, build=BUILD)


def test_type_fields_map_from_sde_names(imported):
    rifter = EveType.objects.select_related("group__category", "meta_group").get(pk=587)
    assert rifter.name == "Rifter"
    assert rifter.group.name == "Frigate" and rifter.group.category.name == "Ship"
    assert rifter.meta_group.name == "Tech I"
    assert rifter.tech_level == 1 and rifter.meta_level == 0
    assert rifter.packaged_volume == 2500.0 and rifter.market_group_id == 64
    assert rifter.published and not rifter.removed


def test_every_category_is_derived(imported):
    assert EveType.objects.filter(pk__in=[34, 691, 587]).count() == 3
    assert EveCategory.objects.get(pk=9).name == "Blueprint"
    assert EveGroup.objects.get(pk=105).category_id == 9


def test_absent_fields_are_null(imported):
    badger = EveType.objects.get(pk=648)
    assert badger.tech_level is None and badger.volume is None
    assert badger.group.name == "Hauler"


def test_published_mirrors_ccp_separately_from_removed(imported):
    thing = EveType.objects.get(pk=999999)
    assert thing.published is False and thing.removed is False


def test_unknown_meta_group_is_nulled_with_warning(imported):
    assert EveType.objects.get(pk=600).meta_group is None
    assert any("unknown metaGroupID" in w for w in imported.warnings)


def test_type_with_unknown_group_is_skipped(imported):
    assert not EveType.objects.filter(pk=5000).exists()
    assert any("groupID not in groups" in w for w in imported.warnings)


def test_blueprint_activities_materials_products_skills(imported):
    bp = Blueprint.objects.get(pk=691)
    assert bp.max_production_limit == 30
    acts = {a.activity: a for a in BlueprintActivity.objects.filter(blueprint=bp)}
    assert set(acts) == {"copying", "manufacturing", "invention", "research_material"}
    mfg = acts["manufacturing"]
    assert mfg.time == 6000
    assert [(m.type_id, m.quantity) for m in mfg.materials.all()] == [(34, 32000)]
    assert [(p.type_id, p.quantity) for p in mfg.products.all()] == [(587, 1)]
    assert [(s.skill_id, s.level) for s in mfg.skills.all()] == [(3380, 1)]
    inv = BlueprintProduct.objects.get(activity=acts["invention"])
    assert inv.type_id == 11371 and inv.probability == 0.3


def test_reimport_rebuilds_activities_without_duplicates(tiny_zip):
    for _ in range(2):
        with ZipSource(tiny_zip) as source:
            import_source(source, build=BUILD, force=True)
    assert BlueprintActivity.objects.filter(blueprint_id=691).count() == 4


def test_solar_system(imported):
    jita = SolarSystem.objects.get(pk=30000142)
    assert jita.name == "Jita" and jita.security == pytest.approx(0.945913)
    assert jita.region_id == 10000002


def test_raw_only_files_are_kept_decoded(imported):
    dogma = SdeRawRecord.objects.get(file="typeDogma", key="35825").data
    assert dogma["dogmaAttributes"] == [{"attributeID": 2600, "value": 0.99}]
