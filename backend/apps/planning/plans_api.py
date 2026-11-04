"""Plans: CRUD, lines, active plan, and the computed result with reservations."""

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Literal, cast

from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Field, Router, Schema, Status
from ninja.errors import HttpError

from apps.accounts.models import User
from apps.esidata.access import owner_q
from apps.esidata.models import BlueprintItem, Feed, IndustryJob
from apps.esidata.overview_api import JobRow, describe_jobs
from apps.sde.models import BlueprintProduct, EveType
from engine import BlueprintOptions, purchase_options
from engine.types import Activity, BuildCategory, PlanResult

from . import reservation, sharing, tracker
from .models import JobLink, LinkSource, Plan, PlanLine, Visibility
from .prices import jita_priced

router = Router(tags=["plans"])


class LineIO(Schema):
    type_id: int
    quantity: int = Field(..., ge=1, le=10_000_000)
    # Owned BPCs to run for this line; the server then sets `quantity` from their runs.
    blueprint_item_ids: list[int] = []


class LineOut(LineIO):
    id: int
    name: str


class ChoiceIO(Schema):
    me: int | None = Field(None, ge=-10, le=10)
    te: int | None = Field(None, ge=0, le=20)
    decryptor: int | Literal["auto", "none"] = "auto"
    # Opt-in purchases (engine.types.BlueprintChoice).
    buy_bpcs: int = Field(0, ge=0, le=100)
    bpc_runs: int | None = Field(None, ge=1, le=100_000)
    bpc_me: int = Field(10, ge=0, le=10)
    bpc_te: int = Field(20, ge=0, le=20)
    bpc_price: float | None = Field(None, ge=0)
    extra_bpos: int = Field(0, ge=0, le=20)
    bpo_me: int = Field(0, ge=0, le=10)
    bpo_te: int = Field(0, ge=0, le=20)


class PlanSettings(Schema):
    name: str | None = Field(None, min_length=1, max_length=100)
    reserve_assets: bool | None = None
    priority: int | None = None
    visibility: Visibility | None = None
    blacklist_add: list[int] | None = None
    blacklist_remove: list[int] | None = None
    category_overrides: dict[BuildCategory, Literal["buy", "build"]] | None = None
    choices: dict[int, ChoiceIO] | None = None
    station_ids: list[int] | None = None
    extra_location_ids: list[int] | None = None
    hangar_flags: list[str] | None = None
    share_corporation_id: int | None = None


class PlanCreate(Schema):
    name: str = Field(..., min_length=1, max_length=100)
    lines: list[LineIO] = []
    reserve_assets: bool = False
    priority: int = 100


class PlanSummary(Schema):
    id: int
    name: str
    is_active: bool
    reserve_assets: bool
    priority: int
    visibility: str
    line_count: int
    updated_at: datetime


class PlanOut(PlanSummary):
    activated_at: datetime | None
    lines: list[LineOut]
    blacklist_add: list[int]
    blacklist_remove: list[int]
    category_overrides: dict[str, str]
    choices: dict[str, dict]
    station_ids: list[int]
    extra_location_ids: list[int]
    hangar_flags: list[str]
    share_token: str | None  # link visibility: the plan is at /shared/<share_token>
    share_corporation_id: int | None  # corp visibility: None means the owner's main's corp


def _user(request: HttpRequest) -> User:
    return cast(User, request.user)


def _plan(request: HttpRequest, plan_id: int) -> Plan:
    return get_object_or_404(Plan, pk=plan_id, user=_user(request))


def _summary(p: Plan) -> dict:
    return {
        "id": p.pk,
        "name": p.name,
        "is_active": p.is_active,
        "reserve_assets": p.reserve_assets,
        "priority": p.priority,
        "visibility": p.visibility,
        "line_count": p.lines.count(),
        "updated_at": p.updated_at,
    }


def _out(p: Plan) -> dict:
    lines = list(p.lines.all())
    names = dict(
        EveType.objects.filter(pk__in=[ln.type_id for ln in lines]).values_list("id", "name")
    )
    return {
        **_summary(p),
        "activated_at": p.activated_at,
        "lines": [
            {
                "id": ln.pk,
                "type_id": ln.type_id,
                "quantity": ln.quantity,
                "blueprint_item_ids": ln.blueprint_item_ids,
                "name": names.get(ln.type_id, ""),
            }
            for ln in lines
        ],
        "blacklist_add": p.blacklist_add,
        "blacklist_remove": p.blacklist_remove,
        "category_overrides": p.category_overrides,
        "choices": p.choices,
        "station_ids": p.station_ids,
        "extra_location_ids": p.extra_location_ids,
        "hangar_flags": p.hangar_flags,
        "share_token": p.share_token,
        "share_corporation_id": p.share_corporation_id,
    }


