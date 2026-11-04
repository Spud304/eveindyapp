from datetime import datetime
from typing import cast

from django.db.models import Q
from django.http import HttpRequest
from ninja import Router, Schema, Status

from apps.accounts.models import User

from . import tasks
from .access import readable_corp_feeds
from .models import Corporation, FeedStatus, OwnerKind

router = Router(tags=["sync"])


class QueuedOut(Schema):
    queued: bool  # false: a sync for this account is already queued or running


class FeedOut(Schema):
    owner_kind: str
    owner_id: int
    owner_name: str  # the character's or corporation's name
    feed: str
    ok: bool
    error: str
    rows: int
    attempted_at: datetime
    fetched_at: datetime | None
    source_character_id: int | None
    source_name: str | None  # corp feeds: the character whose token fetched it


class StatusOut(Schema):
    queued: bool
    feeds: list[FeedOut]


@router.post("/sync", response={202: QueuedOut})
def refresh_now(request: HttpRequest):
    """Queue a sync of every linked character and readable corp of this account."""
    return Status(202, {"queued": tasks.enqueue_account_sync(cast(User, request.user).pk)})


@router.get("/sync/status", response=StatusOut)
def sync_status(request: HttpRequest):
    user = cast(User, request.user)
    owners = Q(
        owner_kind=OwnerKind.CHARACTER,
        owner_id__in=user.characters.values("character_id"),
    )
    for corp_id in readable_corp_feeds(user):
        owners |= Q(owner_kind=OwnerKind.CORPORATION, owner_id=corp_id)
    feeds = list(
        FeedStatus.objects.filter(owners)
        .select_related("source_character")
        .order_by("owner_kind", "owner_id", "feed")
    )
    characters = dict(user.characters.values_list("character_id", "name"))
    corps = dict(
        Corporation.objects.filter(pk__in={f.owner_id for f in feeds}).values_list("id", "name")
    )

    def name(f: FeedStatus) -> str:
        if f.owner_kind == OwnerKind.CHARACTER:
            return characters.get(f.owner_id) or f"Character {f.owner_id}"
        return corps.get(f.owner_id) or f"Corporation {f.owner_id}"

    rows = [
        {
            **{k: getattr(f, k) for k in FeedOut.model_fields if hasattr(f, k)},
            "owner_name": name(f),
            "source_name": f.source_character.name if f.source_character else None,
        }
        for f in feeds
    ]
    # Characters by name, then corporations by name, each owner's feeds together.
    rows.sort(key=lambda r: (r["owner_kind"] != OwnerKind.CHARACTER, r["owner_name"], r["feed"]))
    return {"queued": tasks.is_queued(user.pk), "feeds": rows}
