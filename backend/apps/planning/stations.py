"""Find the account's stations from its synced jobs and assets, and turn them into engine stations.

Discovery adds:
- every structure or NPC station where the account's characters or readable corps have
  industry jobs (they are where you build);
- every structure holding the account's or a readable corp's assets (you build where your
  stuff is). NPC stations holding only assets are reported but not added: they are usually
  old storage.

Name, hull type and system come from ESI (`/universe/structures` needs docking access,
`/universe/stations` is public). Default activities are the ones seen in your jobs there,
plus what the hull or station services offer. Rigs and tax cannot be read for structures
your corp does not own, so they are left for you to set (`tax_confirmed` stays False).
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from apps.accounts import tokens
from apps.accounts.models import User
from apps.esi.client import EsiClient, EsiError, get_client
from apps.esidata.access import readable_corp_feeds
from apps.esidata.models import Asset, BlueprintItem, Feed, IndustryJob, OwnerKind
from apps.sde import gamedata
from apps.sde.models import EveType
from engine.types import Activity, Structure
from engine.types import Station as EngineStation

from .models import Station, StationSource

log = logging.getLogger(__name__)

STRUCTURE_SCOPE = "esi-universe.read_structures.v1"
JOB_ACTIVITY = {
    1: Activity.MANUFACTURING,
    5: Activity.COPYING,
    8: Activity.INVENTION,
    9: Activity.REACTION,
}  # [client: industry/const.py]
# What a hull offers once its service modules are fitted. [SDE group names]
HULL_ACTIVITIES = {
    1404: (Activity.MANUFACTURING, Activity.COPYING, Activity.INVENTION),  # Engineering Complex
    1406: (Activity.REACTION,),  # Refinery
}
# ESI /universe/stations service names (sic: "labratory"). [official: ESI OpenAPI]
NPC_SERVICE_ACTIVITIES = {
    "factory": (Activity.MANUFACTURING,),
    "labratory": (Activity.COPYING, Activity.INVENTION),
}


def is_structure(location_id: int) -> bool:
    return location_id >= 1_000_000_000_000


def is_npc_station(location_id: int) -> bool:
    return 60_000_000 <= location_id < 64_000_000


@dataclass
class DiscoveryResult:
    added: list[Station] = field(default_factory=list)
    already_known: list[int] = field(default_factory=list)
    unresolved: dict[int, str] = field(default_factory=dict)  # id -> why
    asset_only_npc: dict[int, int] = field(default_factory=dict)  # station id -> asset rows


def _owners(user: User) -> list[tuple[str, int]]:
    owners = [
        (OwnerKind.CHARACTER, cid) for cid in user.characters.values_list("character_id", flat=True)
    ]
    for corp_id, feeds in readable_corp_feeds(user).items():
        if Feed.ASSETS in feeds or Feed.JOBS in feeds:
            owners.append((OwnerKind.CORPORATION, corp_id))
    return owners


def _owner_filter(qs, owners):
    from django.db.models import Q

    q = Q(pk__in=[])
    for kind, oid in owners:
        q |= Q(owner_kind=kind, owner_id=oid)
    return qs.filter(q)


def discover(user: User, client: EsiClient | None = None) -> DiscoveryResult:
    client = client or get_client()
    owners = _owners(user)
    job_acts: dict[int, set[Activity]] = defaultdict(set)
    for facility, activity in _owner_filter(IndustryJob.objects.all(), owners).values_list(
        "facility_id", "activity_id"
    ):
        if activity in JOB_ACTIVITY:
            job_acts[facility].add(JOB_ACTIVITY[activity])
    asset_counts: dict[int, int] = defaultdict(int)
    for model in (Asset, BlueprintItem):
        for root in _owner_filter(model.objects.all(), owners).values_list(
            "root_location_id", flat=True
        ):
            asset_counts[root] += 1

    result = DiscoveryResult()
    known = set(user.stations.exclude(location_id=None).values_list("location_id", flat=True))
    candidates = set(job_acts) | {loc for loc in asset_counts if is_structure(loc)}
    for loc in sorted(asset_counts):
        if is_npc_station(loc) and loc not in job_acts:
            result.asset_only_npc[loc] = asset_counts[loc]

    for loc in sorted(candidates):
        if loc in known:
            result.already_known.append(loc)
            continue
        try:
            station = _resolve(user, loc, client)
        except LookupError as exc:
            result.unresolved[loc] = str(exc)
            continue
        station.activities = sorted(
            set(station.activities) | {a.value for a in job_acts.get(loc, ())}
        )
        station.save()
        result.added.append(station)
    return result


def _resolve(user: User, loc: int, client: EsiClient) -> Station:
    if is_npc_station(loc):
        try:
            body = client.request("GET", f"/universe/stations/{loc}/")
        except EsiError as exc:
            raise LookupError(f"ESI: {exc}") from exc
        acts = {a for s in body.get("services", []) for a in NPC_SERVICE_ACTIVITIES.get(s, ())}
        return Station(
            user=user,
            name=body.get("name", f"Station {loc}"),
            location_id=loc,
            system_id=body["system_id"],
            structure_type_id=None,
            activities=sorted(a.value for a in acts),
            source=StationSource.DISCOVERED,
        )
    if not is_structure(loc):
        raise LookupError("not a station or structure")
    errors = []
    for ch in user.characters.filter(
        esi_token__isnull=False, esi_token__refresh_failed_at__isnull=True
    ):
        try:
            tok = tokens.access_token(ch, STRUCTURE_SCOPE)
            body = client.request(
                "GET", f"/universe/structures/{loc}/", token=tok, character_id=ch.character_id
            )
        except (EsiError, tokens.TokenUnavailable) as exc:
            errors.append(f"{ch.name}: {exc}")
            continue
        group = (
            EveType.objects.filter(pk=body.get("type_id"))
            .values_list("group_id", flat=True)
            .first()
        )
        return Station(
            user=user,
            name=body.get("name", f"Structure {loc}"),
            location_id=loc,
            system_id=body["solar_system_id"],
            structure_type_id=body.get("type_id"),
            activities=sorted(a.value for a in HULL_ACTIVITIES.get(group, ())),
            source=StationSource.DISCOVERED,
        )
    raise LookupError(
        "no linked character can see this structure (needs docking access): "
        + "; ".join(errors)[:200]
    )


def engine_station(station: Station) -> EngineStation:
    hull = (
        gamedata.structure(station.structure_type_id)
        if station.structure_type_id
        else Structure(0, "NPC station")
    )
    return EngineStation(
        station_id=station.pk,
        name=station.name,
        system_id=station.system_id,
        structure=hull,
        facility_tax=station.facility_tax,
        activities=frozenset(Activity(a) for a in station.activities),
        rigs=tuple(gamedata.rig(r) for r in station.rig_type_ids),
    )
