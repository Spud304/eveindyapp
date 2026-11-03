"""Assemble the engine's `PlanInput` from an account's synced data.

Sources: SDE game data; the account's enabled stations; linked characters' skills; owned
blueprints and assets of the account's characters and of corps it may read; CCP adjusted
and average prices; system cost indices; the account's build rules.

Assets counted as available: items at one of the account's stations (or at `locations`
when given), in a personal hangar, corp hangar division or deliveries, and not assembled
(an assembled ship or container is not a material). Asset reservation between plans is
step 3; until then every plan sees all of them.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping

from django.db.models import Q

from apps.accounts.models import User
from apps.esidata.access import readable_corp_feeds
from apps.esidata.models import (
    Asset,
    BlueprintItem,
    CharacterSkill,
    Feed,
    MarketPrice,
    OwnerKind,
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
    OwnedBlueprint,
    PlanInput,
    PlanLine,
    Price,
    SolarSystem,
)

from .models import BuildRules as BuildRulesRow
from .stations import engine_station

AVAILABLE_FLAGS = ("Hangar", "CorpDeliveries", "Deliveries")


def _owners(user: User, feed: Feed) -> Q:
    q = Q(owner_kind=OwnerKind.CHARACTER, owner_id__in=user.characters.values("character_id"))
    for corp_id, feeds in readable_corp_feeds(user).items():
        if feed in feeds:
            q |= Q(owner_kind=OwnerKind.CORPORATION, owner_id=corp_id)
    return q


def characters(user: User) -> tuple[Character, ...]:
    skills: dict[int, dict[int, int]] = defaultdict(dict)
    for cid, sid, level in CharacterSkill.objects.filter(character__user=user).values_list(
        "character_id", "skill_id", "active_level"
    ):
        skills[cid][sid] = level
    return tuple(
        # Every activity allowed and omega until per-character settings exist.
        Character(c.character_id, c.name, skills.get(c.character_id, {}), frozenset(Activity))
        for c in user.characters.filter(character_id__in=skills.keys()).order_by("name")
    )


def owned_blueprints(user: User) -> tuple[OwnedBlueprint, ...]:
    out = []
    for b in BlueprintItem.objects.filter(_owners(user, Feed.BLUEPRINTS)):
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
            )
        )
    return tuple(out)


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


def available_assets(user: User, locations: Iterable[int]) -> dict[int, int]:
    totals: dict[int, int] = defaultdict(int)
    for (type_id, _, _), qty in asset_buckets(user, locations).items():
        totals[type_id] += qty
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


def plan_input(
    user: User,
    lines: Iterable[PlanLine],
    choices: Mapping[int, BlueprintChoice] | None = None,
    locations: Iterable[int] | None = None,
) -> PlanInput:
    stations = list(user.stations.filter(enabled=True))
    if locations is None:
        locations = [s.location_id for s in stations if s.location_id is not None]
    return PlanInput(
        lines=tuple(lines),
        game=gamedata.game_data(),
        stations=tuple(engine_station(s) for s in stations),
        systems=systems(s.system_id for s in stations),
        characters=characters(user),
        blueprints=owned_blueprints(user),
        assets=available_assets(user, locations),
        prices=prices(),
        rules=build_rules(user),
        choices=dict(choices or {}),
    )