def _check_types(type_ids: list[int]) -> None:
    found = set(EveType.objects.filter(pk__in=type_ids, removed=False).values_list("id", flat=True))
    missing = sorted(set(type_ids) - found)
    if missing:
        raise HttpError(422, f"unknown type ids: {missing}")


def _picked_quantity(p: Plan, ln: LineIO, taken: set[int]) -> int:
    """Validate the BPCs picked for a line and return the units they make: copies the account
    holds, of one blueprint that manufactures the line's item, not picked twice in this plan
    and not picked in another plan."""
    ids = ln.blueprint_item_ids
    if len(set(ids)) != len(ids) or taken & set(ids):
        raise HttpError(422, "a BPC is picked twice in this plan")
    taken.update(ids)
    items = {
        b.item_id: b
        for b in BlueprintItem.objects.filter(owner_q(p.user, Feed.BLUEPRINTS), item_id__in=ids)
    }
    missing = [i for i in ids if i not in items]
    if missing:
        raise HttpError(422, f"blueprints not found in your library: {missing}")
    if any(b.quantity != -2 for b in items.values()):
        raise HttpError(422, "only copies (BPCs) can be picked for a line")
    bp_types = {b.type_id for b in items.values()}
    if len(bp_types) != 1:
        raise HttpError(422, "BPCs picked for one line must be of one blueprint")
    product = BlueprintProduct.objects.filter(
        activity__blueprint_id=bp_types.pop(), activity__activity="manufacturing"
    ).first()
    if product is None or product.type_id != ln.type_id:
        raise HttpError(422, "the picked BPCs do not manufacture this line's item")
    elsewhere = [
        other
        for other in PlanLine.objects.filter(plan__user=p.user)
        .exclude(plan=p)
        .exclude(blueprint_item_ids=[])
        .select_related("plan")
        if set(other.blueprint_item_ids) & set(ids)
    ]
    if elsewhere:
        raise HttpError(409, f"a picked BPC is already in plan {elsewhere[0].plan.name}")
    return sum(items[i].runs for i in ids) * product.quantity


def _set_lines(p: Plan, lines: list[LineIO]) -> None:
    _check_types([ln.type_id for ln in lines])
    taken: set[int] = set()
    rows = []
    for i, ln in enumerate(lines):
        qty = _picked_quantity(p, ln, taken) if ln.blueprint_item_ids else ln.quantity
        rows.append(
            PlanLine(
                plan=p,
                type_id=ln.type_id,
                quantity=qty,
                position=i,
                blueprint_item_ids=ln.blueprint_item_ids,
            )
        )
    p.lines.all().delete()
    PlanLine.objects.bulk_create(rows)


class SharedSummary(Schema):
    id: int
    name: str
    owner_name: str
    updated_at: datetime


class CorporationOption(Schema):
    id: int
    name: str


@router.get("/plans/shared-with-me", response=list[SharedSummary])
def shared_with_me(request: HttpRequest):
    """Other accounts' plans shared with one of your corporations."""
    return [
        {"id": p.pk, "name": p.name, "owner_name": p.user.display_name, "updated_at": p.updated_at}
        for p in sharing.corp_plans(_user(request))
    ]


# Before "/plans/{plan_id}": ninja matches the path before checking that the id is a number.
@router.get("/plans/corporations", response=list[CorporationOption])
def plan_corporations(request: HttpRequest):
    """Corporations your characters are in: who corp visibility can share with."""
    return sharing.corporation_options(_user(request))


@router.get("/plans", response=list[PlanSummary])
def list_plans(request: HttpRequest):
    return [_summary(p) for p in _user(request).plans.all()]


@router.post("/plans", response={201: PlanOut})
def create_plan(request: HttpRequest, body: PlanCreate):
    with transaction.atomic():
        p = Plan.objects.create(
            user=_user(request),
            name=body.name,
            reserve_assets=body.reserve_assets,
            priority=body.priority,
        )
        _set_lines(p, body.lines)
    return Status(201, _out(p))


@router.get("/plans/{plan_id}", response=PlanOut)
def get_plan(request: HttpRequest, plan_id: int):
    return _out(_plan(request, plan_id))


@router.patch("/plans/{plan_id}", response=PlanOut)
def edit_plan(request: HttpRequest, plan_id: int, body: PlanSettings):
    p = _plan(request, plan_id)
    data = body.dict(exclude_unset=True)
    if "station_ids" in data:
        own = set(_user(request).stations.values_list("id", flat=True))
        bad = sorted(set(data["station_ids"]) - own)
        if bad:
            raise HttpError(422, f"not your stations: {bad}")
    if "category_overrides" in data:
        data["category_overrides"] = {
            BuildCategory(k).value: v for k, v in data["category_overrides"].items()
        }
    if "choices" in data:
        data["choices"] = {str(k): v for k, v in data["choices"].items()}
    corp = data.get("share_corporation_id")
    if corp is not None and corp not in sharing.owner_corporations(_user(request)):
        raise HttpError(422, "none of your characters is in that corporation")
    if data.get("visibility") == Visibility.LINK and not p.share_token:
        data["share_token"] = sharing.new_token()
    for key in ("blacklist_add", "blacklist_remove"):
        if key in data:
            _check_types(data[key])
            data[key] = sorted(set(data[key]))
    for field, value in data.items():
        setattr(p, field, value)
    p.save()
    return _out(p)


