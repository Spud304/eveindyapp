"""Job tracking: matching jobs to the active plan, progress fed to the engine, the API.

Tiny SDE: Rifter Blueprint (691) makes 1 Rifter (587) from 32,000 Tritanium (34)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import services
from apps.accounts.sso import SsoIdentity
from apps.esidata.models import CharacterRoles, IndustryJob
from apps.planning import inputs, reservation, tracker
from apps.planning.models import JobLink, Plan, PlanLine, Station

from .conftest import AZBEL_ID, AZBEL_TYPE, CORP, D_SYSTEM, MAIN, OTHER_CHAR

pytestmark = pytest.mark.django_db

RIFTER, RIFTER_BP, TRIT = 587, 691, 34


@pytest.fixture
def setup(sde, user):
    Station.objects.create(
        user=user,
        name="Azbel",
        location_id=AZBEL_ID,
        system_id=D_SYSTEM,
        structure_type_id=AZBEL_TYPE,
        activities=["manufacturing"],
        source="manual",
    )
    p = Plan.objects.create(
        user=user, name="P", is_active=True, activated_at=timezone.now() - timedelta(hours=2)
    )
    PlanLine.objects.create(plan=p, type_id=RIFTER, quantity=3)
    return p


def job(
    job_id,
    *,
    runs=1,
    started_ago_h=1.0,
    status="active",
    activity=1,
    bp=RIFTER_BP,
    product=RIFTER,
    owner_kind="corporation",
    owner=CORP,
    installer=MAIN,
):
    now = timezone.now()
    start = now - timedelta(hours=started_ago_h)
    return IndustryJob.objects.create(
        job_id=job_id,
        owner_kind=owner_kind,
        owner_id=owner,
        installer_id=installer,
        facility_id=AZBEL_ID,
        location_id=AZBEL_ID,
        activity_id=activity,
        blueprint_id=1,
        blueprint_type_id=bp,
        blueprint_location_id=AZBEL_ID,
        output_location_id=AZBEL_ID,
        product_type_id=product,
        runs=runs,
        status=status,
        duration=3600,
        start_date=start,
        end_date=start + timedelta(hours=10),
        last_seen_at=now,
    )


def linked(p):
    return sorted(JobLink.objects.filter(plan=p).values_list("job_id", flat=True))


# --- matching --------------------------------------------------------------------------------


def test_matches_new_jobs_of_the_plans_blueprints(setup, user):
    job(1)  # after activation, Rifter manufacturing: yes
    job(2, started_ago_h=5)  # before activation: no
    job(3, bp=999, product=None)  # not in the plan: no
    job(4, activity=5)  # copying a Rifter blueprint: the plan has no copy jobs
    job(5, status="cancelled")
    job(6, owner_kind="character", owner=MAIN)  # personal jobs count too
    tracker.match(user)
    assert linked(setup) == [1, 6]
    assert tracker.match(user) == []  # nothing new the second time


def test_no_active_plan_links_nothing(setup, user):
    Plan.objects.filter(pk=setup.pk).update(is_active=False)
    job(1)
    assert tracker.match(user) == []


def test_unlinked_job_is_not_matched_again(setup, user):
    j = job(1)
    tracker.match(user)
    JobLink.objects.filter(job=j).update(plan=None)
    tracker.match(user)
    assert linked(setup) == []


def test_switching_the_active_plan_keeps_links(setup, user):
    job(1)
    tracker.match(user)
    other = Plan.objects.create(user=user, name="Q")
    PlanLine.objects.create(plan=other, type_id=RIFTER, quantity=1)
    Plan.objects.filter(pk=setup.pk).update(is_active=False)
    Plan.objects.filter(pk=other.pk).update(
        is_active=True, activated_at=timezone.now() - timedelta(hours=3)
    )
    job(2)
    tracker.match(user)
    assert linked(setup) == [1] and linked(other) == [2]


def test_jobs_beyond_the_plan_are_still_linked(setup, user):
    job(1, runs=10)  # the plan needs 3 Rifters
    tracker.match(user)
    assert linked(setup) == [1]


def test_match_after_sync_never_raises(user, monkeypatch):
    def boom(u, data=None):
        raise RuntimeError("engine broke")

    monkeypatch.setattr(tracker, "match", boom)
    assert tracker.match_after_sync(user) == 0


# --- progress into the engine ----------------------------------------------------------------


def run(user, p):
    return reservation.run_plans(user, [p])[p.pk].result


def item(result, type_id):
    return next(i for i in result.items if i.type_id == type_id)


def test_running_job_reduces_runs_and_materials(setup, user):
    before = run(user, setup)
    job(1, runs=1)
    tracker.match(user)
    after = run(user, setup)
    assert sum(j.runs for j in before.jobs) == 3 and sum(j.runs for j in after.jobs) == 2
    assert item(after, RIFTER).started == 1
    assert item(after, TRIT).to_buy < item(before, TRIT).to_buy


def test_linked_job_the_account_can_no_longer_read_is_flagged(setup, user):
    job(1, runs=1)
    tracker.match(user)
    assert not any("no longer read" in w.text for w in run(user, setup).warnings)
    CharacterRoles.objects.filter(character_id=MAIN).update(roles=[])  # corp jobs out of reach
    after = run(user, setup)
    assert item(after, RIFTER).started == 1  # still counted, as the warning says
    assert any("1 linked job(s)" in w.text for w in after.warnings)


def test_over_plan_is_reported(setup, user):
    job(1, runs=5)
    tracker.match(user)
    rifter = item(run(user, setup), RIFTER)
    assert (rifter.started, rifter.over_plan) == (3, 2)


def test_delivered_line_output_keeps_counting(setup, user):
    job(1, runs=2, status="delivered")
    tracker.match(user)
    assert item(run(user, setup), RIFTER).started == 2


def test_delivered_component_output_is_left_to_assets(sde, user):
    p = Plan.objects.create(
        user=user, name="P", is_active=True, activated_at=timezone.now() - timedelta(hours=2)
    )
    PlanLine.objects.create(plan=p, type_id=TRIT, quantity=1)  # Tritanium is not built: no keys
    j = job(1, status="delivered")
    JobLink.objects.create(user=user, plan=p, job=j, source="manual")
    started, attempts = tracker.progress_inputs(p, inputs.load(user).game)
    assert started == {} and attempts == {}  # Rifter is not a line of this plan


def test_cancelled_links_count_for_nothing(setup, user):
    j = job(1, runs=2)
    tracker.match(user)
    IndustryJob.objects.filter(pk=j.pk).update(status="cancelled")
    assert item(run(user, setup), RIFTER).started == 0


# --- API -------------------------------------------------------------------------------------


@pytest.fixture
def api(client, user):
    client.force_login(user)
    return client


def test_progress_endpoint(api, setup, user):
    job(1, runs=1)
    job(2, runs=1, started_ago_h=3)  # before activation: a candidate, not linked
    body = api.get(f"/api/plans/{setup.pk}/progress").json()  # matching runs here
    assert body["active"]
    (row,) = [r for r in body["rows"] if r["activity"] == "manufacturing"]
    assert (row["running_runs"], row["remaining_runs"], row["over_plan"]) == (1, 2, 0)
    assert row["product_name"] == "Rifter"
    assert [j["job_id"] for j in body["jobs"]] == [1] and body["jobs"][0]["source"] == "auto"
    assert [j["job_id"] for j in body["candidates"]] == [2]


def test_link_and_unlink_by_hand(api, setup, user):
    job(2, runs=1, started_ago_h=3)
    body = api.post(f"/api/plans/{setup.pk}/jobs/2").json()
    assert [j["job_id"] for j in body["jobs"]] == [2] and body["jobs"][0]["source"] == "manual"
    assert body["candidates"] == []
    body = api.delete(f"/api/plans/{setup.pk}/jobs/2").json()
    assert body["jobs"] == [] and [j["job_id"] for j in body["candidates"]] == [2]
    # With nothing linked, the row still names its product (it comes from the SDE recipe).
    (row,) = [r for r in body["rows"] if r["activity"] == "manufacturing"]
    assert row["product_name"] == "Rifter"
    assert JobLink.objects.get(job_id=2).plan is None  # remembered as unlinked


def test_cannot_link_another_accounts_job(api, setup):
    # A personal job of a character on another account, in another corp.
    services.ensure_user(
        services.upsert_character(SsoIdentity(OTHER_CHAR, "O", "x", ()), {"corporation_id": 555})
    )
    job(9, owner_kind="character", owner=OTHER_CHAR, installer=OTHER_CHAR)
    assert api.post(f"/api/plans/{setup.pk}/jobs/9").status_code == 404


# --- copies being made -------------------------------------------------------------------------


def test_copies_being_made_belong_to_the_linked_plan(setup, user):
    other = Plan.objects.create(user=user, name="Q")
    PlanLine.objects.create(plan=other, type_id=RIFTER, quantity=3)
    copying = job(20, activity=5, product=None, runs=3)  # 3 copies...
    IndustryJob.objects.filter(pk=20).update(licensed_runs=1)  # ...of 1 run each
    link = JobLink.objects.create(user=user, plan=setup, job=copying, source="manual")

    def sources(p):
        result = reservation.run_plans(user)[p.pk].result
        return sorted(str(j.source) for j in result.jobs if j.activity == "manufacturing")

    assert sources(setup) == ["bpc", "bpc", "bpc"]  # one job per copy, usable when it ends
    assert sources(other) == ["missing"]  # the copies are for plan P
    # The tracker's base run leaves them out, so copy jobs stay matchable.
    base = tracker.base_result(setup, inputs.load(user))
    assert [str(j.source) for j in base.jobs] == ["missing"]

    link.plan = None  # unlinked by hand: any plan may use the copies
    link.save()
    assert sources(other) == ["bpc", "bpc", "bpc"]
