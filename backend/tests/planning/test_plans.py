"""Plans: CRUD, active plan, rule overrides, and asset reservation.

Rifter (587) is built from 32,000 Tritanium (34) per run; at an Azbel (material x0.99) that
is 31,680 per Rifter."""

import pytest

from apps.accounts import services
from apps.accounts.sso import SsoIdentity
from apps.planning import reservation
from apps.planning.models import Plan, PlanLine, Station
from engine.types import BuildCategory, BuildRules

from .conftest import AZBEL_ID, AZBEL_TYPE, D_SYSTEM, OTHER_CHAR, asset

pytestmark = pytest.mark.django_db

RAITARU_LOC = 1055512108602
PER_RIFTER = 31680


@pytest.fixture
def azbel(sde, user):
    return Station.objects.create(
        user=user,
        name="Azbel",
        location_id=AZBEL_ID,
        system_id=D_SYSTEM,
        structure_type_id=AZBEL_TYPE,
        activities=["manufacturing"],
        source="manual",
    )


@pytest.fixture
def raitaru(sde, user):
    return Station.objects.create(
        user=user,
        name="Raitaru",
        location_id=RAITARU_LOC,
        system_id=D_SYSTEM,
        structure_type_id=AZBEL_TYPE,
        activities=["manufacturing"],
        source="manual",
    )


def make_plan(user, name, rifters=1, **kw):
    p = Plan.objects.create(user=user, name=name, **kw)
    PlanLine.objects.create(plan=p, type_id=587, quantity=rifters)
    return p


def trit(run):
    item = next((i for i in run.result.items if i.type_id == 34), None)
    return item


# --- reservation ---------------------------------------------------------------------------


def test_reserving_plans_claim_in_priority_order(user, azbel):
    asset(1, 34, 40_000, AZBEL_ID)
    first = make_plan(user, "First", reserve_assets=True, priority=1)
    second = make_plan(user, "Second", reserve_assets=True, priority=2)
    runs = reservation.run_plans(user)
    assert runs[first.pk].claims == {34: PER_RIFTER}
    assert trit(runs[first.pk]).to_buy == 0
    assert runs[second.pk].claims == {34: 40_000 - PER_RIFTER}
    assert trit(runs[second.pk]).to_buy == PER_RIFTER - (40_000 - PER_RIFTER)
    (holder,) = runs[second.pk].held_elsewhere[34]
    assert (holder.plan_id, holder.quantity) == (first.pk, PER_RIFTER)
    assert runs[first.pk].held_elsewhere == {}


def test_priority_change_swaps_who_gets_the_stock(user, azbel):
    asset(1, 34, 40_000, AZBEL_ID)
    first = make_plan(user, "First", reserve_assets=True, priority=1)
    second = make_plan(user, "Second", reserve_assets=True, priority=2)
    Plan.objects.filter(pk=second.pk).update(priority=0)
    runs = reservation.run_plans(user)
    assert runs[second.pk].claims == {34: PER_RIFTER}
    assert runs[first.pk].claims == {34: 40_000 - PER_RIFTER}


def test_non_reserving_plans_see_leftovers_and_do_not_block_each_other(user, azbel):
    asset(1, 34, 40_000, AZBEL_ID)
    holder = make_plan(user, "Holder", reserve_assets=True)
    a = make_plan(user, "A")
    b = make_plan(user, "B")
    runs = reservation.run_plans(user)
    left = 40_000 - PER_RIFTER
    for p in (a, b):
        assert trit(runs[p.pk]).on_hand_used == left  # both see the same leftovers
        assert runs[p.pk].claims == {}
        assert [h.plan_id for h in runs[p.pk].held_elsewhere[34]] == [holder.pk]


def test_claims_only_from_the_plans_own_locations(user, azbel, raitaru):
    asset(1, 34, 40_000, AZBEL_ID)
    asset(2, 34, 5_000, RAITARU_LOC)
    at_raitaru = make_plan(
        user, "Raitaru", reserve_assets=True, priority=1, station_ids=[raitaru.pk]
    )
    at_azbel = make_plan(user, "Azbel", reserve_assets=True, priority=2, station_ids=[azbel.pk])
    runs = reservation.run_plans(user)
    assert runs[at_raitaru.pk].claims == {34: 5_000}  # its own stock only
    assert runs[at_azbel.pk].claims == {34: PER_RIFTER}  # untouched by the Raitaru plan
    assert runs[at_azbel.pk].held_elsewhere == {}


def test_extra_locations_and_hangar_filter(user, azbel):
    asset(1, 34, 10_000, AZBEL_ID, flag="CorpSAG2", kind="corporation", owner=98000001)
    asset(2, 34, 7_000, AZBEL_ID, flag="CorpSAG4", kind="corporation", owner=98000001)
    asset(3, 34, 3_000, RAITARU_LOC)  # not a station of the plan
    p = make_plan(user, "P", hangar_flags=["CorpSAG2"])
    assert trit(reservation.run_plans(user)[p.pk]).on_hand_used == 10_000
    Plan.objects.filter(pk=p.pk).update(hangar_flags=[], extra_location_ids=[RAITARU_LOC])
    assert trit(reservation.run_plans(user)[p.pk]).on_hand_used == 20_000


def test_only_requested_plans_returned_but_reservers_always_run(user, azbel):
    asset(1, 34, 40_000, AZBEL_ID)
    reserver = make_plan(user, "R", reserve_assets=True)
    other = make_plan(user, "O")
    runs = reservation.run_plans(user, [other])
    assert set(runs) == {other.pk}
    assert runs[other.pk].held_elsewhere[34][0].plan_id == reserver.pk


