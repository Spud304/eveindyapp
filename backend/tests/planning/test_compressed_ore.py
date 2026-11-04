"""The compressed ore endpoint: the plan's Tritanium shortfall bought as ore (tiny SDE has no
ores, so the ore list and skill bonuses are stubbed)."""

import pytest
from django.test import Client

from apps.esidata import market
from apps.esidata.models import CharacterSkill, MarketPrice
from apps.planning.models import Plan, PlanLine, Station
from apps.sde import gamedata
from engine.reprocess import Ore, OreClass
from engine.types import Material

from .conftest import AZBEL_ID, AZBEL_TYPE, D_SYSTEM, MAIN

pytestmark = pytest.mark.django_db
ORE = 900001  # made up: 100 units reprocess into 400 Tritanium
RIG = 46634  # not in the tiny SDE: ignored


@pytest.fixture
def setup(sde, user, monkeypatch):
    station = Station.objects.create(
        user=user,
        name="Refinery",
        location_id=AZBEL_ID,
        system_id=D_SYSTEM,
        structure_type_id=AZBEL_TYPE,
        activities=["manufacturing"],
        source="manual",
    )
    p = Plan.objects.create(user=user, name="rifters")
    PlanLine.objects.create(plan=p, type_id=587, quantity=1)  # 31,680 Tritanium at the Azbel
    for t, price in ((34, 4.0), (ORE, 3.0)):
        MarketPrice.objects.create(
            type_id=t, adjusted_price=price, average_price=price, updated_at="2026-11-03T00:00:00Z"
        )
    CharacterSkill.objects.create(
        character_id=MAIN, skill_id=3385, active_level=5, trained_level=5, skillpoints=0
    )
    ores = (
        Ore(ORE, "Compressed Test Ore", OreClass.ASTEROID, 100, (Material(34, 400),), None, None),
    )
    monkeypatch.setattr(gamedata, "ores", lambda: ores)
    monkeypatch.setattr(gamedata, "reprocessing_skill_bonuses", lambda: {3385: 3.0, 3389: 2.0})
    # Never call ESI from tests: Jita has 10,000 units of the ore at 2 ISK, then more at 9 ISK,
    # and Tritanium at 5 ISK.
    books = {ORE: ((2.0, 10_000), (9.0, 1_000_000)), 34: ((5.0, 10_000_000),)}
    monkeypatch.setattr(
        market, "jita_sell_books", lambda ids: ({t: books[t] for t in ids if t in books}, set())
    )
    c = Client()
    c.force_login(user)
    return c, p, station


def test_tritanium_bought_as_ore(setup):
    c, p, station = setup
    resp = c.get(f"/api/plans/{p.pk}/compressed-ore?prices=average")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["station_id"] == station.pk
    assert body["stations"][0]["detail"] == "50.0% on asteroid ore"
    mix = body["mix"]
    # Yield: 0.50 station x 1.15 (Reprocessing V) = 57.5%: 230 Tritanium per batch.
    [line] = mix["ores"]
    assert line["efficiency"] == pytest.approx(0.575)
    assert line["batches"] == -(-31680 // 230)  # 138 batches
    assert line["quantity"] == 13800
    [trit] = mix["minerals"]
    assert trit["needed"] == 31680 and trit["produced"] >= 31680
    assert mix["ore_cost"] == pytest.approx(13800 * 3.0)
    assert mix["mineral_cost"] == pytest.approx(31680 * 4.0)
    assert body["names"] == {"34": "Tritanium"}


def test_bad_choices_are_refused(setup):
    c, p, _ = setup
    assert c.get(f"/api/plans/{p.pk}/compressed-ore?station_id=999").status_code == 422
    assert c.get(f"/api/plans/{p.pk}/compressed-ore?character_id=1").status_code == 422
    assert c.get(f"/api/plans/{p.pk}/compressed-ore?ore_classes=gas").status_code == 422
    assert (
        c.get(f"/api/plans/{p.pk}/compressed-ore?ore_classes=moon").json()["mix"]["feasible"]
        is False
    )


def test_priced_from_jita_orders(setup):
    c, p, _ = setup
    body = c.get(f"/api/plans/{p.pk}/compressed-ore").json()
    assert body["prices"] == "jita" and body["priced_at_average"] == 0
    [line] = body["mix"]["ores"]
    # 138 batches = 13,800 units: 10,000 at 2 ISK, 3,800 at 9 ISK.
    assert line["total"] == pytest.approx(10_000 * 2 + 3_800 * 9)
    assert line["top_price"] == 9.0 and line["on_sale"] == 1_010_000
    assert body["mix"]["mineral_cost"] == pytest.approx(31680 * 5.0)


def test_failed_fetch_falls_back_to_average(setup, monkeypatch):
    c, p, _ = setup
    monkeypatch.setattr(market, "jita_sell_books", lambda ids: ({}, set(ids)))
    body = c.get(f"/api/plans/{p.pk}/compressed-ore").json()
    assert body["priced_at_average"] == 2
    assert body["mix"]["ore_cost"] == pytest.approx(13800 * 3.0)
