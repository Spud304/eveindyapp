import pytest

from apps.accounts import services
from apps.accounts.sso import SsoIdentity
from apps.esidata.models import BlueprintItem, CharacterRoles, CharacterSkill, MarketPrice
from apps.planning import inputs, stations
from apps.planning.models import BuildRules, Station
from engine.types import Activity, BuildCategory

from .conftest import (
    AZBEL_ID,
    AZBEL_TYPE,
    CORP,
    D_SYSTEM,
    JITA,
    MAIN,
    NO_ACCESS,
    NPC,
    OTHER_CHAR,
    RAITARU_TYPE,
    RIG,
    asset,
    esi,
    job,
)

pytestmark = pytest.mark.django_db

# --- discovery -------------------------------------------------------------------------------


def test_discover_structures_from_jobs_and_assets(sde, user):
    job(1, AZBEL_ID, activity=5)
    asset(1, 34, 100, NO_ACCESS, kind="corporation", owner=CORP, flag="CorpSAG1")
    asset(2, 34, 5, NPC)  # NPC station with assets only: reported, not added
    client = esi(
        {
            f"/universe/structures/{AZBEL_ID}/": {
                "name": "D-JVGJ - Azbel",
                "solar_system_id": D_SYSTEM,
                "type_id": AZBEL_TYPE,
                "owner_id": 1,
            },
            f"/universe/structures/{NO_ACCESS}/": (403, {"error": "Forbidden"}),
        }
    )
    r = stations.discover(user, client)
    (azbel,) = r.added
    assert (azbel.name, azbel.system_id, azbel.structure_type_id) == (
        "D-JVGJ - Azbel",
        D_SYSTEM,
        AZBEL_TYPE,
    )
    # hull default plus the copying seen in jobs there
    assert azbel.activities == ["copying", "invention", "manufacturing"]
    assert not azbel.tax_confirmed
    assert "docking access" in r.unresolved[NO_ACCESS]
    assert r.asset_only_npc == {NPC: 1}
    assert stations.discover(user, client).already_known == [AZBEL_ID]


def test_discover_npc_station_with_jobs_uses_services(sde, user):
    job(1, NPC, owner_kind="character", owner=MAIN)
    client = esi(
        {
            f"/universe/stations/{NPC}/": {
                "name": "Jita IV - Moon 4",
                "system_id": JITA,
                "services": ["factory", "market"],
            }
        }
    )
    (s,) = stations.discover(user, client).added
    assert s.structure_type_id is None and s.activities == ["manufacturing"]


def test_engine_station_uses_sde_hull_and_rigs(sde, user):
    s = Station.objects.create(
        user=user,
        name="A",
        location_id=AZBEL_ID,
        system_id=D_SYSTEM,
        structure_type_id=AZBEL_TYPE,
        rig_type_ids=[RIG],
        activities=["manufacturing"],
        facility_tax=1.5,
        source="manual",
    )
    e = stations.engine_station(s)
    assert e.structure.name == "Azbel" and e.structure.modifiers[0].multiplier == 0.99
    assert e.rigs[0].type_id == RIG
    assert e.activities == frozenset({Activity.MANUFACTURING}) and e.facility_tax == 1.5


# --- plan input ------------------------------------------------------------------------------


def available(user, location):
    totals = {}
    for (type_id, _, _), qty in inputs.asset_buckets(user, [location]).items():
        totals[type_id] = totals.get(type_id, 0) + qty
    return totals


def test_available_assets_filters_location_flag_and_singletons(sde, user):
    asset(1, 34, 100, AZBEL_ID)
    asset(2, 34, 50, AZBEL_ID, flag="CorpSAG3", kind="corporation", owner=CORP)
    asset(3, 34, 7, AZBEL_ID, flag="CorpDeliveries", kind="corporation", owner=CORP)
    asset(4, 34, 1000, NPC)  # not a station of this plan
    asset(5, 34, 9, AZBEL_ID, flag="Cargo")  # inside a ship
    asset(6, 587, 1, AZBEL_ID, singleton=True)  # an assembled Rifter
    asset(7, 34, 11, AZBEL_ID, kind="corporation", owner=555, flag="CorpSAG1")  # another corp
    assert available(user, AZBEL_ID) == {34: 157}


