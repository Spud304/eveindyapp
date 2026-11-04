from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import services
from apps.accounts.sso import SsoIdentity
from apps.esidata import names
from apps.esidata.models import (
    BlueprintItem,
    CharacterRoles,
    CharacterSkill,
    CorpDivision,
    Corporation,
    IndustryJob,
)
from apps.planning.models import Station

pytestmark = pytest.mark.django_db

MAIN, CORPMATE, CORP, STRUCTURE = 90000001, 90000077, 98000001, 1055981940385


@pytest.fixture
def user(monkeypatch):
    monkeypatch.setattr(
        names, "resolve", lambda ids, client=None: {CORPMATE: "Corpmate", CORP: "Test Corp"}
    )
    ch = services.upsert_character(SsoIdentity(MAIN, "Main", "o", ()), {"corporation_id": CORP})
    u = services.ensure_user(ch)
    services.store_tokens(ch, {"access_token": "a", "refresh_token": "r"}, ("publicData",))
    CharacterRoles.objects.create(character_id=MAIN, corporation_id=CORP, roles=["Director"])
    Corporation.objects.create(id=CORP, name="Test Corp")
    CorpDivision.objects.create(corporation_id=CORP, division=2, name="Build Projects")
    Station.objects.create(
        user=u,
        name="Azbel",
        location_id=STRUCTURE,
        system_id=1,
        structure_type_id=35826,
        activities=["manufacturing"],
        source="discovered",
    )
    return u


@pytest.fixture
def api(client, user):
    client.force_login(user)
    return client


def bp(item_id, quantity, runs=-1, owner_kind="corporation", owner=CORP, flag="CorpSAG2"):
    return BlueprintItem.objects.create(
        owner_kind=owner_kind,
        owner_id=owner,
        item_id=item_id,
        type_id=691,
        location_id=STRUCTURE,
        location_flag=flag,
        quantity=quantity,
        runs=runs,
        material_efficiency=10,
        time_efficiency=20,
        root_location_id=STRUCTURE,
        hangar_flag=flag,
    )


def job(
    job_id,
    installer=MAIN,
    activity=1,
    status="active",
    ends_in=3600,
    owner_kind="corporation",
    owner=CORP,
):
    now = timezone.now()
    return IndustryJob.objects.create(
        job_id=job_id,
        owner_kind=owner_kind,
        owner_id=owner,
        installer_id=installer,
        facility_id=STRUCTURE,
        location_id=STRUCTURE,
        activity_id=activity,
        blueprint_id=1,
        blueprint_type_id=691,
        blueprint_location_id=STRUCTURE,
        output_location_id=STRUCTURE,
        runs=1,
        status=status,
        duration=1,
        start_date=now - timedelta(hours=1),
        end_date=now + timedelta(seconds=ends_in),
        last_seen_at=now,
    )


def test_library_kinds_divisions_and_locations(api):
    bp(1, -1)
    bp(2, -2, runs=5)
    bp(3, 4)  # a stack of 4 unresearched originals
    bp(4, -1, owner_kind="character", owner=MAIN, flag="Hangar")
    rows = {r["item_id"]: r for r in api.get("/api/library/blueprints").json()}
    assert [rows[i]["kind"] for i in (1, 2, 3, 4)] == ["bpo", "bpc", "stack", "bpo"]
    assert rows[3]["quantity"] == 4 and rows[2]["runs"] == 5
    assert rows[1]["hangar"] == "Build Projects" and rows[4]["hangar"] == "Hangar"
    assert rows[1]["location_name"] == "Azbel" and rows[1]["owner_name"] == "Test Corp"


def test_library_hides_corp_blueprints_without_director(api):
    bp(1, -1)
    CharacterRoles.objects.filter(character_id=MAIN).update(roles=["Factory_Manager"])
    assert api.get("/api/library/blueprints").json() == []


def test_dashboard_jobs_status_and_installer(api):
    job(1)  # running
    job(2, ends_in=-60)  # ESI still says active, but it has finished
    job(3, installer=CORPMATE)
    job(4, status="delivered")  # delivered long ago: dropped
    IndustryJob.objects.filter(pk=4).update(completed_date=timezone.now() - timedelta(days=3))
    rows = {j["job_id"]: j for j in api.get("/api/dashboard").json()["jobs"]}
    assert set(rows) == {1, 2, 3}
    assert rows[1]["status"] == "active" and rows[2]["status"] == "ready"
    assert rows[3]["installer_name"] == "Corpmate" and not rows[3]["mine"]
    assert rows[1]["installer_name"] == "Main" and rows[1]["mine"]
    assert rows[1]["facility_name"] == "Azbel"


def test_dashboard_slots_from_skills_and_jobs(api):
    CharacterSkill.objects.create(
        character_id=MAIN, skill_id=3387, active_level=4, trained_level=4, skillpoints=1
    )  # Mass Production
    job(1)
    job(2, ends_in=-60)
    job(3, activity=8)  # invention uses a science slot
    job(4, installer=CORPMATE)  # not this account's slot
    (char,) = api.get("/api/dashboard").json()["characters"]
    slots = {s["kind"]: s for s in char["slots"]}
    assert slots["manufacturing"] == {"kind": "manufacturing", "max": 5, "running": 1, "ready": 1}
    assert slots["science"]["running"] == 1 and slots["reaction"]["max"] == 1


def test_dashboard_problems(api, user):
    Station.objects.filter(user=user).update(tax_confirmed=False)
    problems = [p["text"] for p in api.get("/api/dashboard").json()["problems"]]
    assert any("Main is missing" in p and "ESI scopes" in p for p in problems)
    assert any(p.startswith("Azbel: tax not set") and "no rigs entered" in p for p in problems)


def test_overview_requires_login(client):
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/library/blueprints").status_code == 401
