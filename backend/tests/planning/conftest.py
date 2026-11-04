"""Shared fixtures for planning tests: a tiny SDE with real structure/rig ids, an account
with a Director character, and row builders."""

import httpx
import pytest
from django.core.cache import cache

from apps.accounts import services, tokens
from apps.accounts.sso import SsoIdentity
from apps.esi.client import EsiClient
from apps.esidata.models import (
    Asset,
    CharacterRoles,
    IndustryJob,
)
from apps.sde import gamedata
from apps.sde.jsonl import ZipSource
from apps.sde.loader import import_source

from ..sde.conftest import BUILD, make_sde_zip, names, tiny_records

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


@pytest.fixture(autouse=True)
def no_market(monkeypatch):
    """Never call ESI's market from tests: no order books, so prices stay at the average.
    Tests that price from orders set their own books."""
    from apps.esidata import market

    monkeypatch.setattr(market, "jita_sell_books", lambda ids, refresh=False: ({}, set()))


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
