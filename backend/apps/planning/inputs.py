"""Assemble the engine's `PlanInput` from an account's synced data.

Sources: SDE game data; the account's enabled stations; linked characters' skills; owned
blueprints and assets of the account's characters and of corps it may read; CCP adjusted
and average prices; system cost indices; the account's build rules.

Assets counted as available: items in a personal hangar, corp hangar division or deliveries,
and not assembled (an assembled ship or container is not a material). `load` gathers the
account's data once; `plan_input` turns it into one plan's input, with that plan's stations,
hangar scope and rule overrides. Which stock a plan may use when other plans reserve stock is
`reservation`'s job; progress from linked jobs is `tracker`'s.
"""

import dataclasses
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.esidata.access import owner_q
from apps.esidata.jobs import OPEN_STATUSES, blueprint_jobs
from apps.esidata.models import (
    Asset,
    BlueprintItem,
    CharacterSkill,
    Feed,
    IndustryJob,
    MarketPrice,
    SystemCostIndex,
)
from apps.sde import gamedata
from apps.sde.models import SolarSystem as SdeSystem
from engine.types import (
    Activity,
    BlueprintChoice,
    BuildCategory,
    BuildRules,
    Character,
    GameData,
    OwnedBlueprint,
    PlanInput,
    PlanLine,
    Price,
    SolarSystem,
    Station,
)

from .models import BuildRules as BuildRulesRow
from .models import JobLink, Plan
from .models import PlanLine as PlanLineRow
from .stations import engine_station

AVAILABLE_FLAGS = ("Hangar", "CorpDeliveries", "Deliveries")


def _owners(user: User, feed: Feed) -> Q:
    return owner_q(user, feed)


def characters(user: User) -> tuple[Character, ...]:
    skills: dict[int, dict[int, int]] = defaultdict(dict)
    for cid, sid, level in CharacterSkill.objects.filter(character__user=user).values_list(
        "character_id", "skill_id", "active_level"
    ):
        skills[cid][sid] = level
    busy = busy_slots(user)
    return tuple(
        # Every activity allowed and omega until per-character settings exist.
        Character(
            c.character_id,
            c.name,
            skills.get(c.character_id, {}),
            frozenset(Activity),
            busy=busy.get(c.character_id, {}),
        )
        for c in user.characters.filter(character_id__in=skills.keys()).order_by("name")
    )


# ESI activity id -> the slot it takes. Research (3 TE, 4 ME) uses science slots too, though
# plans never schedule it. [client: industry activities]
SLOT_OF_ACTIVITY = {1: "mfg", 3: "science", 4: "science", 5: "science", 8: "science", 9: "reaction"}


def busy_slots(user: User) -> dict[int, dict[str, tuple[float, ...]]]:
    """character id -> slot kind -> seconds until each running job ends. Running means active
    and not yet past its end (a job ready to deliver frees its slot) or paused (until its stored
    end, as for blueprint locks). Corp jobs count for the character who installed them."""
    now = timezone.now()
    out: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    jobs = IndustryJob.objects.filter(
        owner_q(user, Feed.JOBS),
        installer_id__in=user.characters.values("character_id"),
        status__in=("active", "paused"),
    ).values_list("installer_id", "activity_id", "status", "end_date")
    for installer, activity, status, end in jobs:
        kind = SLOT_OF_ACTIVITY.get(activity)
        if kind is None or (status == "active" and end <= now):
            continue
        out[installer][kind].append(max(0.0, (end - now).total_seconds()))
    return {cid: {k: tuple(v) for k, v in kinds.items()} for cid, kinds in out.items()}


def owned_blueprints(user: User) -> tuple[OwnedBlueprint, ...]:
    out = []
    jobs = blueprint_jobs(user)
    now = timezone.now()
    for b in BlueprintItem.objects.filter(_owners(user, Feed.BLUEPRINTS)):
        job = jobs.get(b.item_id)
        # quantity: -1 original, -2 copy, N > 0 a stack of N unresearched originals (one is
        # enough for planning; extra originals are step 6).
        out.append(
            OwnedBlueprint(
                item_id=b.item_id,
                type_id=b.type_id,
                is_copy=b.quantity == -2,
                runs=b.runs,
                me=b.material_efficiency,
                te=b.time_efficiency,
                owner_id=b.owner_id,
                location_id=b.root_location_id,
                job_activity_id=job.activity_id if job else None,
                job_ends_in=(job.end_date - now).total_seconds() if job else 0.0,
            )
        )
    return tuple(out)