def test_plan_without_lines_reports_an_error(user, azbel):
    p = Plan.objects.create(user=user, name="Empty")
    assert reservation.run_plans(user)[p.pk].error == "plan has no lines"


# --- rules ---------------------------------------------------------------------------------


def test_effective_rules_apply_plan_overrides():
    default = BuildRules(
        item_blacklist=frozenset({34, 35}),
        buy_categories=frozenset({BuildCategory.FUEL_BLOCKS, BuildCategory.T2_ITEMS}),
    )
    p = Plan(
        blacklist_add=[36],
        blacklist_remove=[35],
        category_overrides={"t2_items": "build", "capital_components": "buy"},
    )
    rules = reservation.effective_rules(default, p)
    assert rules.item_blacklist == {34, 36}
    assert rules.buy_categories == {BuildCategory.FUEL_BLOCKS, BuildCategory.CAPITAL_COMPONENTS}


def test_plan_blacklist_reaches_the_engine_but_lines_are_still_built(user, azbel):
    p = make_plan(user, "P", blacklist_add=[587])
    run = reservation.run_plans(user)[p.pk]
    assert 587 in run.rules.item_blacklist
    rifter = next(i for i in run.result.items if i.type_id == 587)
    assert rifter.decision == "build" and rifter.reason.code == "plan_line"


def test_choices_reach_the_engine(user, azbel):
    p = make_plan(user, "P", choices={"691": {"me": 10}})
    run = reservation.run_plans(user)[p.pk]
    job = next(j for j in run.result.jobs if j.blueprint_type_id == 691)
    assert job.me == 10 and job.me_reason.code == "me_override"


# --- API -----------------------------------------------------------------------------------


@pytest.fixture
def api(client, user):
    client.force_login(user)

    def call(method, path, body=None):
        fn = getattr(client, method)
        if body is None:
            return fn(path)
        return fn(path, body, content_type="application/json")

    return call


def test_plan_crud(api, azbel):
    resp = api(
        "post", "/api/plans", {"name": "indy 1", "lines": [{"type_id": 587, "quantity": 10}]}
    )
    assert resp.status_code == 201, resp.content
    pid = resp.json()["id"]
    assert resp.json()["lines"][0]["name"] == "Rifter"
    resp = api(
        "patch",
        f"/api/plans/{pid}",
        {
            "reserve_assets": True,
            "priority": 5,
            "category_overrides": {"t2_items": "buy"},
            "choices": {"691": {"me": 8, "decryptor": "none"}},
            "station_ids": [azbel.pk],
        },
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["reserve_assets"] and body["priority"] == 5
    assert body["category_overrides"] == {"t2_items": "buy"}
    assert body["choices"]["691"]["me"] == 8
    resp = api(
        "put",
        f"/api/plans/{pid}/lines",
        [{"type_id": 587, "quantity": 3}, {"type_id": 34, "quantity": 1}],
    )
    assert [ln["quantity"] for ln in resp.json()["lines"]] == [3, 1]
    assert [p["name"] for p in api("get", "/api/plans").json()] == ["indy 1"]
    assert api("delete", f"/api/plans/{pid}").status_code == 204


def test_plan_validation(api, azbel):
    assert (
        api(
            "post", "/api/plans", {"name": "x", "lines": [{"type_id": 999999999, "quantity": 1}]}
        ).status_code
        == 422
    )
    pid = api("post", "/api/plans", {"name": "x"}).json()["id"]
    assert (
        api("patch", f"/api/plans/{pid}", {"category_overrides": {"nonsense": "buy"}}).status_code
        == 422
    )
    assert api("patch", f"/api/plans/{pid}", {"station_ids": [987654]}).status_code == 422
    assert api("patch", f"/api/plans/{pid}", {"choices": {"691": {"me": 50}}}).status_code == 422


def test_one_active_plan(api, user):
    a = api("post", "/api/plans", {"name": "a"}).json()["id"]
    b = api("post", "/api/plans", {"name": "b"}).json()["id"]
    assert api("post", f"/api/plans/{a}/activate").json()["activated_at"] is not None
    assert api("post", f"/api/plans/{b}/activate").json()["is_active"]
    assert not api("get", f"/api/plans/{a}").json()["is_active"]
    assert Plan.objects.filter(user=user, is_active=True).count() == 1
    assert not api("post", f"/api/plans/{b}/deactivate").json()["is_active"]


def test_plans_are_private_to_the_account(api, sde):
    other = services.ensure_user(
        services.upsert_character(SsoIdentity(OTHER_CHAR, "O", "x", ()), {})
    )
    theirs = Plan.objects.create(user=other, name="theirs")
    assert api("get", f"/api/plans/{theirs.pk}").status_code == 404
    assert api("get", f"/api/plans/{theirs.pk}/result").status_code == 404
    assert api("get", "/api/plans").json() == []


def test_result_endpoint(api, user, azbel):
    asset(1, 34, 40_000, AZBEL_ID)
    holder = make_plan(user, "Holder", reserve_assets=True, priority=1)
    p = make_plan(user, "Mine", reserve_assets=True, priority=2)
    body = api("get", f"/api/plans/{p.pk}/result").json()
    assert body["error"] == ""
    assert body["reservation"]["claims"] == {"34": 40_000 - PER_RIFTER}
    assert body["reservation"]["held_elsewhere"]["34"] == [
        {"plan_id": holder.pk, "plan_name": "Holder", "quantity": PER_RIFTER}
    ]
    trit_row = next(s for s in body["result"]["shopping_list"] if s["type_id"] == 34)
    assert trit_row["quantity"] == PER_RIFTER - (40_000 - PER_RIFTER)
