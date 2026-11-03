from datetime import datetime
from typing import cast

from django.db.models import Q
from django.http import HttpRequest
from ninja import Router, Schema, Status

from apps.accounts.models import User

from . import tasks
from .access import readable_corp_feeds
from .models import FeedStatus, OwnerKind

router = Router(tags=["sync"])


class QueuedOut(Schema):
    queued: bool  # false: a sync for this account is already queued or running


class FeedOut(Schema):
    owner_kind: str
    owner_id: int
    feed: str
    ok: bool
    error: str
    rows: int
    attempted_at: datetime
    fetched_at: datetime | None
    source_character_id: int | None


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
    feeds = FeedStatus.objects.filter(owners).order_by("owner_kind", "owner_id", "feed")
    return {"queued": tasks.is_queued(user.pk), "feeds": list(feeds)}
