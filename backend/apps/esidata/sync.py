"""Fetch ESI feeds into esidata tables.

Each feed is independent: a failure (missing scope, rejected token, ESI error) is recorded in
`FeedStatus` and the other feeds still run. Corp feeds use the first linked character in that
corp whose roles allow the route and whose token has the scope (see `CORP_FEEDS`).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts import tokens
from apps.accounts.models import EveCharacter, User
from apps.esi.client import EsiClient, EsiError, get_client

from .models import (
    Asset,
    BlueprintItem,
    CharacterRoles,
    CharacterSkill,
    CorpDivision,
    Corporation,
    Feed,
    FeedStatus,
    IndustryJob,
    MarketPrice,
    OwnerKind,
    SystemCostIndex,
)

log = logging.getLogger(__name__)

SCOPE = {
    "skills": "esi-skills.read_skills.v1",
    "roles": "esi-characters.read_corporation_roles.v1",
    "assets": "esi-assets.read_assets.v1",
    "blueprints": "esi-characters.read_blueprints.v1",
    "jobs": "esi-industry.read_character_jobs.v1",
    "corp_assets": "esi-assets.read_corporation_assets.v1",
    "corp_blueprints": "esi-corporations.read_blueprints.v1",
    "corp_jobs": "esi-industry.read_corporation_jobs.v1",
    "corp_divisions": "esi-corporations.read_divisions.v1",
}


@dataclass(frozen=True)
class CorpFeed:
    feed: Feed
    scope: str
    roles: tuple[str, ...]  # any one of these is enough


# In-game roles each corp route needs. [official: ESI route descriptions]
CORP_FEEDS = (
    CorpFeed(Feed.ASSETS, SCOPE["corp_assets"], ("Director",)),
    CorpFeed(Feed.BLUEPRINTS, SCOPE["corp_blueprints"], ("Director",)),
    CorpFeed(Feed.DIVISIONS, SCOPE["corp_divisions"], ("Director",)),
    CorpFeed(Feed.JOBS, SCOPE["corp_jobs"], ("Factory_Manager", "Director")),
)
CHARACTER_FEEDS = (Feed.SKILLS, Feed.ROLES, Feed.ASSETS, Feed.BLUEPRINTS, Feed.JOBS)


class FeedUnavailable(Exception):
    """No character can supply this feed (roles or scopes missing)."""


# --- status bookkeeping --------------------------------------------------------------------


def _record(
    kind: str,
    owner_id: int,
    feed: Feed,
    fetch: Callable[[], int],
    source: EveCharacter | None = None,
) -> FeedStatus:
    now = timezone.now()
    status, _ = FeedStatus.objects.get_or_create(
        owner_kind=kind, owner_id=owner_id, feed=feed, defaults={"attempted_at": now}
    )
    status.attempted_at = now
    status.source_character = source
    try:
        status.rows = fetch()
    except (EsiError, tokens.TokenUnavailable, FeedUnavailable) as exc:
        status.ok = False
        status.error = str(exc)[:300]
        log.warning("%s %s %s failed: %s", kind, owner_id, feed, exc)
    else:
        status.ok = True
        status.error = ""
        status.fetched_at = now
    status.save()
    return status


# --- location resolution -------------------------------------------------------------------


def resolve_locations(rows: list[dict]) -> dict[int, tuple[int, str]]:
    """item_id -> (root location, hangar flag) by walking up `location_id` through other
    items in the same snapshot (containers, ships, corp offices)."""
    by_item = {r["item_id"]: r for r in rows}
    out: dict[int, tuple[int, str]] = {}
    for row in rows:
        chain = [row]
        seen = {row["item_id"]}
        while chain[-1]["location_id"] in by_item and chain[-1]["location_id"] not in seen:
            parent = by_item[chain[-1]["location_id"]]
            seen.add(parent["item_id"])
            chain.append(parent)
        top = chain[-1]
        if top["location_flag"] == "OfficeFolder" and len(chain) > 1:
            # A corp office: the station is above it, the division flag is just below it.
            out[row["item_id"]] = (top["location_id"], chain[-2]["location_flag"])
        else:
            out[row["item_id"]] = (top["location_id"], top["location_flag"])
    return out


def _dt(value: str | None) -> datetime | None:
    return parse_datetime(value) if value else None


# --- writers -------------------------------------------------------------------------------


def _write_assets(kind: str, owner_id: int, rows: list[dict]) -> int:
    where = resolve_locations(rows)
    with transaction.atomic():
        Asset.objects.filter(owner_kind=kind, owner_id=owner_id).delete()
        Asset.objects.bulk_create(
            [
                Asset(
                    owner_kind=kind,
                    owner_id=owner_id,
                    item_id=r["item_id"],
                    type_id=r["type_id"],
                    quantity=r["quantity"],
                    location_id=r["location_id"],
                    location_type=r["location_type"],
                    location_flag=r["location_flag"],
                    is_singleton=r["is_singleton"],
                    is_blueprint_copy=r.get("is_blueprint_copy"),
                    root_location_id=where[r["item_id"]][0],
                    hangar_flag=where[r["item_id"]][1],
                )
                for r in rows
            ],
            batch_size=2000,
        )
    return len(rows)


def _write_blueprints(kind: str, owner_id: int, rows: list[dict]) -> int:
    # Blueprints sit in the same containers as assets; resolve through the asset snapshot.
    assets = list(
        Asset.objects.filter(owner_kind=kind, owner_id=owner_id).values(
            "item_id", "location_id", "location_flag"
        )
    )
    where = resolve_locations(
        assets + [{k: r[k] for k in ("item_id", "location_id", "location_flag")} for r in rows]
    )
    with transaction.atomic():
        BlueprintItem.objects.filter(owner_kind=kind, owner_id=owner_id).delete()
        BlueprintItem.objects.bulk_create(
            [
                BlueprintItem(
                    owner_kind=kind,
                    owner_id=owner_id,
                    item_id=r["item_id"],
                    type_id=r["type_id"],
                    location_id=r["location_id"],
                    location_flag=r["location_flag"],
                    quantity=r["quantity"],
                    runs=r["runs"],
                    material_efficiency=r["material_efficiency"],
                    time_efficiency=r["time_efficiency"],
                    root_location_id=where[r["item_id"]][0],
                    hangar_flag=where[r["item_id"]][1],
                )
                for r in rows
            ],
            batch_size=2000,
        )
    return len(rows)


def _write_jobs(kind: str, owner_id: int, rows: list[dict]) -> int:
    now = timezone.now()
    objs = [
        IndustryJob(
            job_id=r["job_id"],
            owner_kind=kind,
            owner_id=owner_id,
            installer_id=r["installer_id"],
            facility_id=r["facility_id"],
            location_id=r.get("station_id", r.get("location_id")),
            activity_id=r["activity_id"],
            blueprint_id=r["blueprint_id"],
            blueprint_type_id=r["blueprint_type_id"],
            blueprint_location_id=r["blueprint_location_id"],
            output_location_id=r["output_location_id"],
            product_type_id=r.get("product_type_id"),
            runs=r["runs"],
            licensed_runs=r.get("licensed_runs"),
            successful_runs=r.get("successful_runs"),
            probability=r.get("probability"),
            cost=r.get("cost"),
            status=r["status"],
            duration=r["duration"],
            start_date=_dt(r["start_date"]),
            end_date=_dt(r["end_date"]),
            pause_date=_dt(r.get("pause_date")),
            completed_date=_dt(r.get("completed_date")),
            completed_character_id=r.get("completed_character_id"),
            last_seen_at=now,
        )
        for r in rows
    ]
    fields = [f.name for f in IndustryJob._meta.fields if f.name != "job_id"]
    IndustryJob.objects.bulk_create(
        objs, update_conflicts=True, unique_fields=["job_id"], update_fields=fields, batch_size=1000
    )
    return len(objs)


# --- character feeds -----------------------------------------------------------------------


def sync_character(
    character: EveCharacter, feeds=CHARACTER_FEEDS, client: EsiClient | None = None
) -> list[FeedStatus]:
    client = client or get_client()
    cid = character.character_id
    kind = OwnerKind.CHARACTER

    def token(scope: str) -> str:
        return tokens.access_token(character, scope)

    def skills() -> int:
        body = client.request(
            "GET", f"/characters/{cid}/skills/", token=token(SCOPE["skills"]), character_id=cid
        )
        rows = body.get("skills", [])
        with transaction.atomic():
            CharacterSkill.objects.filter(character=character).delete()
            CharacterSkill.objects.bulk_create(
                [
                    CharacterSkill(
                        character=character,
                        skill_id=s["skill_id"],
                        active_level=s["active_skill_level"],
                        trained_level=s["trained_skill_level"],
                        skillpoints=s["skillpoints_in_skill"],
                    )
                    for s in rows
                ]
            )
        return len(rows)

    def roles() -> int:
        body = client.request(
            "GET", f"/characters/{cid}/roles/", token=token(SCOPE["roles"]), character_id=cid
        )
        CharacterRoles.objects.update_or_create(
            character=character,
            defaults={
                "corporation_id": character.corporation_id,
                "roles": body.get("roles", []),
                "roles_at_hq": body.get("roles_at_hq", []),
                "roles_at_base": body.get("roles_at_base", []),
                "roles_at_other": body.get("roles_at_other", []),
            },
        )
        return len(body.get("roles", []))

    def assets() -> int:
        rows = client.paged(
            f"/characters/{cid}/assets/", token=token(SCOPE["assets"]), character_id=cid
        )
        return _write_assets(kind, cid, rows)

    def blueprints() -> int:
        rows = client.paged(
            f"/characters/{cid}/blueprints/", token=token(SCOPE["blueprints"]), character_id=cid
        )
        return _write_blueprints(kind, cid, rows)

    def jobs() -> int:
        rows = client.request(
            "GET",
            f"/characters/{cid}/industry/jobs/",
            params={"include_completed": "true"},
            token=token(SCOPE["jobs"]),
            character_id=cid,
        )
        return _write_jobs(kind, cid, rows)

    fetchers = {
        Feed.SKILLS: skills,
        Feed.ROLES: roles,
        Feed.ASSETS: assets,  # before blueprints: blueprint locations resolve through assets
        Feed.BLUEPRINTS: blueprints,
        Feed.JOBS: jobs,
    }
    return [_record(kind, cid, f, fetchers[f]) for f in CHARACTER_FEEDS if f in feeds]


# --- corporation feeds ---------------------------------------------------------------------


def corp_source(corporation_id: int, feed: CorpFeed) -> EveCharacter:
    """A linked character in the corp whose last roles fetch allows `feed` and whose token has
    its scope. Roles must be from the same corp (a character that changed corp is skipped)."""
    candidates = EveCharacter.objects.filter(
        corporation_id=corporation_id,
        user__isnull=False,
        esi_token__isnull=False,
        esi_token__refresh_failed_at__isnull=True,
    ).select_related("roles", "esi_token")
    for ch in candidates.order_by("character_id"):
        r = getattr(ch, "roles", None)
        if r is None or r.corporation_id != corporation_id or not r.has(*feed.roles):
            continue
        if not ch.esi_token.has_scopes(feed.scope):
            continue
        return ch
    raise FeedUnavailable(
        f"no linked character in corp {corporation_id} has {' or '.join(feed.roles)} "
        f"and the {feed.scope} scope"
    )


def sync_corporation(corporation_id: int, client: EsiClient | None = None) -> list[FeedStatus]:
    client = client or get_client()
    kind = OwnerKind.CORPORATION
    _ensure_corporation(corporation_id, client)
    results = []
    for cf in CORP_FEEDS:
        try:
            source = corp_source(corporation_id, cf)
        except FeedUnavailable as exc:
            message = exc

            def unavailable(message=message) -> int:
                raise message

            results.append(_record(kind, corporation_id, cf.feed, unavailable))
            continue
        results.append(
            _record(
                kind,
                corporation_id,
                cf.feed,
                _corp_fetcher(cf, corporation_id, source, client),
                source=source,
            )
        )
    return results


def _corp_fetcher(cf: CorpFeed, corp_id: int, source: EveCharacter, client: EsiClient):
    def call() -> int:
        tok = tokens.access_token(source, cf.scope)
        cid = source.character_id
        if cf.feed == Feed.ASSETS:
            rows = client.paged(f"/corporations/{corp_id}/assets/", token=tok, character_id=cid)
            return _write_assets(OwnerKind.CORPORATION, corp_id, rows)
        if cf.feed == Feed.BLUEPRINTS:
            rows = client.paged(f"/corporations/{corp_id}/blueprints/", token=tok, character_id=cid)
            return _write_blueprints(OwnerKind.CORPORATION, corp_id, rows)
        if cf.feed == Feed.JOBS:
            rows = client.paged(
                f"/corporations/{corp_id}/industry/jobs/",
                token=tok,
                character_id=cid,
                params={"include_completed": "true"},
            )
            return _write_jobs(OwnerKind.CORPORATION, corp_id, rows)
        body = client.request(
            "GET", f"/corporations/{corp_id}/divisions/", token=tok, character_id=cid
        )
        corp = Corporation.objects.get(pk=corp_id)
        hangars = body.get("hangar", [])
        with transaction.atomic():
            CorpDivision.objects.filter(corporation=corp).delete()
            CorpDivision.objects.bulk_create(
                [
                    CorpDivision(corporation=corp, division=h["division"], name=h.get("name", ""))
                    for h in hangars
                ]
            )
        return len(hangars)

    return call


def _ensure_corporation(corporation_id: int, client: EsiClient) -> Corporation:
    corp, _ = Corporation.objects.get_or_create(pk=corporation_id)
    try:
        body = client.request("GET", f"/corporations/{corporation_id}/")
    except EsiError as exc:
        log.warning("corporation %s name lookup failed: %s", corporation_id, exc)
        return corp
    corp.name = body.get("name", corp.name)
    corp.ticker = body.get("ticker", corp.ticker)
    corp.save()
    return corp


# --- accounts and public data --------------------------------------------------------------


def refresh_affiliations(characters: list[EveCharacter], client: EsiClient) -> None:
    if not characters:
        return
    by_id = {
        r["character_id"]: r for r in client.affiliations([c.character_id for c in characters])
    }
    now = timezone.now()
    for ch in characters:
        row = by_id.get(ch.character_id)
        if row:
            ch.corporation_id = row.get("corporation_id")
            ch.alliance_id = row.get("alliance_id")
            ch.affiliation_checked_at = now
    EveCharacter.objects.bulk_update(
        characters, ["corporation_id", "alliance_id", "affiliation_checked_at"]
    )


def sync_account(user: User, client: EsiClient | None = None) -> list[FeedStatus]:
    """Every linked character of the account, then every corp they are in."""
    client = client or get_client()
    characters = list(user.characters.filter(esi_token__isnull=False))
    try:
        refresh_affiliations(characters, client)
    except EsiError as exc:
        log.warning("affiliation refresh failed: %s", exc)
    results = []
    for ch in characters:
        results.extend(sync_character(ch, client=client))
    for corp_id in sorted({c.corporation_id for c in characters if c.corporation_id}):
        results.extend(sync_corporation(corp_id, client=client))
    return results


def sync_public(client: EsiClient | None = None) -> dict[str, int]:
    """Adjusted / average prices and system cost indices (no token needed)."""
    client = client or get_client()
    now = timezone.now()
    prices = client.request("GET", "/markets/prices/")
    MarketPrice.objects.bulk_create(
        [
            MarketPrice(
                type_id=p["type_id"],
                adjusted_price=p.get("adjusted_price"),
                average_price=p.get("average_price"),
                updated_at=now,
            )
            for p in prices
        ],
        update_conflicts=True,
        unique_fields=["type_id"],
        update_fields=["adjusted_price", "average_price", "updated_at"],
        batch_size=2000,
    )
    systems = client.request("GET", "/industry/systems/")
    rows = [
        SystemCostIndex(
            system_id=s["solar_system_id"],
            activity=ci["activity"],
            cost_index=ci["cost_index"],
            updated_at=now,
        )
        for s in systems
        for ci in s.get("cost_indices", [])
    ]
    SystemCostIndex.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["system_id", "activity"],
        update_fields=["cost_index", "updated_at"],
        batch_size=2000,
    )
    return {"prices": len(prices), "cost_indices": len(rows)}
