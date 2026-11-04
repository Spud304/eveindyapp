"""How old, and how healthy, the ESI snapshots an account reads are.

One function for the plan page and the dashboard, so the two never disagree about whether
data is stale. A feed is a problem when its last sync failed, when it has never synced, or
when its last success is older than `STALE_AFTER`."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from apps.accounts.models import User

from .access import readable_corp_feeds
from .models import Corporation, Feed, FeedStatus, OwnerKind

# About three sync intervals of `deploy/crontab` (jobs every 10 minutes, the rest hourly), so
# one slow or skipped run is not reported, and a stopped scheduler is within a few hours.
STALE_AFTER = {
    Feed.JOBS: timedelta(minutes=30),
    Feed.SKILLS: timedelta(hours=3),
    Feed.ROLES: timedelta(hours=3),
    Feed.ASSETS: timedelta(hours=3),
    Feed.BLUEPRINTS: timedelta(hours=3),
    Feed.DIVISIONS: timedelta(hours=3),
}

# What a plan computes from: skills (time, slots, invention), assets, blueprints, jobs.
PLAN_FEEDS = (Feed.SKILLS, Feed.ASSETS, Feed.BLUEPRINTS, Feed.JOBS)
CHARACTER_ONLY = {Feed.SKILLS, Feed.ROLES}


@dataclass(frozen=True)
class FeedHealth:
    owner_kind: str
    owner_id: int
    owner_name: str
    feed: str
    ok: bool
    error: str
    fetched_at: datetime | None
    stale: bool

    @property
    def problem(self) -> bool:
        return not self.ok or self.stale

    def describe(self) -> str:
        label = Feed(self.feed).label.lower()
        if self.fetched_at is None and self.ok:
            return f"{self.owner_name} {label}: never synced."
        if not self.ok:
            return f"{self.owner_name} {label}: {self.error or 'last sync failed'}."
        return f"{self.owner_name} {label}: last synced {_ago(self.fetched_at)}."


def feed_health(user: User, feeds=PLAN_FEEDS) -> list[FeedHealth]:
    """Every feed in `feeds` the account reads: its characters' (those with an ESI token) and
    the corp feeds its roles allow."""
    owners: list[tuple[str, int, str, Feed]] = []
    for ch in user.characters.filter(esi_token__isnull=False).order_by("name"):
        owners += [(OwnerKind.CHARACTER, ch.character_id, ch.name, f) for f in feeds]
    corp_feeds = readable_corp_feeds(user)
    corp_names = dict(Corporation.objects.filter(pk__in=corp_feeds).values_list("id", "name"))
    for corp_id, readable in sorted(corp_feeds.items()):
        name = corp_names.get(corp_id) or f"Corporation {corp_id}"
        owners += [
            (OwnerKind.CORPORATION, corp_id, name, f)
            for f in feeds
            if f in readable and f not in CHARACTER_ONLY
        ]

    statuses = {
        (s.owner_kind, s.owner_id, s.feed): s
        for s in FeedStatus.objects.filter(
            owner_id__in={o[1] for o in owners}, feed__in=[f.value for f in feeds]
        )
    }
    now = timezone.now()
    out = []
    for kind, owner_id, name, feed in owners:
        s = statuses.get((kind, owner_id, feed.value))
        fetched = s.fetched_at if s else None
        out.append(
            FeedHealth(
                owner_kind=kind,
                owner_id=owner_id,
                owner_name=name,
                feed=feed.value,
                ok=s.ok if s else True,
                error=s.error if s else "",
                fetched_at=fetched,
                stale=fetched is None or now - fetched > STALE_AFTER[feed],
            )
        )
    return out


def oldest(health: list[FeedHealth]) -> datetime | None:
    """The oldest successful sync among these feeds; None if any has never synced."""
    times = [h.fetched_at for h in health]
    if not times or any(t is None for t in times):
        return None
    return min(times)


def _ago(t: datetime) -> str:
    seconds = (timezone.now() - t).total_seconds()
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 2 * 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"