@router.put("/plans/{plan_id}/lines", response=PlanOut)
def put_lines(request: HttpRequest, plan_id: int, lines: list[LineIO]):
    p = _plan(request, plan_id)
    with transaction.atomic():
        _set_lines(p, lines)
        p.save(update_fields=["updated_at"])
    return _out(p)


@router.post("/plans/{plan_id}/activate", response=PlanOut)
def activate(request: HttpRequest, plan_id: int):
    """Make this the account's one active plan; the tracker attributes new jobs to it."""
    p = _plan(request, plan_id)
    with transaction.atomic():
        Plan.objects.filter(user=p.user, is_active=True).exclude(pk=p.pk).update(is_active=False)
        if not p.is_active:
            p.is_active = True
            p.activated_at = timezone.now()
            p.save(update_fields=["is_active", "activated_at", "updated_at"])
    return _out(p)


@router.post("/plans/{plan_id}/deactivate", response=PlanOut)
def deactivate(request: HttpRequest, plan_id: int):
    p = _plan(request, plan_id)
    p.is_active = False
    p.save(update_fields=["is_active", "updated_at"])
    return _out(p)


@router.delete("/plans/{plan_id}", response={204: None})
def delete_plan(request: HttpRequest, plan_id: int):
    _plan(request, plan_id).delete()
    return Status(204, None)


class RuleOverridesOut(Schema):
    blacklist_add: list[int]
    blacklist_remove: list[int]
    categories: dict[str, str]


class EffectiveRulesOut(Schema):
    item_blacklist: list[int]
    buy_categories: list[BuildCategory]
    overrides: RuleOverridesOut


class HolderOut(Schema):
    plan_id: int
    plan_name: str
    quantity: int


class ReservationOut(Schema):
    reserves: bool
    claims: dict[int, int]  # type id -> quantity this plan reserves
    held_elsewhere: dict[int, list[HolderOut]]  # type id -> earlier plans holding stock


class PlanResultOut(Schema):
    prices: Literal["jita", "average"] = "average"
    priced_at_average: int = 0  # shopping items whose Jita orders could not be fetched
    plan_id: int
    error: str
    result: PlanResult | None
    effective_rules: EffectiveRulesOut
    reservation: ReservationOut


@router.get("/plans/{plan_id}/result", response=PlanResultOut)
def plan_result(request: HttpRequest, plan_id: int, prices: Literal["jita", "average"] = "jita"):
    """The engine's result for this plan, with the assets other plans reserve. The shopping
    list and costs are priced from Jita 4-4 sell orders unless `prices=average`."""
    p = _plan(request, plan_id)
    run = reservation.run_plans(_user(request), [p])[p.pk]
    rules = run.rules
    result, failed = jita_priced(run.result) if prices == "jita" else (run.result, 0)
    return {
        "plan_id": p.pk,
        "error": run.error,
        "result": result,
        "prices": prices,
        "priced_at_average": failed,
        "effective_rules": {
            "item_blacklist": sorted(rules.item_blacklist) if rules else [],
            "buy_categories": sorted(rules.buy_categories) if rules else [],
            "overrides": {
                "blacklist_add": p.blacklist_add,
                "blacklist_remove": p.blacklist_remove,
                "categories": p.category_overrides,
            },
        },
        "reservation": {
            "reserves": p.reserve_assets,
            "claims": run.claims,
            "held_elsewhere": {t: [asdict(h) for h in hs] for t, hs in run.held_elsewhere.items()},
        },
    }


@router.get("/plans/{plan_id}/blueprints/{bp_id}/options", response=BlueprintOptions)
def blueprint_options(request: HttpRequest, plan_id: int, bp_id: int):
    """What buying BPCs or an extra BPO for one blueprint would save and cost: the plan run
    again with each purchase. One plan run per candidate, so only on request."""
    p = _plan(request, plan_id)
    run = reservation.run_plans(_user(request), [p])[p.pk]
    if run.input is None or run.result is None:
        raise HttpError(422, run.error or "the plan has no result")
    return purchase_options(run.input, bp_id, run.result)


# --- progress (step 5) ---------------------------------------------------------------------