def incoming_copies(user: User) -> list[tuple[OwnedBlueprint, int | None]]:
    """Copies that open copy jobs are making, as engine blueprints usable when the job ends,
    with the plan the job is linked to (None: not linked to a plan, so any plan may use them).
    A job makes `runs` copies of `licensed_runs` runs, at the original's ME / TE. Item ids are
    negative and made up (job id x 1000 + n); the copies have none until they exist."""
    jobs = list(
        IndustryJob.objects.filter(
            owner_q(user, Feed.JOBS), activity_id=5, status__in=OPEN_STATUSES
        ).exclude(licensed_runs=None)
    )
    originals = {
        b.item_id: b
        for b in BlueprintItem.objects.filter(item_id__in=[j.blueprint_id for j in jobs])
    }
    links = dict(JobLink.objects.filter(user=user, job__in=jobs).values_list("job_id", "plan_id"))
    now = timezone.now()
    out = []
    for j in jobs:
        bpo = originals.get(j.blueprint_id)
        for n in range(j.runs):
            copy = OwnedBlueprint(
                item_id=-(j.job_id * 1000 + n),
                type_id=j.blueprint_type_id,
                is_copy=True,
                runs=j.licensed_runs or 0,
                me=bpo.material_efficiency if bpo else 0,
                te=bpo.time_efficiency if bpo else 0,
                owner_id=j.owner_id,
                location_id=j.output_location_id,
                source_job_id=j.job_id,
                available_in=(j.end_date - now).total_seconds(),
            )
            out.append((copy, links.get(j.job_id)))
    return out


AssetBucket = tuple[int, int, str]  # (type_id, root location id, hangar flag)


def asset_buckets(user: User, locations: Iterable[int] | None = None) -> dict[AssetBucket, int]:
    """Usable stock grouped by item, location and hangar: personal hangars, corp divisions
    and deliveries, not assembled. `locations` None means everywhere."""
    hangar = Q(hangar_flag__in=AVAILABLE_FLAGS) | Q(hangar_flag__startswith="CorpSAG")
    qs = Asset.objects.filter(_owners(user, Feed.ASSETS)).filter(hangar, is_singleton=False)
    if locations is not None:
        qs = qs.filter(root_location_id__in=list(locations))
    totals: dict[AssetBucket, int] = defaultdict(int)
    for type_id, root, flag, qty in qs.values_list(
        "type_id", "root_location_id", "hangar_flag", "quantity"
    ):
        totals[(type_id, root, flag)] += qty
    return dict(totals)


def prices() -> dict[int, Price]:
    """`unit_price` is CCP's average price until a buy-price source exists (Janice, orders)."""
    return {
        t: Price(unit_price=avg, adjusted_price=adj)
        for t, avg, adj in MarketPrice.objects.values_list(
            "type_id", "average_price", "adjusted_price"
        )
    }


def systems(system_ids: Iterable[int]) -> dict[int, SolarSystem]:
    ids = set(system_ids)
    indices: dict[int, dict[Activity, float]] = defaultdict(dict)
    wanted = [a.value for a in Activity]
    for sid, act, idx in SystemCostIndex.objects.filter(
        system_id__in=ids, activity__in=wanted
    ).values_list("system_id", "activity", "cost_index"):
        indices[sid][Activity(act)] = idx
    return {
        s.id: SolarSystem(s.id, s.name, s.security, indices.get(s.id, {}))
        for s in SdeSystem.objects.filter(pk__in=ids)
    }


def build_rules(user: User) -> BuildRules:
    row = BuildRulesRow.objects.filter(user=user).first()
    if row is None:
        return BuildRules()
    return BuildRules(
        item_blacklist=frozenset(int(t) for t in row.item_blacklist),
        buy_categories=frozenset(BuildCategory(c) for c in row.buy_categories),
    )


# --- one plan's input ------------------------------------------------------------------------


@dataclass
class AccountData:
    """Everything a plan run needs that does not depend on the plan."""

    game: GameData
    stations: dict[int, Station]  # by Station pk
    station_locations: dict[int, int | None]  # Station pk -> structure / NPC station id
    systems: dict[int, SolarSystem]
    characters: tuple[Character, ...]
    blueprints: tuple[OwnedBlueprint, ...]
    prices: dict[int, Price]
    default_rules: BuildRules
    buckets: dict[AssetBucket, int]
    # BPC item id -> the plan whose line picked it; other plans do not see it.
    picked: dict[int, int] = field(default_factory=dict)
    # Copies open copy jobs are making, with the plan the job is linked to (None: any plan).
    incoming: list[tuple[OwnedBlueprint, int | None]] = field(default_factory=list)


def load(user: User) -> AccountData:
    rows = list(user.stations.filter(enabled=True))
    return AccountData(
        game=gamedata.game_data(),
        stations={s.pk: engine_station(s) for s in rows},
        station_locations={s.pk: s.location_id for s in rows},
        systems=systems(s.system_id for s in rows),
        characters=characters(user),
        blueprints=owned_blueprints(user),
        prices=prices(),
        default_rules=build_rules(user),
        buckets=asset_buckets(user),
        picked=picked_blueprints(user),
        incoming=incoming_copies(user),
    )


