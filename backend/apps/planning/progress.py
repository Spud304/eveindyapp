"""A plan's progress: its jobs per blueprint and activity, and the jobs offered for linking.

Used by the owner's Progress tab and by shared views, so it lives apart from the API."""

from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.esidata.access import owner_q
from apps.esidata.models import Feed, IndustryJob
from apps.esidata.overview_api import describe_jobs
from apps.sde.models import EveType
from engine.types import Activity, GameData, PlanResult

from . import tracker
from .inputs import AccountData
from .models import JobLink, Plan
from .reservation import PlanRun

CANDIDATE_DAYS = 30


def progress_data(
    user: User,
    p: Plan,
    data: AccountData,
    run: PlanRun,
    candidates: bool,
    base: PlanResult | None = None,
) -> dict:
    """Progress rows and linked jobs for a plan of `user`; `candidates` adds the unlinked
    recent jobs offered for linking (owner only). `base`: the tracker's base result, when the
    caller already has it."""
    base = base or tracker.base_result(p, data)
    keys = tracker.plan_keys(base) if base else set()
    now = timezone.now()

    links = list(
        JobLink.objects.filter(user=user, plan=p).select_related("job").order_by("job__start_date")
    )
    linked_jobs = [ln.job for ln in links]
    rows_by_job = {r["job_id"]: r for r in describe_jobs(user, linked_jobs, now)}

    remaining: dict[tuple[int, str], int] = {}
    over: dict[int, int] = {}
    if run.result:
        for j in run.result.jobs:
            key = (j.blueprint_type_id, j.activity.value)
            remaining[key] = remaining.get(key, 0) + j.runs * max(j.copies, 1)
        over = {i.type_id: i.over_plan for i in run.result.items if i.over_plan}
    products = _products(data.game, keys)
    names = dict(
        EveType.objects.filter(
            pk__in={bp for bp, _ in keys}
            | set(products.values())
            | {j.product_type_id for j in linked_jobs if j.product_type_id}
        ).values_list("id", "name")
    )
    counts: dict[tuple[int, str], dict[str, int]] = {}
    for job in linked_jobs:
        activity = tracker.JOB_ACTIVITY.get(job.activity_id)
        if activity is None:
            continue
        status = rows_by_job[job.job_id]["status"]
        c = counts.setdefault(
            (job.blueprint_type_id, activity.value), {"running": 0, "ready": 0, "delivered": 0}
        )
        if status in ("active", "paused"):
            c["running"] += job.runs
        elif status in c:
            c[status] += job.runs
    rows = []
    for bp_id, activity in sorted(
        keys | {(k[0], Activity(k[1])) for k in counts}, key=lambda k: names.get(k[0], "")
    ):
        key = (bp_id, activity.value)
        c = counts.get(key, {"running": 0, "ready": 0, "delivered": 0})
        product = products.get(key)
        rows.append(
            {
                "blueprint_type_id": bp_id,
                "activity": activity.value,
                "name": names.get(bp_id, str(bp_id)),
                "product_name": names.get(product, "") if product else "",
                "remaining_runs": remaining.get(key, 0),
                "running_runs": c["running"],
                "ready_runs": c["ready"],
                "delivered_runs": c["delivered"],
                "over_plan": over.get(product, 0) if product else 0,
            }
        )

    out = {
        "active": p.is_active,
        "activated_at": p.activated_at,
        "rows": rows,
        "jobs": [{**rows_by_job[ln.job_id], "source": ln.source} for ln in links],
        "candidates": [],
    }
    if not candidates:
        return out
    linked_ids = JobLink.objects.filter(user=user, plan__isnull=False).values("job_id")
    since = now - timedelta(days=CANDIDATE_DAYS)
    offered = [
        j
        for j in IndustryJob.objects.filter(owner_q(user, Feed.JOBS), start_date__gte=since)
        .exclude(status__in=tracker.DEAD)
        .exclude(pk__in=linked_ids)
        .order_by("-start_date")
        if (j.blueprint_type_id, tracker.JOB_ACTIVITY.get(j.activity_id)) in keys
    ]
    out["candidates"] = describe_jobs(user, offered[:100], now)
    return out


def _products(game: GameData, keys) -> dict[tuple[int, str], int]:
    out = {}
    for bp_id, activity in keys:
        bp = game.blueprints.get(bp_id)
        if bp is None:
            continue
        recipe = {
            Activity.MANUFACTURING: bp.manufacturing,
            Activity.REACTION: bp.reaction,
        }.get(activity)
        if recipe and recipe.product_type_id:
            out[(bp_id, activity.value)] = recipe.product_type_id
    return out
