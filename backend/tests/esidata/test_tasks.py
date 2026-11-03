import pytest
from django.core.cache import cache
from django.core.management import call_command

from apps.accounts import services, sso
from apps.accounts.sso import SsoIdentity
from apps.core.locks import advisory_lock
from apps.esidata import sync, tasks
from apps.esidata.management.commands.sync_esi import _lock_key
from apps.esidata.models import Feed, FeedStatus

pytestmark = pytest.mark.django_db

MAIN, CORP = 90000001, 98000001


@pytest.fixture(autouse=True)
def clear():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    ch = services.upsert_character(SsoIdentity(MAIN, "Main", "o", ()), {"corporation_id": CORP})
    u = services.ensure_user(ch)
    services.store_tokens(ch, {"access_token": "a", "refresh_token": "r"}, ("publicData",))
    return u


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(
        sync,
        "sync_account",
        lambda user, client=None, feeds=None: seen.append((user.pk, feeds)) or [],
    )
    return seen


def test_enqueue_runs_task_and_releases_dedup(user, calls):
    assert tasks.enqueue_account_sync(user.pk) is True  # eager in tests: runs inline
    assert calls == [(user.pk, None)]
    assert not tasks.is_queued(user.pk)


def test_second_enqueue_is_skipped_while_one_is_queued(user, calls, monkeypatch):
    monkeypatch.setattr(tasks.sync_account_task, "delay", lambda uid: None)  # stays queued
    assert tasks.enqueue_account_sync(user.pk) is True
    assert tasks.is_queued(user.pk)
    assert tasks.enqueue_account_sync(user.pk) is False


def test_broker_failure_releases_dedup(user, monkeypatch):
    def down(uid):
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks.sync_account_task, "delay", down)
    with pytest.raises(ConnectionError):
        tasks.enqueue_account_sync(user.pk)
    assert not tasks.is_queued(user.pk)


def test_refresh_now_and_status_api(client, user, calls):
    client.force_login(user)
    FeedStatus.objects.create(
        owner_kind="character",
        owner_id=MAIN,
        feed=Feed.SKILLS,
        ok=True,
        rows=3,
        attempted_at="2026-11-03T00:00:00Z",
        fetched_at="2026-11-03T00:00:00Z",
    )
    FeedStatus.objects.create(
        owner_kind="character",
        owner_id=12345,
        feed=Feed.SKILLS,
        ok=True,
        attempted_at="2026-11-03T00:00:00Z",
    )
    resp = client.post("/api/sync")
    assert resp.status_code == 202 and resp.json() == {"queued": True}
    body = client.get("/api/sync/status").json()
    assert body["queued"] is False
    assert [(f["owner_id"], f["feed"], f["rows"]) for f in body["feeds"]] == [(MAIN, "skills", 3)]


def test_sync_api_requires_login(client):
    assert client.post("/api/sync").status_code == 401


def test_linking_a_character_queues_a_first_sync(
    client, user, calls, monkeypatch, settings, django_capture_on_commit_callbacks
):
    client.force_login(user)
    monkeypatch.setattr(sso, "build_authorize_url", lambda **kw: "https://sso.test")
    monkeypatch.setattr(
        sso,
        "exchange_code",
        lambda **kw: {"access_token": "t", "refresh_token": "r", "expires_in": 1200},
    )
    monkeypatch.setattr(
        sso, "validate_access_token", lambda t: SsoIdentity(MAIN, "Main", "o", ("publicData",))
    )
    monkeypatch.setattr(services, "fetch_affiliation", lambda cid: None)
    client.get("/auth/login", {"mode": "link"})
    state = client.session["sso"]["state"]
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.get("/auth/callback", {"state": state, "code": "c"})
    assert resp.status_code == 302
    assert calls == [(user.pk, None)]


def test_sync_account_feed_subset_keeps_roles(user, monkeypatch):
    seen = {}

    def fake_char(ch, feeds=sync.CHARACTER_FEEDS, client=None):
        seen["char"] = tuple(feeds)
        return []

    def fake_corp(corp_id, client=None, feeds=None):
        seen["corp"] = feeds
        return []

    monkeypatch.setattr(sync, "sync_character", fake_char)
    monkeypatch.setattr(sync, "sync_corporation", fake_corp)
    monkeypatch.setattr(sync, "refresh_affiliations", lambda chars, client: None)
    sync.sync_account(user, client=object(), feeds={Feed.JOBS})
    assert seen["char"] == (Feed.ROLES, Feed.JOBS)  # roles decide corp feed sources
    assert seen["corp"] == {Feed.JOBS}


def test_sync_esi_feeds_option(user, calls):
    call_command("sync_esi", "--all", "--feeds", "jobs")
    assert calls == [(user.pk, {Feed.JOBS})]


def test_sync_esi_rejects_unknown_feed():
    from django.core.management import CommandError

    with pytest.raises(CommandError):
        call_command("sync_esi", "--all", "--feeds", "wallets")


def test_sync_esi_skips_when_the_same_mode_is_running(user, calls, capsys):
    from django.db import connections

    other = connections.create_connection("default")
    try:
        with other.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", [_lock_key("accounts:jobs")])
        call_command("sync_esi", "--all", "--feeds", "jobs")
        assert calls == [] and "in progress" in capsys.readouterr().out
        call_command("sync_esi", "--all")  # a different mode still runs
        assert calls == [(user.pk, None)]
    finally:
        other.close()


def test_lock_keys_differ_by_mode():
    assert _lock_key("accounts:jobs") != _lock_key("accounts:all") != _lock_key("public")
    with advisory_lock(_lock_key("public")) as acquired:
        assert acquired
