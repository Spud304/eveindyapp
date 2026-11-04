"""Sharing (step 7): link and corp visibility, aliases for link viewers, the cache."""

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import EveCharacter
from apps.accounts.sso import SsoIdentity
from apps.planning import reservation, sharing
from apps.planning.models import Plan, PlanLine, Station

from .conftest import AZBEL_ID, AZBEL_TYPE, CORP, D_SYSTEM, MAIN, OTHER_CHAR

pytestmark = pytest.mark.django_db
OTHER_CORP = 98000002


@pytest.fixture
def plan(sde, user):
    Station.objects.create(
        user=user,
        name="Secret Keep",
        location_id=AZBEL_ID,
        system_id=D_SYSTEM,
        structure_type_id=AZBEL_TYPE,
        activities=["manufacturing"],
        source="manual",
    )
    p = Plan.objects.create(user=user, name="Shared rifters")
    PlanLine.objects.create(plan=p, type_id=587, quantity=2)
    return p


def logged_in(user):
    c = Client()
    c.force_login(user)
    return c


def corpmate(corp=CORP):
    ch = services.upsert_character(
        SsoIdentity(OTHER_CHAR, "Mate", "x", ()), {"corporation_id": corp}
    )
    return services.ensure_user(ch)


def patch(user, p, body):
    return logged_in(user).patch(f"/api/plans/{p.pk}", body, content_type="application/json")


def test_link_view_needs_no_login_and_hides_names(user, plan):
    body = patch(user, plan, {"visibility": "link"}).json()
    token = body["share_token"]
    assert token
    resp = Client().get(f"/api/shared/{token}")
    assert resp.status_code == 200, resp.content
    shared = resp.json()
    assert shared["anonymized"] and shared["plan_id"] is None and shared["owner_name"] is None
    assert shared["name"] == "Shared rifters"
    assert shared["lines"] == [{"type_id": 587, "name": "Rifter", "quantity": 2}]
    assert shared["stations"] == {"1": "Station 1"}
    assert all(v.startswith("Builder ") for v in shared["characters"].values())
    text = json.dumps(shared)
    assert "Secret Keep" not in text and str(MAIN) not in text
    assert {j["station_id"] for j in shared["result"]["jobs"]} <= {1, None}
    assert "Station 1" in shared["result"]["blueprints"][0]["station"]["reason"]["text"]


def test_link_stops_working_when_private_or_renewed(user, plan):
    token = patch(user, plan, {"visibility": "link"}).json()["share_token"]
    assert Client().get("/api/shared/nonsense").status_code == 404
    renewed = logged_in(user).post(f"/api/plans/{plan.pk}/share-link").json()["share_token"]
    assert renewed != token
    assert Client().get(f"/api/shared/{token}").status_code == 404
    assert Client().get(f"/api/shared/{renewed}").status_code == 200
    patch(user, plan, {"visibility": "private"})
    assert Client().get(f"/api/shared/{renewed}").status_code == 404


def test_corp_members_see_the_plan_with_names(user, plan):
    mate = corpmate()
    viewer = logged_in(mate)
    assert viewer.get(f"/api/plans/{plan.pk}/view").status_code == 404  # still private
    assert viewer.get("/api/plans/shared-with-me").json() == []
    patch(user, plan, {"visibility": "corp"})
    listed = viewer.get("/api/plans/shared-with-me").json()
    assert [(p["id"], p["owner_name"]) for p in listed] == [(plan.pk, "Main")]
    view = viewer.get(f"/api/plans/{plan.pk}/view").json()
    assert not view["anonymized"] and view["plan_id"] == plan.pk
    assert "Secret Keep" in view["stations"].values()
    assert view["progress"]["candidates"] == []
    # Viewers cannot use the owner's endpoints.
    assert viewer.get(f"/api/plans/{plan.pk}/result").status_code == 404
    assert (
        viewer.patch(f"/api/plans/{plan.pk}", {}, content_type="application/json").status_code
        == 404
    )


def test_other_corps_and_link_plans_are_not_corp_visible(user, plan):
    outsider = logged_in(corpmate(OTHER_CORP))
    patch(user, plan, {"visibility": "corp"})
    assert outsider.get(f"/api/plans/{plan.pk}/view").status_code == 404
    patch(user, plan, {"visibility": "link"})
    assert logged_in(corpmate()).get(f"/api/plans/{plan.pk}/view").status_code == 404


def test_corp_membership_is_checked_again_when_old(user, plan, monkeypatch):
    mate = corpmate()
    patch(user, plan, {"visibility": "corp"})
    EveCharacter.objects.filter(pk=OTHER_CHAR).update(
        affiliation_checked_at=timezone.now() - timedelta(days=2)
    )
    monkeypatch.setattr(
        services,
        "fetch_affiliation",
        lambda cid: {"corporation_id": OTHER_CORP, "alliance_id": None},
    )
    assert logged_in(mate).get(f"/api/plans/{plan.pk}/view").status_code == 404
    assert EveCharacter.objects.get(pk=OTHER_CHAR).corporation_id == OTHER_CORP


def test_share_corporation_must_be_one_of_yours(user, plan):
    assert patch(user, plan, {"share_corporation_id": OTHER_CORP}).status_code == 422
    assert patch(user, plan, {"share_corporation_id": CORP}).status_code == 200


def test_shared_view_is_cached(user, plan, monkeypatch):
    token = patch(user, plan, {"visibility": "link"}).json()["share_token"]
    calls = []
    real = reservation.run_plans
    monkeypatch.setattr(reservation, "run_plans", lambda *a, **k: calls.append(1) or real(*a, **k))
    Client().get(f"/api/shared/{token}")
    Client().get(f"/api/shared/{token}")
    assert len(calls) == 1
    patch(user, plan, {"name": "renamed"})  # an edit changes the cache key
    assert Client().get(f"/api/shared/{token}").json()["name"] == "renamed"
    assert len(calls) == 2
    assert sharing.SHARED_CACHE_SECONDS == 60
