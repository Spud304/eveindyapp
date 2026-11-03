import httpx
import pytest
from django.core.cache import cache

from apps.accounts import services, tokens
from apps.accounts.sso import SsoIdentity
from apps.esi.client import EsiClient
from apps.esidata.models import (
    Asset,
    BlueprintItem,
    CharacterRoles,
    CharacterSkill,
    IndustryJob,
    MarketPrice,
)
from apps.planning import inputs, stations
from apps.planning.models import BuildRules, Station
from apps.sde import gamedata
from apps.sde.jsonl import ZipSource
from apps.sde.loader import import_source
from engine.types import Activity, BuildCategory

from ..sde.conftest import BUILD, make_sde_zip, names, tiny_records

pytestmark = pytest.mark.django_db

MAIN, CORP = 90000001, 98000001
JITA, D_SYSTEM = 30000142, 30001761
AZBEL_ID, NO_ACCESS, NPC = 1055981940385, 1048845490998, 60003760
AZBEL_TYPE, RAITARU_TYPE, RIG = 35826, 35825, 37146
OTHER_CHAR = 90000999


def sde_records():
    r = tiny_records()
    r["categories"].update(
        {65: {"name": names("Structure")}, 66: {"name": names("Structure Module")}}
    )
    r["groups"].update(
        {
            1404: {"categoryID": 65, "name": names("Engineering Complex")},
            1826: {"categoryID": 66, "name": names("Rig M - Basic Medium Ship ME")},
        }
    )
    r["types"].update(
        {
            AZBEL_TYPE: {"groupID": 1404, "name": names("Azbel"), "published": True},
            RAITARU_TYPE: {"groupID": 1404, "name": names("Raitaru"), "published": True},
            RIG: {
                "groupID": 1826,
                "name": names("M-Set Basic Medium Ship ME I"),
                "published": True,
            },
        }
    )
    r["mapSolarSystems"][D_SYSTEM] = {"name": names("D-JVGJ"), "securityStatus": -0.22}
    r["typeDogma"] = {AZBEL_TYPE: {"dogmaAttributes": [{"attributeID": 2600, "value": 0.99}]}}
    r["industryModifierSources"] = {
        AZBEL_TYPE: {"manufacturing": {"material": [{"dogmaAttributeID": 2600}]}}
    }
    return r


@pytest.fixture
def sde(tmp_path, sde_dir):
    path = tmp_path / f"eve-online-static-data-{BUILD}-jsonl.zip"
    path.write_bytes(make_sde_zip(sde_records()))
    with ZipSource(path) as source:
        import_source(source, build=BUILD)
    for fn in (gamedata._game_data, gamedata._structure, gamedata._rig, gamedata._filter):
        fn.cache_clear()


@pytest.fixture
def user(monkeypatch):
    cache.clear()
    monkeypatch.setattr(tokens, "access_token", lambda ch, *s: f"tok-{getattr(ch, 'pk', ch)}")
    ch = services.upsert_character(SsoIdentity(MAIN, "Main", "o", ()), {"corporation_id": CORP})
    u = services.ensure_user(ch)
    services.store_tokens(ch, {"access_token": "a", "refresh_token": "r"}, ("publicData",))
    CharacterRoles.objects.create(character_id=MAIN, corporation_id=CORP, roles=["Director"])
    return u


def esi(routes):
    def handler(request):
        value = routes.get(request.url.path)
        if value is None:
            return httpx.Response(404, json={})
        if isinstance(value, tuple):
            return httpx.Response(value[0], json=value[1])
        return httpx.Response(200, json=value)

    return EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(handler))


def asset(
    item_id, type_id, qty, root, flag="Hangar", kind="character", owner=MAIN, singleton=False
):
    return Asset.objects.create(
        owner_kind=kind,
        owner_id=owner,
        item_id=item_id,
        type_id=type_id,
        quantity=qty,
        location_id=root,
        location_type="station",
        location_flag=flag,
        is_singleton=singleton,
        root_location_id=root,
        hangar_flag=flag,
    )


def job(job_id, facility, activity=1, owner_kind="corporation", owner=CORP):
    return IndustryJob.objects.create(
        job_id=job_id,
        owner_kind=owner_kind,
        owner_id=owner,
        installer_id=MAIN,
        facility_id=facility,
        location_id=facility,
        activity_id=activity,
        blueprint_id=1,
        blueprint_type_id=691,
        blueprint_location_id=facility,
        output_location_id=facility,
        runs=1,
        status="active",
        duration=1,
        start_date="2026-11-03T00:00:00Z",
        end_date="2026-11-03T01:00:00Z",
        last_seen_at="2026-11-03T00:00:00Z",
    )


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


def test_available_assets_filters_location_flag_and_singletons(sde, user):
    asset(1, 34, 100, AZBEL_ID)
    asset(2, 34, 50, AZBEL_ID, flag="CorpSAG3", kind="corporation", owner=CORP)
    asset(3, 34, 7, AZBEL_ID, flag="CorpDeliveries", kind="corporation", owner=CORP)
    asset(4, 34, 1000, NPC)  # not a station of this plan
    asset(5, 34, 9, AZBEL_ID, flag="Cargo")  # inside a ship
    asset(6, 587, 1, AZBEL_ID, singleton=True)  # an assembled Rifter
    asset(7, 34, 11, AZBEL_ID, kind="corporation", owner=555, flag="CorpSAG1")  # another corp
    assert inputs.available_assets(user, [AZBEL_ID]) == {34: 157}


def test_corp_assets_need_director(sde, user):
    asset(2, 34, 50, AZBEL_ID, flag="CorpSAG3", kind="corporation", owner=CORP)
    CharacterRoles.objects.filter(character_id=MAIN).update(roles=["Factory_Manager"])
    assert inputs.available_assets(user, [AZBEL_ID]) == {}


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


def test_plan_preview_runs_the_engine_on_account_data(sde, logged_in, user):
    Station.objects.create(
        user=user,
        name="Azbel",
        location_id=AZBEL_ID,
        system_id=D_SYSTEM,
        structure_type_id=AZBEL_TYPE,
        activities=["manufacturing"],
        source="manual",
    )
    asset(1, 34, 2000, AZBEL_ID)
    resp = logged_in.post(
        "/api/plan/preview",
        {"lines": [{"type_id": 587, "quantity": 1}]},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    (buy,) = [s for s in body["shopping_list"] if s["type_id"] == 34]
    # 32000 x Azbel 0.99 = 31680, minus 2000 on hand
    assert buy["quantity"] == 31680 - 2000
    assert body["blueprints"][0]["station"]["station_id"] is not None


def test_plan_preview_requires_login(client, sde):
    assert (
        client.post(
            "/api/plan/preview",
            {"lines": [{"type_id": 587, "quantity": 1}]},
            content_type="application/json",
        ).status_code
        == 401
    )
