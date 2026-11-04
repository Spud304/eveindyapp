"""Sharing plans (step 7): who may view a plan, and the read-only view they get.

- Corp visibility: members of the plan's corporation (`share_corporation_id`, or the owner's
  main's) who log in. Membership comes from the viewer's characters' affiliation, checked
  again against ESI's public endpoint when older than AFFILIATION_MAX_AGE.
- Link visibility: anyone with /shared/<share_token>; no login. Link viewers get aliases
  instead of the owner's station, structure and character names, and small made-up ids
  instead of the real ones (character ids resolve to names through ESI).

Every viewer sees the plan's lines, the engine result (shopping list, schedule, costs) and
progress, computed from the owner's data. Never: reservation details (which name the owner's
other plans), jobs offered for linking, buy options, settings. The payload is cached for
SHARED_CACHE_SECONDS per plan and kind, so an open link cannot make the server run the
engine on every request.
"""

import dataclasses
import secrets
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import EveCharacter, User
from apps.esidata import names
from apps.sde.models import EveType

from . import reservation
from .models import Plan, Visibility
from .prices import jita_priced

AFFILIATION_MAX_AGE = timedelta(hours=24)
SHARED_CACHE_SECONDS = 60
ID_KEYS = {"station_id", "character_id", "installer_id", "facility_id"}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def plan_corporation(p: Plan) -> int | None:
    if p.share_corporation_id:
        return p.share_corporation_id
    main = p.user.main_character
    return main.corporation_id if main else None


def owner_corporations(user: User) -> list[int]:
    """Corporations the account's characters are in: the choices for corp visibility."""
    ids = user.characters.exclude(corporation_id=None).values_list("corporation_id", flat=True)
    return sorted(set(ids))


def viewer_corporations(user: User) -> set[int]:
    """The viewer's corporations, re-checked when the stored affiliation is old, so someone
    who left the corp stops seeing its plans within a day."""
    now = timezone.now()
    out = set()
    for ch in user.characters.all():
        if (
            ch.affiliation_checked_at is None
            or now - ch.affiliation_checked_at > AFFILIATION_MAX_AGE
        ):
            aff = services.fetch_affiliation(ch.character_id)
            if aff is not None:
                EveCharacter.objects.filter(pk=ch.pk).update(
                    corporation_id=aff.get("corporation_id"),
                    alliance_id=aff.get("alliance_id"),
                    affiliation_checked_at=now,
                )
                ch.corporation_id = aff.get("corporation_id")
        if ch.corporation_id:
            out.add(ch.corporation_id)
    return out


def corp_plans(user: User) -> list[Plan]:
    """Other accounts' plans shared with one of the viewer's corporations."""
    corps = viewer_corporations(user)
    if not corps:
        return []
    shared = (
        Plan.objects.filter(visibility=Visibility.CORP)
        .exclude(user=user)
        .select_related("user__main_character")
    )
    return [p for p in shared if plan_corporation(p) in corps]


def can_view(user: User, p: Plan) -> bool:
    if p.user_id == user.pk:
        return True
    return p.visibility == Visibility.CORP and plan_corporation(p) in viewer_corporations(user)


def by_token(token: str) -> Plan | None:
    if not token:
        return None
    return (
        Plan.objects.filter(visibility=Visibility.LINK, share_token=token)
        .select_related("user")
        .first()
    )


# --- the read-only view ------------------------------------------------------------------------


def view(p: Plan, anonymize: bool) -> dict:
    key = f"shared:{p.pk}:{p.updated_at.timestamp()}:{int(anonymize)}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    out = _build(p, anonymize)
    cache.set(key, out, SHARED_CACHE_SECONDS)
    return out