def test_corp_assets_need_director(sde, user):
    asset(2, 34, 50, AZBEL_ID, flag="CorpSAG3", kind="corporation", owner=CORP)
    CharacterRoles.objects.filter(character_id=MAIN).update(roles=["Factory_Manager"])
    assert available(user, AZBEL_ID) == {}


def test_blueprints_characters_rules_and_prices(sde, user):
    BlueprintItem.objects.create(
        owner_kind="corporation",
        owner_id=CORP,
        item_id=1,
        type_id=691,
        location_id=AZBEL_ID,
        location_flag="CorpSAG2",
        quantity=-2,
        runs=5,
        material_efficiency=10,
        time_efficiency=20,
        root_location_id=AZBEL_ID,
        hangar_flag="CorpSAG2",
    )
    CharacterSkill.objects.create(
        character_id=MAIN, skill_id=3380, active_level=5, trained_level=5, skillpoints=1
    )
    BuildRules.objects.create(user=user, item_blacklist=[34], buy_categories=["fuel_blocks"])
    MarketPrice.objects.create(
        type_id=34, adjusted_price=3.0, average_price=3.7, updated_at="2026-11-03T00:00:00Z"
    )
    (bp,) = inputs.owned_blueprints(user)
    assert bp.is_copy and bp.runs == 5 and bp.me == 10
    (ch,) = inputs.characters(user)
    assert ch.skills == {3380: 5}
    rules = inputs.build_rules(user)
    assert rules.item_blacklist == {34} and rules.buy_categories == {BuildCategory.FUEL_BLOCKS}
    p = inputs.prices()[34]
    assert (p.unit_price, p.adjusted_price) == (3.7, 3.0)


# --- API -------------------------------------------------------------------------------------


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def test_station_crud(sde, logged_in):
    resp = logged_in.post(
        "/api/stations",
        {
            "name": "Raitaru",
            "system_id": D_SYSTEM,
            "structure_type_id": RAITARU_TYPE,
            "rig_type_ids": [RIG],
            "activities": ["manufacturing"],
            "facility_tax": 1.0,
        },
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    sid = resp.json()["id"]
    assert resp.json()["rig_names"] == ["M-Set Basic Medium Ship ME I"]
    resp = logged_in.patch(
        f"/api/stations/{sid}",
        {"facility_tax": 2.5, "activities": ["copying"]},
        content_type="application/json",
    )
    assert resp.json()["facility_tax"] == 2.5 and resp.json()["activities"] == ["copying"]
    assert logged_in.delete(f"/api/stations/{sid}").status_code == 204


def test_station_rejects_non_rig_and_non_structure_types(sde, logged_in):
    bad = logged_in.post(
        "/api/stations",
        {"name": "x", "system_id": D_SYSTEM, "rig_type_ids": [34]},
        content_type="application/json",
    )
    assert bad.status_code == 422
    bad = logged_in.post(
        "/api/stations",
        {"name": "x", "system_id": D_SYSTEM, "structure_type_id": 587},
        content_type="application/json",
    )
    assert bad.status_code == 422


def test_stations_are_per_account(sde, logged_in, user):
    other = services.ensure_user(
        services.upsert_character(SsoIdentity(OTHER_CHAR, "Other", "x", ()), {})
    )
    s = Station.objects.create(user=other, name="theirs", system_id=D_SYSTEM, source="manual")
    assert (
        logged_in.patch(
            f"/api/stations/{s.pk}", {"name": "mine"}, content_type="application/json"
        ).status_code
        == 404
    )
    assert logged_in.get("/api/stations").json() == []


def test_build_rules_roundtrip(sde, logged_in):
    put = logged_in.put(
        "/api/build-rules",
        {"item_blacklist": [34, 34], "buy_categories": ["t2_items"]},
        content_type="application/json",
    )
    assert put.json() == {"item_blacklist": [34], "buy_categories": ["t2_items"]}
    assert logged_in.get("/api/build-rules").json()["buy_categories"] == ["t2_items"]
