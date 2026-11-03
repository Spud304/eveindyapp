from datetime import timedelta

import pytest
from django.db import connection, connections
from django.utils import timezone

from apps.core.locks import advisory_lock
from apps.sde.constants import SDE_IMPORT_LOCK_KEY
from apps.sde.models import SdeBuild, SdeRawRecord

pytestmark = pytest.mark.django_db


def test_health_without_build_is_stale(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["sde_build"] is None and body["sde_stale"] is True


def test_health_reports_fresh_build(client):
    SdeBuild.objects.create(build=1, imported_at=timezone.now())
    body = client.get("/api/health").json()
    assert body["sde_build"] == 1 and body["sde_stale"] is False


def test_health_stale_after_threshold_unless_checked_recently(client, settings):
    settings.SDE_STALE_DAYS = 10
    build = SdeBuild.objects.create(build=1, imported_at=timezone.now() - timedelta(days=30))
    assert client.get("/api/health").json()["sde_stale"] is True
    build.last_checked_at = timezone.now()
    build.save()
    assert client.get("/api/health").json()["sde_stale"] is False


@pytest.mark.skipif(connection.vendor != "postgresql", reason="advisory locks are Postgres-only")
def test_advisory_lock_excludes_other_sessions():
    other = connections.create_connection("default")
    try:
        with advisory_lock(SDE_IMPORT_LOCK_KEY) as acquired:
            assert acquired
            with other.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", [SDE_IMPORT_LOCK_KEY])
                assert cur.fetchone()[0] is False
        with other.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", [SDE_IMPORT_LOCK_KEY])
            assert cur.fetchone()[0] is True
            cur.execute("SELECT pg_advisory_unlock(%s)", [SDE_IMPORT_LOCK_KEY])
    finally:
        other.close()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="JSONB path lookups")
def test_raw_json_path_query():
    SdeRawRecord.objects.create(
        file="types", key="587", data={"name": {"en": "Rifter"}, "groupID": 25}, build=1
    )
    assert SdeRawRecord.objects.filter(file="types", data__name__en="Rifter").count() == 1
    assert SdeRawRecord.objects.filter(data__groupID=25).count() == 1
