"""On-demand sync tasks. A queued sync for an account blocks another one for
`SYNC_DEDUP_SECONDS` (or until it finishes), so repeated "refresh now" clicks do not pile up."""

import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from apps.accounts.models import User
from apps.planning.tracker import match_after_sync

from . import sync

log = logging.getLogger(__name__)


def _dedup_key(user_id: int) -> str:
    return f"sync:account:{user_id}"


def is_queued(user_id: int) -> bool:
    return cache.get(_dedup_key(user_id)) is not None


def enqueue_account_sync(user_id: int) -> bool:
    """Queue a full sync for the account unless one is already queued or running."""
    if not cache.add(_dedup_key(user_id), 1, timeout=settings.SYNC_DEDUP_SECONDS):
        return False
    try:
        sync_account_task.delay(user_id)
    except Exception:
        cache.delete(_dedup_key(user_id))
        raise
    return True


@shared_task(name="esidata.sync_account")
def sync_account_task(user_id: int) -> None:
    try:
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            return
        statuses = sync.sync_account(user)
        failed = [f"{s.owner_kind}:{s.owner_id}:{s.feed}" for s in statuses if not s.ok]
        linked = match_after_sync(user)
        log.info(
            "account %s synced: %d feeds, failed %s, %d jobs linked",
            user_id,
            len(statuses),
            failed,
            linked,
        )
    finally:
        cache.delete(_dedup_key(user_id))
