"""SDE build summary for /api/health."""

from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from .models import SdeBuild

_NO_BUILD = {
    "sde_build": None,
    "sde_release_date": None,
    "sde_imported_at": None,
    "sde_stale": True,
}


def latest_build_summary() -> dict:
    """Never raises: before migrations or on a broken DB it reports no build."""
    try:
        latest = SdeBuild.latest()
    except DatabaseError:
        return dict(_NO_BUILD)
    if latest is None:
        return dict(_NO_BUILD)
    freshest = max(latest.imported_at, latest.last_checked_at or latest.imported_at)
    stale = timezone.now() - freshest > timedelta(days=settings.SDE_STALE_DAYS)
    return {
        "sde_build": latest.build,
        "sde_release_date": latest.release_date,
        "sde_imported_at": latest.imported_at,
        "sde_stale": stale,
    }
