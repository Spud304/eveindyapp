from datetime import datetime

from django.conf import settings
from django.db import connection
from django.http import HttpRequest
from ninja import Router, Schema

from apps.sde.health import latest_build_summary

router = Router(tags=["core"])


class HealthOut(Schema):
    status: str
    version: str
    database: str
    sde_build: int | None = None
    sde_release_date: datetime | None = None
    sde_imported_at: datetime | None = None
    sde_stale: bool = True


@router.get("/health", auth=None, response=HealthOut)
def health(request: HttpRequest):
    database = "ok"
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:  # pragma: no cover - only on a broken deployment
        database = "error"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "version": settings.APP_VERSION,
        "database": database,
        **latest_build_summary(),
    }