def _build(p: Plan, anonymize: bool) -> dict:
    from .plans_api import progress_data  # the API module imports this one

    owner = p.user
    data = reservation.load(owner)
    run = reservation.run_plans(owner, [p], data)[p.pk]
    priced, _ = jita_priced(run.result)
    lines = list(p.lines.all())
    line_names = dict(
        EveType.objects.filter(pk__in=[ln.type_id for ln in lines]).values_list("id", "name")
    )
    out = {
        "plan_id": None if anonymize else p.pk,
        "name": p.name,
        "owner_name": None if anonymize else owner.display_name,
        "anonymized": anonymize,
        "lines": [
            {"type_id": ln.type_id, "name": line_names.get(ln.type_id, ""), "quantity": ln.quantity}
            for ln in lines
        ],
        "error": run.error,
        # Priced from Jita 4-4 sell orders, as the owner sees it by default.
        "result": dataclasses.asdict(priced) if priced else None,
        "progress": progress_data(owner, p, data, run, candidates=False),
        # Only the stations and characters the plan uses, not the owner's whole setup.
        "stations": {s.station_id: s.name for s in _used_stations(run.result, data)},
        "characters": {c.character_id: c.name for c in _used_characters(run.result, data)},
    }
    return _anonymize(out, data, owner) if anonymize else out


def _used_stations(result, data) -> list:
    if result is None:
        return []
    ids = {j.station_id for j in result.jobs} | {b.station.station_id for b in result.blueprints}
    return [s for s in data.stations.values() if s.station_id in ids]


def _used_characters(result, data) -> list:
    if result is None:
        return []
    ids = {j.schedule.character_id for j in result.jobs}
    return [c for c in data.characters if c.character_id in ids]


def _anonymize(out: dict, data, owner: User) -> dict:
    """Station and character names become "Station N" / "Builder N"; other installers and
    facilities in progress become "Corp member N" / "Structure N". Their ids become N, and
    every name is replaced wherever it appears in text (reasons, warnings). All the owner's
    stations and characters are aliased for that, but only the ones the plan uses are listed."""
    used_stations, used_characters = set(out["stations"]), set(out["characters"])
    ids: dict[str, dict[int, int]] = {"station": {}, "character": {}}
    renames: dict[str, str] = {}
    stations, characters = {}, {}
    # Used ones first, so the numbers do not hint at how many the owner has.
    all_stations = sorted(data.stations.values(), key=lambda s: s.station_id not in used_stations)
    all_characters = sorted(data.characters, key=lambda c: c.character_id not in used_characters)
    for n, s in enumerate(all_stations, 1):
        ids["station"][s.station_id] = n
        stations[n] = f"Station {n}"
        renames[s.name] = stations[n]
    for n, c in enumerate(all_characters, 1):
        ids["character"][c.character_id] = n
        characters[n] = f"Builder {n}"
        renames[c.name] = characters[n]
    renames[owner.display_name] = "the owner"
    others = {"installer": 0, "facility": 0}
    for job in out["progress"]["jobs"]:
        if job["installer_id"] not in ids["character"]:
            others["installer"] += 1
            n = len(characters) + others["installer"]
            ids["character"][job["installer_id"]] = n
            characters[n] = f"Corp member {others['installer']}"
            renames[job["installer_name"]] = characters[n]
        if job["facility_name"] not in renames:
            others["facility"] += 1
            renames[job["facility_name"]] = f"Structure {others['facility']}"
        job["installer_name"] = renames.get(job["installer_name"], job["installer_name"])
        job["facility_name"] = renames[job["facility_name"]]
    out["stations"] = {ids["station"][i]: stations[ids["station"][i]] for i in used_stations}
    installers = {ids["character"][j["installer_id"]] for j in out["progress"]["jobs"]}
    out["characters"] = {
        n: name
        for n, name in characters.items()
        if n in installers or n in {ids["character"][i] for i in used_characters}
    }
    order = sorted((k for k in renames if k), key=len, reverse=True)

    def scrub(value, key=None):
        if isinstance(value, dict):
            return {k: scrub(v, k) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            for name in order:
                if name in value:
                    value = value.replace(name, renames[name])
            return value
        if key in ID_KEYS and isinstance(value, int):
            kind = "station" if key in ("station_id",) else "character"
            if key == "facility_id":
                return 0
            return ids[kind].setdefault(value, len(ids[kind]) + 1)
        return value

    return scrub(out)


def corporation_options(user: User) -> list[dict]:
    corps = owner_corporations(user)
    resolved = names.resolve(corps)
    return [{"id": c, "name": resolved.get(c, str(c))} for c in corps]
