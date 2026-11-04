"""Attribute ESI industry jobs to plans and turn the links into engine progress.

Matching (docs/redesign.md, Job tracking): while a plan is active, every job of the account
(its characters' and its readable corps') that started after the plan was activated, and
whose blueprint and activity appear in the plan, is linked to it. Jobs beyond what the plan
needs are linked too; the engine reports their output as over plan. A job unlinked by hand
keeps a link row with no plan, so it is never matched again. Links survive switching the
active plan.

Which blueprints "appear in the plan" comes from a run without progress and without assets,
so a blueprint whose runs are all started, or whose output is already in a hangar, still
matches.

Progress fed to the engine, per linked job (cancelled and reverted jobs count for nothing):
- manufacturing / reaction not yet delivered: its output units count toward the plan;
- delivered: only when the product is a plan line. Other delivered output is in a hangar and
  arrives through the next asset sync, so counting it here would count it twice;
- invention not yet delivered: its attempts count; delivered copies arrive as owned blueprints;
- copying: not fed here. The copies an open copy job is making reach the engine as owned
  blueprints usable when the job ends (`inputs.incoming_copies`), for the plan the job is
  linked to, or for every plan when it is linked to none; delivered copies arrive through the
  blueprint sync.
"""

import logging
from collections import defaultdict

from django.db import transaction

from apps.accounts.models import User
from apps.esidata.access import owner_q
from apps.esidata.models import Feed, IndustryJob
from engine import PlanError, plan
from engine.types import Activity, GameData, PlanResult

from . import inputs
from .models import JobLink, LinkSource, Plan

log = logging.getLogger(__name__)

JOB_ACTIVITY = {
    1: Activity.MANUFACTURING,
    5: Activity.COPYING,
    8: Activity.INVENTION,
    9: Activity.REACTION,
}
DEAD = ("cancelled", "reverted")
NOT_DELIVERED = ("active", "paused", "ready")


def plan_keys(base: PlanResult) -> set[tuple[int, Activity]]:
    """(blueprint type, activity) pairs the plan uses."""
    return {(j.blueprint_type_id, j.activity) for j in base.jobs}


def base_result(p: Plan, data: inputs.AccountData) -> PlanResult | None:
    """The plan with no progress, no stock and no copies in the making: every blueprint and
    activity it could need, so a new copy job still matches after copies are under way."""
    inp = inputs.plan_input(p, data, {}, incoming=False)
    if not inp.lines:
        return None
    try:
        return plan(inp)
    except PlanError:
        return None


def match(
    user: User, data: inputs.AccountData | None = None, base: PlanResult | None = None
) -> list[JobLink]:
    """Link new jobs to the account's active plan. Returns the links it created. `base`: the
    active plan's `base_result`, when the caller already has it."""
    active = Plan.objects.filter(user=user, is_active=True).prefetch_related("lines").first()
    if active is None or active.activated_at is None:
        return []
    data = data or inputs.load(user)
    base = base or base_result(active, data)
    if base is None:
        return []
    keys = plan_keys(base)
    seen = JobLink.objects.filter(user=user).values("job_id")
    jobs = (
        IndustryJob.objects.filter(owner_q(user, Feed.JOBS), start_date__gte=active.activated_at)
        .exclude(status__in=DEAD)
        .exclude(pk__in=seen)
        .order_by("start_date", "job_id")
    )
    created = []
    with transaction.atomic():
        for job in jobs:
            activity = JOB_ACTIVITY.get(job.activity_id)
            if activity and (job.blueprint_type_id, activity) in keys:
                created.append(JobLink(user=user, plan=active, job=job, source=LinkSource.AUTO))
        JobLink.objects.bulk_create(created, ignore_conflicts=True)
    if created:
        log.info("linked %d jobs to plan %s for account %s", len(created), active.pk, user.pk)
    return created


def progress_inputs(p: Plan, game: GameData) -> tuple[dict[int, int], dict[int, int]]:
    """(started units by item, started invention attempts by T2 blueprint) for the engine."""
    line_types = {ln.type_id for ln in p.lines.all()}
    started: dict[int, int] = defaultdict(int)
    attempts: dict[int, int] = defaultdict(int)
    for job in IndustryJob.objects.filter(links__plan=p).exclude(status__in=DEAD):
        activity = JOB_ACTIVITY.get(job.activity_id)
        bp = game.blueprints.get(job.blueprint_type_id)
        if activity in (Activity.MANUFACTURING, Activity.REACTION) and bp is not None:
            recipe = bp.manufacturing if activity == Activity.MANUFACTURING else bp.reaction
            if recipe is None or recipe.product_type_id is None:
                continue
            product = job.product_type_id or recipe.product_type_id
            if job.status in NOT_DELIVERED or product in line_types:
                started[product] += job.runs * (recipe.product_quantity or 1)
        elif activity == Activity.INVENTION and job.status in NOT_DELIVERED and job.product_type_id:
            attempts[job.product_type_id] += job.runs
    return dict(started), dict(attempts)


def unreadable_links(p: Plan) -> list[IndustryJob]:
    """Linked, still-counting jobs the account can no longer read (character unlinked, corp
    role or token lost). Their status no longer updates, yet they still count as started; the
    plan says so rather than dropping progress the user may want kept."""
    readable = IndustryJob.objects.filter(owner_q(p.user, Feed.JOBS)).values("job_id")
    return list(
        IndustryJob.objects.filter(links__plan=p)
        .exclude(status__in=DEAD)
        .exclude(job_id__in=readable)
    )


def match_after_sync(user: User) -> int:
    """Run after a sync that read jobs. Matching problems are logged, never raised: the sync
    itself succeeded and the next one retries."""
    try:
        return len(match(user))
    except Exception:
        log.exception("job matching failed for account %s", user.pk)
        return 0
