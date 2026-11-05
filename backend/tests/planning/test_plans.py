"""Plans: CRUD, active plan, rule overrides, and asset reservation.

Rifter (587) is built from 32,000 Tritanium (34) per run; at an Azbel (material x0.99) that
is 31,680 per Rifter."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import services
from apps.accounts.sso import SsoIdentity
from apps.esidata.models import BlueprintItem, IndustryJob
from apps.planning import inputs, reservation
from apps.planning.models import Plan, PlanLine, Station
from engine.types import BuildCategory, BuildRules

from .conftest import AZBEL_ID, AZBEL_TYPE, CORP, D_SYSTEM, MAIN, OTHER_CHAR, asset, job

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
    rules = inputs.effective_rules(default, p)
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
    assert body["moves"] == []


def test_result_lists_stock_to_carry_to_the_building_station(api, user, azbel, raitaru):
    asset(1, 34, 20_000, AZBEL_ID)
    asset(2, 34, 30_000, RAITARU_LOC, flag="CorpSAG3", kind="corporation", owner=CORP)
    # Builds at the Azbel only; the Raitaru's hangar counts as stock.
    p = make_plan(user, "Split", station_ids=[azbel.pk], extra_location_ids=[RAITARU_LOC])
    (move,) = api("get", f"/api/plans/{p.pk}/result").json()["moves"]
    assert move == {
        "kind": "stock",
        "from_station_id": None,
        "type_id": 34,
        "name": "Tritanium",
        "quantity": PER_RIFTER - 20_000,
        "volume": 0.0,  # the test SDE has no volumes; test_hauling checks them
        "from_location_id": RAITARU_LOC,
        "from_name": "Raitaru",
        "from_hangar": "CorpSAG3",
        "to_station_id": azbel.pk,
        "to_name": "Azbel",
    }


# --- picked BPC lines ----------------------------------------------------------------------


def rifter_bp(item_id, runs=9, copy=True, me=10):
    return BlueprintItem.objects.create(
        owner_kind="character",
        owner_id=MAIN,
        item_id=item_id,
        type_id=691,
        location_id=AZBEL_ID,
        location_flag="Hangar",
        quantity=-2 if copy else -1,
        runs=runs if copy else -1,
        material_efficiency=me,
        time_efficiency=20,
        root_location_id=AZBEL_ID,
        hangar_flag="Hangar",
    )


def bpc_line(*ids, type_id=587):
    return {"type_id": type_id, "quantity": 1, "blueprint_item_ids": list(ids)}


def test_picked_bpc_line_quantity_comes_from_runs(api, azbel):
    rifter_bp(1, 9)
    rifter_bp(2, 4)
    resp = api("post", "/api/plans", {"name": "a", "lines": [bpc_line(1, 2)]})
    assert resp.status_code == 201, resp.content
    [line] = resp.json()["lines"]
    assert (line["quantity"], line["blueprint_item_ids"]) == (13, [1, 2])


def test_picked_bpc_line_validation(api, azbel):
    rifter_bp(1)
    rifter_bp(2, copy=False)
    pid = api("post", "/api/plans", {"name": "a"}).json()["id"]

    def put(*lines):
        return api("put", f"/api/plans/{pid}/lines", list(lines))

    assert put(bpc_line(1, 1)).status_code == 422  # twice in one line
    assert put(bpc_line(1), bpc_line(1)).status_code == 422  # twice in the plan
    assert put(bpc_line(2)).status_code == 422  # an original
    assert put(bpc_line(77)).status_code == 422  # not in the library
    assert put(bpc_line(1, type_id=34)).status_code == 422  # does not make Tritanium
    assert put(bpc_line(1)).status_code == 200
    other = api("post", "/api/plans", {"name": "b"}).json()["id"]
    resp = api("put", f"/api/plans/{other}/lines", [bpc_line(1)])
    assert resp.status_code == 409
    assert "plan a" in resp.json()["detail"]


def test_picked_bpcs_belong_to_their_plan(api, user, azbel):
    rifter_bp(1, 9)
    rifter_bp(2, 9)
    picker = api("post", "/api/plans", {"name": "picker", "lines": [bpc_line(1)]}).json()["id"]
    other = make_plan(user, "other", rifters=18)
    runs = reservation.run_plans(user)

    def bpc_runs(pid):
        jobs = runs[pid].result.jobs
        return sorted(j.runs for j in jobs if j.blueprint_type_id == 691 and j.source == "bpc")

    assert bpc_runs(picker) == [9]
    assert bpc_runs(other.pk) == [9]  # only BPC 2; BPC 1 belongs to "picker"
    rows = {r["item_id"]: r for r in api("get", "/api/library/blueprints").json()}
    assert (rows[1]["plan_id"], rows[1]["plan_name"]) == (picker, "picker")
    assert rows[2]["plan_id"] is None
    assert rows[1]["product_type_id"] == 587


def test_reserving_plans_take_bpc_runs_in_priority_order(user, azbel):
    rifter_bp(1, 9)
    first = make_plan(user, "first", rifters=6, reserve_assets=True, priority=1)
    second = make_plan(user, "second", rifters=6, reserve_assets=True, priority=2)
    runs = reservation.run_plans(user)

    def bpc_jobs(pid):
        return [
            (j.runs, j.blueprint_item_id)
            for j in runs[pid].result.jobs
            if j.blueprint_type_id == 691 and j.source == "bpc"
        ]

    assert bpc_jobs(first.pk) == [(6, 1)]
    assert bpc_jobs(second.pk) == [(3, 1)]  # the 3 runs "first" leaves on the copy


def test_two_reserving_plans_on_one_bpo_are_warned(user, azbel):
    rifter_bp(1, copy=False)
    make_plan(user, "first", reserve_assets=True, priority=1)
    second = make_plan(user, "second", reserve_assets=True, priority=2)
    run = reservation.run_plans(user)[second.pk]
    assert any("Plan first also schedules Rifter Blueprint" in w.text for w in run.result.warnings)


def test_blueprints_in_open_jobs(api, user, azbel):
    rifter_bp(1, copy=False)
    rifter_bp(2, 9)
    copying = job(10, AZBEL_ID, activity=5, owner_kind="character", owner=MAIN)
    IndustryJob.objects.filter(pk=copying.pk).update(blueprint_id=1)  # ended 2026-11-03 01:00
    building = job(11, AZBEL_ID, activity=1, owner_kind="character", owner=MAIN)
    IndustryJob.objects.filter(pk=building.pk).update(
        blueprint_id=2, end_date=timezone.now() + timedelta(hours=2)
    )
    owned = {b.item_id: b for b in inputs.owned_blueprints(user)}
    assert owned[1].job_activity_id == 5 and owned[1].job_ends_in < 0
    assert owned[2].job_activity_id == 1 and 7000 < owned[2].job_ends_in <= 7200
    rows = {r["item_id"]: r for r in api("get", "/api/library/blueprints").json()}
    assert (rows[1]["job_activity"], rows[1]["job_status"]) == ("copying", "ready")
    assert (rows[2]["job_activity"], rows[2]["job_status"]) == ("manufacturing", "active")
    IndustryJob.objects.filter(pk=copying.pk).update(status="delivered")
    rows = {r["item_id"]: r for r in api("get", "/api/library/blueprints").json()}
    assert rows[1]["job_status"] is None


# --- opt-in purchases ----------------------------------------------------------------------


def test_purchase_options_and_saving_one(api, user, azbel):
    pid = api("post", "/api/plans", {"name": "a", "lines": [{"type_id": 587, "quantity": 4}]})
    pid = pid.json()["id"]
    resp = api("get", f"/api/plans/{pid}/blueprints/691/options")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    kinds = {o["kind"]: o for o in body["options"]}
    assert set(kinds) == {"bpcs", "bpo"}
    bpcs = kinds["bpcs"]
    assert bpcs["count"] == 1 and bpcs["purchase_cost"] is None

    choice = {"buy_bpcs": 1, "bpc_runs": bpcs["runs_per_bpc"], "bpc_price": 2_000_000}
    assert api("patch", f"/api/plans/{pid}", {"choices": {"691": choice}}).status_code == 200
    result = api("get", f"/api/plans/{pid}/result").json()["result"]
    assert "bought" in next(b for b in result["blueprints"] if b["type_id"] == 691)["sources"]
    assert result["costs"]["blueprints"] == 2_000_000
    assert api("get", f"/api/plans/{pid}/blueprints/587/options").json()["options"] == []


def test_settings_refuse_unknown_hangars_and_foreign_locations(api, user, azbel):
    p = make_plan(user, "scope")

    def patch(body):
        return api("patch", f"/api/plans/{p.pk}", body)

    assert patch({"hangar_flags": ["CorpSAG3", "Hangar"]}).status_code == 200
    resp = patch({"hangar_flags": ["CorpSAG9"]})
    assert resp.status_code == 422 and "CorpSAG9" in resp.json()["detail"]
    asset(1, 34, 10, AZBEL_ID)
    assert patch({"extra_location_ids": [AZBEL_ID]}).status_code == 200
    resp = patch({"extra_location_ids": [123]})
    assert resp.status_code == 422 and "123" in resp.json()["detail"]


def test_result_reports_how_old_its_data_is(api, user, azbel):
    from datetime import timedelta

    from django.utils import timezone

    from apps.esidata.models import FeedStatus

    now = timezone.now()
    for kind, owner, feeds in (
        ("character", MAIN, ("skills", "assets", "blueprints", "jobs")),
        ("corporation", CORP, ("assets", "blueprints", "jobs")),
    ):
        for feed in feeds:
            FeedStatus.objects.create(
                owner_kind=kind,
                owner_id=owner,
                feed=feed,
                ok=True,
                attempted_at=now,
                fetched_at=now - timedelta(minutes=5),
            )
    FeedStatus.objects.filter(owner_kind="corporation", feed="assets").update(
        fetched_at=now - timedelta(days=2)
    )
    inputs = api("get", f"/api/plans/{make_plan(user, 'p').pk}/result").json()["inputs"]
    assert inputs["as_of"] is not None
    [problem] = inputs["problems"]
    assert problem["severity"] == "warn" and problem["feed"] == "assets"
    assert problem["text"].endswith("assets: last synced 2 days ago.")


def test_result_priced_from_jita_orders(api, user, azbel, monkeypatch):
    from apps.esidata import market

    monkeypatch.setattr(
        market,
        "jita_sell_books",
        lambda ids, refresh=False: ({34: ((2.0, 10**9),)}, set(ids) - {34}),
    )
    p = make_plan(user, "jita")
    body = api("get", f"/api/plans/{p.pk}/result").json()
    assert body["prices"] == "jita" and body["priced_at_average"] == 0
    [trit] = [s for s in body["result"]["shopping_list"] if s["type_id"] == 34]
    assert (trit["price_source"], trit["unit_price"]) == ("jita", 2.0)
    assert body["result"]["costs"]["materials"] == PER_RIFTER * 2.0
    avg = api("get", f"/api/plans/{p.pk}/result?prices=average").json()
    [trit] = [s for s in avg["result"]["shopping_list"] if s["type_id"] == 34]
    assert avg["prices"] == "average" and trit["price_source"] == "average"


# --- completing a plan ---------------------------------------------------------------------


def test_complete_deactivates_and_blocks_activation_until_reopened(api):
    pid = api("post", "/api/plans", {"name": "done"}).json()["id"]
    api("post", f"/api/plans/{pid}/activate")
    body = api("post", f"/api/plans/{pid}/complete").json()
    assert body["completed_at"] is not None and not body["is_active"]
    assert api("post", f"/api/plans/{pid}/activate").status_code == 409
    assert api("post", f"/api/plans/{pid}/reopen").json()["completed_at"] is None
    assert api("post", f"/api/plans/{pid}/activate").json()["is_active"]


def test_a_completed_plan_reserves_nothing(api, user, azbel):
    asset(1, 34, 40_000, AZBEL_ID)
    first = make_plan(user, "First", reserve_assets=True, priority=1)
    second = make_plan(user, "Second", reserve_assets=True, priority=2)
    assert trit(reservation.run_plans(user)[second.pk]).on_hand_used == 40_000 - PER_RIFTER
    api("post", f"/api/plans/{first.pk}/complete")
    assert trit(reservation.run_plans(user)[second.pk]).on_hand_used == PER_RIFTER
    body = api("get", f"/api/plans/{first.pk}/result").json()
    assert body["reservation"]["reserves"] is False and body["reservation"]["claims"] == {}


def test_a_completed_plan_releases_its_picked_bpcs(api, azbel):
    rifter_bp(1, 9)
    done = api("post", "/api/plans", {"name": "done", "lines": [bpc_line(1)]}).json()["id"]
    other = api("post", "/api/plans", {"name": "next"}).json()["id"]
    assert api("put", f"/api/plans/{other}/lines", [bpc_line(1)]).status_code == 409
    api("post", f"/api/plans/{done}/complete")
    assert api("put", f"/api/plans/{other}/lines", [bpc_line(1)]).status_code == 200
    # Reopening would pick the same copy twice.
    resp = api("post", f"/api/plans/{done}/reopen")
    assert resp.status_code == 409 and "next" in resp.json()["detail"]
