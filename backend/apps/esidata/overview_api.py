"""Read-only views over synced ESI data: the blueprint library and the dashboard."""

from datetime import datetime, timedelta
from typing import Literal, cast

from django.conf import settings
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema

from apps.accounts.models import EsiToken, User
from apps.sde.models import EveType
from engine import formulas
from engine.types import Activity
from engine.types import Character as EngineCharacter

from . import names
from .access import owner_q, readable_corp_feeds
from .models import BlueprintItem, CharacterSkill, CorpDivision, Feed, FeedStatus, IndustryJob

router = Router(tags=["overview"])

ACTIVITY_NAMES = {
    1: "manufacturing",
    3: "research_time",
    4: "research_material",
    5: "copying",
    8: "invention",
    9: "reaction",
}  # [client]
SLOT_KIND = {
    1: "manufacturing",
    9: "reaction",
    3: "science",
    4: "science",
    5: "science",
    8: "science",
}
OPEN_STATUSES = ("active", "paused", "ready")


def _user(request: HttpRequest) -> User:
    return cast(User, request.user)


def _location_names(user: User, ids: set[int]) -> dict[int, str]:
    """The account's own station names first, then ESI for NPC stations."""
    out = {
        loc: name
        for loc, name in user.stations.exclude(location_id=None).values_list("location_id", "name")
        if loc in ids
    }
    out.update(names.resolve(i for i in ids if i not in out))
    return out


def _divisions(user: User) -> dict[tuple[int, str], str]:
    """(corp id, 'CorpSAG3') -> division name, for corps the account may read."""
    corps = list(readable_corp_feeds(user))
    return {
        (corp, f"CorpSAG{division}"): name
        for corp, division, name in CorpDivision.objects.filter(
            corporation_id__in=corps
        ).values_list("corporation_id", "division", "name")
    }


# --- library -----------------------------------------------------------------------------


class BlueprintRow(Schema):
    item_id: int
    type_id: int
    name: str
    kind: Literal["bpo", "bpc", "stack"]  # stack: N unresearched originals
    quantity: int  # originals in a stack; 1 otherwise
    runs: int  # remaining runs on a copy; -1 for originals
    me: int
    te: int
    owner_kind: str
    owner_id: int
    owner_name: str
    location_id: int
    location_name: str
    hangar: str  # division name, or the hangar flag


@router.get("/library/blueprints", response=list[BlueprintRow])
def library(request: HttpRequest):
    """Every blueprint the account's characters and readable corps hold."""
    user = _user(request)
    rows = list(BlueprintItem.objects.filter(owner_q(user, Feed.BLUEPRINTS)))
    type_names = dict(
        EveType.objects.filter(pk__in={b.type_id for b in rows}).values_list("id", "name")
    )
    owners = names.resolve({b.owner_id for b in rows})
    locations = _location_names(user, {b.root_location_id for b in rows})
    divisions = _divisions(user)
    out = []
    for b in rows:
        kind = "bpc" if b.quantity == -2 else ("stack" if b.quantity > 0 else "bpo")
        out.append(
            {
                "item_id": b.item_id,
                "type_id": b.type_id,
                "name": type_names.get(b.type_id, f"Type {b.type_id}"),
                "kind": kind,
                "quantity": b.quantity if b.quantity > 0 else 1,
                "runs": b.runs,
                "me": b.material_efficiency,
                "te": b.time_efficiency,
                "owner_kind": b.owner_kind,
                "owner_id": b.owner_id,
                "owner_name": owners.get(b.owner_id, str(b.owner_id)),
                "location_id": b.root_location_id,
                "location_name": locations.get(
                    b.root_location_id, f"Structure {b.root_location_id}"
                ),
                "hangar": divisions.get((b.owner_id, b.hangar_flag), b.hangar_flag),
            }
        )
    out.sort(key=lambda r: (r["name"], r["kind"], -r["me"]))
    return out


# --- dashboard ---------------------------------------------------------------------------


class JobRow(Schema):
    job_id: int
    activity: str
    status: str  # ESI status, with "active" past its end date shown as "ready"
    blueprint_type_id: int
    blueprint_name: str
    product_type_id: int | None
    product_name: str | None
    runs: int
    installer_id: int
    installer_name: str
    mine: bool  # installed by one of the account's characters
    owner_kind: str
    facility_id: int
    facility_name: str
    start_date: datetime
    end_date: datetime


class SlotUse(Schema):
    kind: Literal["manufacturing", "science", "reaction"]
    max: int  # from skills
    running: int  # active or paused jobs installed by this character
    ready: (
        int  # finished, not yet delivered (shown apart: whether they hold a slot is not confirmed)
    )


class CharacterSlots(Schema):
    character_id: int
    name: str
    skills_known: bool
    slots: list[SlotUse]


class Problem(Schema):
    severity: Literal["bad", "warn"]
    text: str
    where: Literal["setup", "station"]


class DashboardOut(Schema):
    jobs: list[JobRow]
    characters: list[CharacterSlots]
    problems: list[Problem]


def _effective_status(job: IndustryJob, now: datetime) -> str:
    """The client calls an installed job past its end date "ready" (industryCommon.JobStatus);
    ESI's status can lag until the next sync."""
    if job.status == "active" and job.end_date <= now:
        return "ready"
    return job.status