def picked_blueprints(user: User) -> dict[int, int]:
    """BPC item id -> the plan whose line picked it. Plans marked complete hold none."""
    out: dict[int, int] = {}
    for plan_id, ids in (
        PlanLineRow.objects.filter(plan__user=user, plan__completed_at=None)
        .exclude(blueprint_item_ids=[])
        .values_list("plan_id", "blueprint_item_ids")
    ):
        for item_id in ids:
            out.setdefault(item_id, plan_id)
    return out


def effective_rules(default: BuildRules, p: Plan) -> BuildRules:
    blacklist = (set(default.item_blacklist) | {int(t) for t in p.blacklist_add}) - {
        int(t) for t in p.blacklist_remove
    }
    buy = set(default.buy_categories)
    for cat, mode in (p.category_overrides or {}).items():
        if mode == "buy":
            buy.add(BuildCategory(cat))
        elif mode == "build":
            buy.discard(BuildCategory(cat))
    return BuildRules(item_blacklist=frozenset(blacklist), buy_categories=frozenset(buy))


def plan_stations(p: Plan, data: AccountData) -> list[int]:
    if p.station_ids:
        return [sid for sid in p.station_ids if sid in data.stations]
    return list(data.stations)


def plan_scope(p: Plan, data: AccountData) -> tuple[set[int], set[str] | None]:
    """(locations whose stock counts, hangar flags that count or None for all)."""
    locations = {
        data.station_locations[sid]
        for sid in plan_stations(p, data)
        if data.station_locations.get(sid) is not None
    }
    locations |= {int(loc) for loc in p.extra_location_ids}
    flags = set(p.hangar_flags) if p.hangar_flags else None
    return locations, flags


def in_scope(bucket: AssetBucket, locations: set[int], flags: set[str] | None) -> bool:
    _, loc, flag = bucket
    return loc in locations and (flags is None or flag in flags)


def _choices(p: Plan) -> dict[int, BlueprintChoice]:
    out = {}
    for bp_id, c in (p.choices or {}).items():
        dec = c.get("decryptor", "auto")
        out[int(bp_id)] = BlueprintChoice(
            me_override=c.get("me"),
            te_override=c.get("te"),
            decryptor=dec if dec in ("auto", "none") else int(dec),
            buy_bpcs=c.get("buy_bpcs", 0),
            bpc_runs=c.get("bpc_runs"),
            bpc_me=c.get("bpc_me", 10),
            bpc_te=c.get("bpc_te", 20),
            bpc_price=c.get("bpc_price"),
            extra_bpos=c.get("extra_bpos", 0),
            bpo_me=c.get("bpo_me", 0),
            bpo_te=c.get("bpo_te", 0),
        )
    return out


def _available_blueprints(
    p: Plan, data: AccountData, incoming: bool, bpc_used: Mapping[int, int] | None
) -> tuple[OwnedBlueprint, ...]:
    """The account's blueprints this plan may use: not picked by another plan, with the BPC
    runs earlier reserving plans take removed (copies with none left are left out)."""
    owned = [
        *(b for b in data.blueprints if data.picked.get(b.item_id, p.pk) == p.pk),
        *(b for b, plan_id in data.incoming if incoming and plan_id in (None, p.pk)),
    ]
    if not bpc_used:
        return tuple(owned)
    out = []
    for b in owned:
        used = bpc_used.get(b.item_id, 0) if b.is_copy else 0
        if used and b.runs - used <= 0:
            continue
        out.append(dataclasses.replace(b, runs=b.runs - used) if used else b)
    return tuple(out)


def plan_input(
    p: Plan,
    data: AccountData,
    pool: Mapping[AssetBucket, int],
    *,
    progress: tuple[Mapping[int, int], Mapping[int, int]] = ({}, {}),
    incoming: bool = True,
    bpc_used: Mapping[int, int] | None = None,
) -> PlanInput:
    """The engine input for one plan. `pool`: stock still free (reservation runs pass what
    earlier reserving plans left). `progress`: (units started, invention attempts started)
    from the tracker's linked jobs. `incoming`: include copies open copy jobs are making
    (those linked to this plan or to no plan); off for the tracker's base run, which must
    still plan the copy jobs. `bpc_used`: BPC item id -> runs earlier reserving plans use."""
    locations, flags = plan_scope(p, data)
    assets: dict[int, int] = defaultdict(int)
    for bucket, qty in pool.items():
        if qty > 0 and in_scope(bucket, locations, flags):
            assets[bucket[0]] += qty
    started, started_attempts = progress
    return PlanInput(
        lines=tuple(
            PlanLine(str(ln.pk), ln.type_id, ln.quantity, tuple(ln.blueprint_item_ids))
            for ln in p.lines.all()
        ),
        game=data.game,
        stations=tuple(data.stations[s] for s in plan_stations(p, data)),
        systems=data.systems,
        characters=data.characters,
        blueprints=_available_blueprints(p, data, incoming, bpc_used),
        assets=dict(assets),
        prices=data.prices,
        rules=effective_rules(data.default_rules, p),
        choices=_choices(p),
        started=dict(started),
        started_attempts=dict(started_attempts),
    )
