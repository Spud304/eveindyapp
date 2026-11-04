from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import EveCharacter
from apps.accounts.sso import SsoIdentity
from apps.esidata import names
from apps.esidata.freshness import PLAN_FEEDS, feed_health, oldest
from apps.esidata.models import CharacterRoles, Corporation, Feed, FeedStatus, OwnerKind

pytestmark = pytest.mark.django_db

MAIN, CORP, OTHER_CORP = 90000001, 98000001, 98000002


@pytest.fixture
def user(monkeypatch):
    monkeypatch.setattr(names, "resolve", lambda ids, client=None: {})
    ch = services.upsert_character(SsoIdentity(MAIN, "Main", "o", ()), {"corporation_id": CORP})
    u = services.ensure_user(ch)
    services.store_tokens(ch, {"access_token": "a", "refresh_token": "r"}, ("publicData",))
    CharacterRoles.objects.create(character_id=MAIN, corporation_id=CORP, roles=["Director"])
    Corporation.objects.create(id=CORP, name="Test Corp")
    return u


def status(kind, owner, feed, age=timedelta(minutes=5), ok=True, error=""):
    now = timezone.now()
    FeedStatus.objects.update_or_create(
        owner_kind=kind,
        owner_id=owner,
        feed=feed,
        defaults={
            "ok": ok,
            "error": error,
            "attempted_at": now,
            "fetched_at": now - age if age is not None else None,
        },
    )


def all_fresh():
    for f in PLAN_FEEDS:
        status(OwnerKind.CHARACTER, MAIN, f)
    for f in (Feed.ASSETS, Feed.BLUEPRINTS, Feed.JOBS):
        status(OwnerKind.CORPORATION, CORP, f)


def problems(user):
    return {(h.owner_name, h.feed): h for h in feed_health(user) if h.problem}


def test_covers_character_feeds_and_readable_corp_feeds(user):
    all_fresh()
    health = feed_health(user)
    assert {(h.owner_kind, h.feed) for h in health} == {
        *((OwnerKind.CHARACTER, f.value) for f in PLAN_FEEDS),
        (OwnerKind.CORPORATION, "assets"),
        (OwnerKind.CORPORATION, "blueprints"),
        (OwnerKind.CORPORATION, "jobs"),
    }
    assert problems(user) == {}
    assert oldest(health) is not None


def test_stale_failed_and_never_synced(user):
    all_fresh()
    status(OwnerKind.CORPORATION, CORP, Feed.JOBS, age=timedelta(minutes=45))  # limit 30 min
    status(OwnerKind.CORPORATION, CORP, Feed.ASSETS, age=timedelta(hours=2))  # limit 3 h
    status(OwnerKind.CHARACTER, MAIN, Feed.SKILLS, ok=False, error="HTTP 502")
    FeedStatus.objects.filter(owner_id=MAIN, feed=Feed.BLUEPRINTS).delete()
    p = problems(user)
    assert set(p) == {("Test Corp", "jobs"), ("Main", "skills"), ("Main", "blueprints")}
    assert p[("Test Corp", "jobs")].describe() == "Test Corp industry jobs: last synced 45 min ago."
    assert p[("Main", "skills")].describe() == "Main skills: HTTP 502."
    assert p[("Main", "blueprints")].describe() == "Main blueprints: never synced."
    assert oldest(feed_health(user)) is None


def test_corp_without_role_is_not_read(user):
    all_fresh()
    CharacterRoles.objects.filter(character_id=MAIN).update(roles=["Factory_Manager"])
    corp_feeds = {h.feed for h in feed_health(user) if h.owner_kind == OwnerKind.CORPORATION}
    assert corp_feeds == {"jobs"}


def test_dashboard_lists_stale_and_failed_feeds(client, user):
    all_fresh()
    status(OwnerKind.CORPORATION, CORP, Feed.ASSETS, age=timedelta(days=2))
    status(OwnerKind.CORPORATION, CORP, Feed.DIVISIONS, ok=False, error="HTTP 403")
    # A corp no character may read still reports why its feed failed.
    status(OwnerKind.CORPORATION, OTHER_CORP, Feed.JOBS, ok=False, error="no Director")
    alt = services.upsert_character(
        SsoIdentity(90000002, "Alt", "o", ()), {"corporation_id": OTHER_CORP}
    )
    EveCharacter.objects.filter(pk=alt.pk).update(user=user)
    client.force_login(user)
    problems = {p["text"]: p["severity"] for p in client.get("/api/dashboard").json()["problems"]}
    assert problems["Test Corp assets: last synced 2 days ago."] == "warn"
    assert problems["Test Corp hangar divisions: HTTP 403."] == "bad"
    assert problems[f"Corporation {OTHER_CORP} industry jobs: no Director"] == "bad"