def describe_jobs(user: User, jobs: list[IndustryJob], now: datetime) -> list[dict]:
    """JobRow dicts with names and the effective status, for the dashboard and plan progress."""
    type_names = dict(
        EveType.objects.filter(
            pk__in={j.blueprint_type_id for j in jobs}
            | {j.product_type_id for j in jobs if j.product_type_id}
        ).values_list("id", "name")
    )
    people = names.resolve({j.installer_id for j in jobs})
    own = set()
    for c in user.characters.all():
        people[c.character_id] = c.name
        own.add(c.character_id)
    facilities = _location_names(user, {j.facility_id for j in jobs})
    return [
        {
            "job_id": j.job_id,
            "activity": ACTIVITY_NAMES.get(j.activity_id, str(j.activity_id)),
            "status": _effective_status(j, now),
            "blueprint_type_id": j.blueprint_type_id,
            "blueprint_name": type_names.get(j.blueprint_type_id, str(j.blueprint_type_id)),
            "product_type_id": j.product_type_id,
            "product_name": type_names.get(j.product_type_id) if j.product_type_id else None,
            "runs": j.runs,
            "installer_id": j.installer_id,
            "installer_name": people.get(j.installer_id, str(j.installer_id)),
            "mine": j.installer_id in own,
            "owner_kind": j.owner_kind,
            "facility_id": j.facility_id,
            "facility_name": facilities.get(j.facility_id, f"Structure {j.facility_id}"),
            "start_date": j.start_date,
            "end_date": j.end_date,
        }
        for j in jobs
    ]


@router.get("/dashboard", response=DashboardOut)
def dashboard(request: HttpRequest):
    user = _user(request)
    now = timezone.now()
    own = set(user.characters.values_list("character_id", flat=True))
    q = owner_q(user, Feed.JOBS)
    jobs = list(
        IndustryJob.objects.filter(q, status__in=OPEN_STATUSES).order_by("end_date")
        | IndustryJob.objects.filter(
            q, status="delivered", completed_date__gte=now - timedelta(days=1)
        )
    )
    job_rows = describe_jobs(user, sorted(jobs, key=lambda j: j.end_date), now)

    skills: dict[int, dict[int, int]] = {}
    for cid, sid, level in CharacterSkill.objects.filter(character__user=user).values_list(
        "character_id", "skill_id", "active_level"
    ):
        skills.setdefault(cid, {})[sid] = level
    characters = []
    for c in user.characters.order_by("name"):
        sk = skills.get(c.character_id, {})
        eng = EngineCharacter(c.character_id, c.name, sk, frozenset(Activity))
        mine = [j for j in jobs if j.installer_id == c.character_id]
        slots = []
        for kind, activity in (
            ("manufacturing", Activity.MANUFACTURING),
            ("science", Activity.INVENTION),
            ("reaction", Activity.REACTION),
        ):
            of_kind = [j for j in mine if SLOT_KIND.get(j.activity_id) == kind]
            statuses = [_effective_status(j, now) for j in of_kind]
            slots.append(
                {
                    "kind": kind,
                    "max": formulas.slots(eng, activity),
                    "running": sum(s in ("active", "paused") for s in statuses),
                    "ready": sum(s == "ready" for s in statuses),
                }
            )
        characters.append(
            {
                "character_id": c.character_id,
                "name": c.name,
                "skills_known": bool(sk),
                "slots": slots,
            }
        )
    return {"jobs": job_rows, "characters": characters, "problems": _problems(user, own)}


def _problems(user: User, own: set[int]) -> list[dict]:
    out = []
    tokens = {t.character_id: t for t in EsiToken.objects.filter(character__user=user)}
    for c in user.characters.order_by("name"):
        t = tokens.get(c.character_id)
        if t is None:
            out.append(
                {
                    "severity": "warn",
                    "text": f"{c.name} has not granted ESI access; link it in Setup.",
                    "where": "setup",
                }
            )
        elif t.refresh_failed_at:
            out.append(
                {
                    "severity": "bad",
                    "text": f"{c.name}'s ESI token was rejected; link it again.",
                    "where": "setup",
                }
            )
        elif missing := sorted(set(settings.EVE_CHARACTER_SCOPES) - set(t.scopes)):
            out.append(
                {
                    "severity": "warn",
                    "text": f"{c.name} is missing {len(missing)} ESI scopes; link it again.",
                    "where": "setup",
                }
            )
    corps = set(
        user.characters.exclude(corporation_id=None).values_list("corporation_id", flat=True)
    )
    for s in FeedStatus.objects.filter(ok=False).filter(
        owner_q(user, Feed.SKILLS) | owner_q(user, Feed.ASSETS) | _corp_q(corps)
    ):
        out.append(
            {
                "severity": "bad",
                "text": f"{s.owner_kind} {s.owner_id} {s.feed}: {s.error}",
                "where": "setup",
            }
        )
    # One line per station, so a fresh discovery does not bury the account problems above.
    for st in user.stations.filter(enabled=True):
        gaps = []
        if not st.tax_confirmed:
            gaps.append(f"tax not set (fees assume {st.facility_tax}%)")
        if st.structure_type_id and not st.rig_type_ids:
            gaps.append("no rigs entered")
        if not st.activities:
            gaps.append("no activities on, so plans never use it")
        if gaps:
            out.append(
                {"severity": "warn", "text": f"{st.name}: {'; '.join(gaps)}.", "where": "station"}
            )
    return out


def _corp_q(corps: set[int]):
    return Q(owner_kind="corporation", owner_id__in=corps)