class ProgressRow(Schema):
    """One blueprint and activity of the plan: what jobs are doing for it."""

    blueprint_type_id: int
    activity: str
    name: str
    product_name: str
    remaining_runs: int  # still to start, from the engine with progress applied
    running_runs: int
    ready_runs: int
    delivered_runs: int
    over_plan: int  # units of the product made beyond what the plan needs


class LinkedJob(JobRow):
    source: str  # auto | manual


class ProgressOut(Schema):
    active: bool
    activated_at: datetime | None
    rows: list[ProgressRow]
    jobs: list[LinkedJob]
    candidates: list[JobRow]  # recent jobs of this plan's blueprints that are not linked here


CANDIDATE_DAYS = 30


@router.get("/plans/{plan_id}/progress", response=ProgressOut)
def plan_progress(request: HttpRequest, plan_id: int):
    """Jobs linked to this plan, per blueprint, with what is left. Matching runs first, so
    jobs synced since the last match show up here."""
    user = _user(request)
    p = _plan(request, plan_id)
    data = reservation.load(user)
    if p.is_active:
        tracker.match(user, data)
    run = reservation.run_plans(user, [p], data)[p.pk]
    return progress_data(user, p, data, run, candidates=True)


def progress_data(user: User, p: Plan, data, run, candidates: bool) -> dict:
    """Progress rows and linked jobs for a plan of `user`; `candidates` adds the unlinked
    recent jobs offered for linking (owner only)."""
    base = tracker.base_result(p, data)
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

    if not candidates:
        return {
            "active": p.is_active,
            "activated_at": p.activated_at,
            "rows": rows,
            "jobs": [{**rows_by_job[ln.job_id], "source": ln.source} for ln in links],
            "candidates": [],
        }
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
    return {
        "active": p.is_active,
        "activated_at": p.activated_at,
        "rows": rows,
        "jobs": [{**rows_by_job[ln.job_id], "source": ln.source} for ln in links],
        "candidates": describe_jobs(user, offered[:100], now),
    }


def _products(game, keys) -> dict[tuple[int, str], int]:
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


@router.post("/plans/{plan_id}/jobs/{job_id}", response=ProgressOut)
def link_job(request: HttpRequest, plan_id: int, job_id: int):
    """Count a job toward this plan (moving it from another plan, or undoing an unlink)."""
    user = _user(request)
    p = _plan(request, plan_id)
    job = get_object_or_404(IndustryJob.objects.filter(owner_q(user, Feed.JOBS)), pk=job_id)
    JobLink.objects.update_or_create(
        user=user, job=job, defaults={"plan": p, "source": LinkSource.MANUAL}
    )
    return plan_progress(request, plan_id)


@router.delete("/plans/{plan_id}/jobs/{job_id}", response=ProgressOut)
def unlink_job(request: HttpRequest, plan_id: int, job_id: int):
    """Stop counting a job toward this plan. It is not matched again automatically."""
    user = _user(request)
    p = _plan(request, plan_id)
    link = get_object_or_404(JobLink, user=user, plan=p, job_id=job_id)
    link.plan = None
    link.source = LinkSource.MANUAL
    link.save(update_fields=["plan", "source", "updated_at"])
    return plan_progress(request, plan_id)


# --- sharing (step 7) ----------------------------------------------------------------------


class SharedLine(Schema):
    type_id: int
    name: str
    quantity: int


class SharedPlanOut(Schema):
    """A plan as a viewer sees it. Link viewers get aliases for stations and characters
    (`anonymized`), and `plan_id` / `owner_name` are left out."""

    plan_id: int | None
    name: str
    owner_name: str | None
    anonymized: bool
    lines: list[SharedLine]
    error: str
    result: PlanResult | None
    progress: ProgressOut
    stations: dict[int, str]
    characters: dict[int, str]


@router.get("/shared/{token}", auth=None, response=SharedPlanOut)
def shared_by_link(request: HttpRequest, token: str):
    """A plan shared by link: no login needed."""
    p = sharing.by_token(token)
    if p is None:
        raise HttpError(404, "no plan is shared with this link")
    return sharing.view(p, anonymize=True)


@router.get("/plans/{plan_id}/view", response=SharedPlanOut)
def view_plan(request: HttpRequest, plan_id: int):
    """The read-only view: for corp members of a corp-shared plan, and for the owner as a
    preview. Anyone else gets 404, so a plan's existence does not leak."""
    p = Plan.objects.filter(pk=plan_id).select_related("user__main_character").first()
    if p is None or not sharing.can_view(_user(request), p):
        raise HttpError(404, "Not Found")
    return sharing.view(p, anonymize=False)


@router.post("/plans/{plan_id}/share-link", response=PlanOut)
def new_share_link(request: HttpRequest, plan_id: int):
    """A new link for the plan; the old one stops working."""
    p = _plan(request, plan_id)
    p.share_token = sharing.new_token()
    p.save(update_fields=["share_token", "updated_at"])
    return _out(p)
