"""Build the planning engine's static inputs from the imported SDE.

- `game_data()`: every live type, blueprint and decryptor as `engine.types.GameData`.
- `structure(type_id)` / `rig(type_id)`: hull and rig bonuses from CCP's
  industryModifierSources + industryTargetFilters, with values from typeDogma.

Results are cached per process and keyed by the live SDE build, so a new import is picked up
without a restart.
"""

from collections import defaultdict
from functools import lru_cache

from engine.reprocess import Ore, OreClass, RefineryRig
from engine.types import (
    Activity,
    BlueprintData,
    Decryptor,
    GameData,
    ItemType,
    Material,
    ModifierKind,
    Recipe,
    Rig,
    RigBonus,
    SecurityClass,
    SkillRequirement,
    Structure,
    StructureModifier,
    TargetFilter,
)

from .models import (
    Blueprint,
    BlueprintActivity,
    BlueprintMaterial,
    BlueprintProduct,
    BlueprintSkill,
    EveGroup,
    EveType,
    SdeBuild,
    SdeRawRecord,
)

DECRYPTOR_GROUP = 1304  # Generic Decryptor; groups 728-731 and 979 are legacy
ATTR_DECRYPTOR = {"prob": 1112, "me": 1113, "te": 1114, "runs": 1124}
ATTR_REQUIRED_SKILL_TIME = 1982  # manufactureTimePerLevel on skills [client][SDE]
ATTR_JOB_COST_MULTIPLIER = 1954  # jobCostMultiplier on blueprints [client][SDE]
ATTR_SECURITY = {SecurityClass.HIGH: 2355, SecurityClass.LOW: 2356, SecurityClass.NULL: 2357}
ATTR_SECURITY_MODIFIER = 2358  # securityModifier: resolves to 2355/2356/2357 [client]
# Rig bonus attribute per modifier kind (values are negative percentages in the SDE).
ATTR_ENGINEERING_RIG = {
    ModifierKind.MATERIAL: 2594,
    ModifierKind.TIME: 2593,
    ModifierKind.COST: 2595,
}
ATTR_REACTOR_RIG = {ModifierKind.MATERIAL: 2714, ModifierKind.TIME: 2713}

# industryModifierSources activity keys -> engine activities (research is not planned).
SOURCE_ACTIVITIES = {
    "manufacturing": Activity.MANUFACTURING,
    "reaction": Activity.REACTION,
    "copying": Activity.COPYING,
    "invention": Activity.INVENTION,
}
RECIPE_ACTIVITIES = ("manufacturing", "reaction", "copying", "invention")


class UnknownStructure(LookupError):
    pass


def _build_key() -> int:
    """Keys every cache below: a new build, or the same build imported again (a fix, or more
    files), gives a new key, so long-running processes pick it up without a restart."""
    latest = SdeBuild.latest()
    return hash((latest.pk, latest.imported_at)) if latest else 0


def game_data() -> GameData:
    return _game_data(_build_key())


def structure(type_id: int) -> Structure:
    return _structure(_build_key(), type_id)


def rig(type_id: int) -> Rig:
    return _rig(_build_key(), type_id)


def dogma(type_id: int) -> dict[int, float]:
    raw = SdeRawRecord.objects.filter(file="typeDogma", key=str(type_id), removed=False).first()
    if raw is None:
        return {}
    return {int(a["attributeID"]): float(a["value"]) for a in raw.data.get("dogmaAttributes", [])}


def _raw(file: str, key: int) -> dict | None:
    row = SdeRawRecord.objects.filter(file=file, key=str(key), removed=False).first()
    return row.data if row else None


@lru_cache(maxsize=2)
def _game_data(build_key: int) -> GameData:
    group_category = dict(EveGroup.objects.values_list("id", "category_id"))
    types = {
        tid: ItemType(tid, name, gid, group_category.get(gid, 0), packaged or volume or 0.0)
        for tid, name, gid, volume, packaged in EveType.objects.filter(removed=False).values_list(
            "id", "name", "group_id", "volume", "packaged_volume"
        )
    }

    acts = {a.pk: a for a in BlueprintActivity.objects.filter(activity__in=RECIPE_ACTIVITIES)}
    materials, products, skills = defaultdict(list), defaultdict(list), defaultdict(list)
    for m in BlueprintMaterial.objects.filter(activity_id__in=acts).values_list(
        "activity_id", "type_id", "quantity"
    ):
        materials[m[0]].append(Material(m[1], m[2]))
    for p in BlueprintProduct.objects.filter(activity_id__in=acts).values_list(
        "activity_id", "type_id", "quantity", "probability"
    ):
        products[p[0]].append(p[1:])
    for s in BlueprintSkill.objects.filter(activity_id__in=acts).values_list(
        "activity_id", "skill_id", "level"
    ):
        skills[s[0]].append(SkillRequirement(s[1], s[2]))

    def recipe(act: BlueprintActivity, product=None) -> Recipe:
        type_id, qty, prob = product or (None, 0, None)
        return Recipe(
            time_seconds=act.time,
            materials=tuple(materials[act.pk]),
            skills=tuple(skills[act.pk]),
            product_type_id=type_id,
            product_quantity=qty,
            probability=prob,
        )

    by_bp: dict[int, dict[str, BlueprintActivity]] = defaultdict(dict)
    for act in acts.values():
        by_bp[act.blueprint_id][act.activity] = act

    def single(a: dict[str, BlueprintActivity], name: str) -> Recipe | None:
        act = a.get(name)
        if act is None:
            return None
        prods = products[act.pk]
        return recipe(act, prods[0] if prods else None)

    attr_values = _attribute_values((ATTR_REQUIRED_SKILL_TIME, ATTR_JOB_COST_MULTIPLIER))
    published = set(
        EveType.objects.filter(published=True, pk__in=Blueprint.objects.values("id")).values_list(
            "id", flat=True
        )
    )
    blueprints = {}
    for bp_id, limit in Blueprint.objects.filter(removed=False).values_list(
        "id", "max_production_limit"
    ):
        a = by_bp.get(bp_id, {})
        invention = ()
        if "invention" in a:
            act = a["invention"]
            invention = tuple(recipe(act, p) for p in products[act.pk])
        blueprints[bp_id] = BlueprintData(
            type_id=bp_id,
            max_production_limit=limit,
            manufacturing=single(a, "manufacturing"),
            reaction=single(a, "reaction"),
            copying=single(a, "copying"),
            invention=invention,
            job_cost_multiplier=attr_values[ATTR_JOB_COST_MULTIPLIER].get(bp_id, 1.0),
            published=bp_id in published,
        )

    decryptors = []
    for t in EveType.objects.filter(group_id=DECRYPTOR_GROUP, published=True, removed=False):
        d = dogma(t.id)
        decryptors.append(
            Decryptor(
                type_id=t.id,
                name=t.name,
                probability_multiplier=d.get(ATTR_DECRYPTOR["prob"], 1.0),
                me_modifier=int(d.get(ATTR_DECRYPTOR["me"], 0)),
                te_modifier=int(d.get(ATTR_DECRYPTOR["te"], 0)),
                run_modifier=int(d.get(ATTR_DECRYPTOR["runs"], 0)),
            )
        )
    decryptors.sort(key=lambda d: d.name)
    return GameData(
        types=types,
        blueprints=blueprints,
        decryptors=tuple(decryptors),
        skill_time_bonuses=attr_values[ATTR_REQUIRED_SKILL_TIME],
    )


def _attribute_values(attribute_ids: tuple[int, ...]) -> dict[int, dict[int, float]]:
    """attribute id -> {type id: value} across all of typeDogma, for a few attributes."""
    out: dict[int, dict[int, float]] = {a: {} for a in attribute_ids}
    rows = SdeRawRecord.objects.filter(file="typeDogma", removed=False).values_list("key", "data")
    for key, data in rows.iterator(chunk_size=2000):
        for a in data.get("dogmaAttributes", []):
            attr = int(a["attributeID"])
            if attr in out:
                out[attr][int(key)] = float(a["value"])
    return out


def _sources(type_id: int):
    """Yield (activity, kind, entry) from a type's industryModifierSources record."""
    data = _raw("industryModifierSources", type_id) or {}
    for act_name, kinds in data.items():
        activity = SOURCE_ACTIVITIES.get(act_name)
        if activity is None:
            continue
        for kind_name, entries in kinds.items():
            kind = ModifierKind(kind_name)
            for entry in entries:
                yield activity, kind, entry


@lru_cache(maxsize=256)
def _structure(build_key: int, type_id: int) -> Structure:
    t = EveType.objects.filter(pk=type_id).first()
    if t is None:
        raise UnknownStructure(f"type {type_id} is not in the SDE")
    values = dogma(type_id)
    mods = []
    for activity, kind, entry in _sources(type_id):
        attr = int(entry["dogmaAttributeID"])
        if attr in values:
            mods.append(StructureModifier(activity, kind, values[attr]))
    return Structure(type_id, t.name, tuple(mods))


@lru_cache(maxsize=32)
def _filter(build_key: int, filter_id: int) -> TargetFilter:
    data = _raw("industryTargetFilters", filter_id) or {}
    return TargetFilter(
        filter_id,
        str(data.get("name", f"filter {filter_id}")),
        frozenset(int(c) for c in data.get("categoryIDs", [])),
        frozenset(int(g) for g in data.get("groupIDs", [])),
    )


@lru_cache(maxsize=1024)
def _rig(build_key: int, type_id: int) -> Rig:
    t = EveType.objects.filter(pk=type_id).first()
    if t is None:
        raise UnknownStructure(f"type {type_id} is not in the SDE")
    values = dogma(type_id)
    feeds, scaled = _rig_effects(type_id)
    bonuses = []
    for activity, kind, entry in _sources(type_id):
        # The structure attribute this entry modifies is fed by one of the rig's attributes
        # through a dogma effect. Without dogmaEffects (an older import), the usual ones.
        attr = feeds.get(int(entry["dogmaAttributeID"]))
        if attr is None and not feeds:
            attrs = ATTR_REACTOR_RIG if activity == Activity.REACTION else ATTR_ENGINEERING_RIG
            attr = attrs.get(kind)
        percent = abs(values.get(attr, 0.0)) if attr else 0.0
        if not percent:
            continue
        target = _filter(build_key, int(entry["filterID"])) if "filterID" in entry else None
        secured = attr in scaled if feeds else True
        bonuses.append(RigBonus(activity, kind, percent, target, secured))
    sec = {cls: values[attr] for cls, attr in ATTR_SECURITY.items() if attr in values}
    return Rig(type_id, t.name, tuple(bonuses), sec)


def _rig_effects(type_id: int) -> tuple[dict[int, int], set[int]]:
    """From the rig's dogma effects: {structure attribute: rig attribute that feeds it}, and
    the rig attributes its security effect multiplies by `securityModifier` (attr 2358).
    Empty when dogmaEffects was not imported. [SDE: effects 6830-6837, 6842, 6976, 7098...]"""
    record = _raw("typeDogma", type_id) or {}
    effect_ids = [int(e["effectID"]) for e in record.get("dogmaEffects", [])]
    effects = SdeRawRecord.objects.filter(
        file="dogmaEffects", key__in=[str(e) for e in effect_ids], removed=False
    ).values_list("data", flat=True)
    feeds: dict[int, int] = {}
    scaled: set[int] = set()
    for data in effects:
        for m in data.get("modifierInfo") or []:
            if "modifiedAttributeID" not in m or "modifyingAttributeID" not in m:
                continue
            if m.get("domain") == "structureID":
                feeds[int(m["modifiedAttributeID"])] = int(m["modifyingAttributeID"])
            elif (
                m.get("domain") == "itemID"
                and int(m["modifyingAttributeID"]) == ATTR_SECURITY_MODIFIER
            ):
                scaled.add(int(m["modifiedAttributeID"]))
    return feeds, scaled


# --- reprocessing (compressed ore calculator) ----------------------------------------------

ASTEROID_CATEGORY = 25
ICE_GROUP = 465
MOON_ORE_GROUPS = frozenset({1884, 1920, 1921, 1922, 1923})
ATTR_REPROCESSING_SKILL = 790  # reprocessingSkillType on ores [client][SDE]
ATTR_SKILL_YIELD = 379  # refiningYieldMutator on skills: percent per level [client][SDE]
ATTR_RIG_YIELD = 717  # refiningYieldMultiplier on reprocessing rigs [SDE]
ATTR_HULL_YIELD = 2722  # strRefiningYieldBonus on refineries, percent [SDE]
GENERAL_REPROCESSING_SKILLS = (3385, 3389)  # Reprocessing, Reprocessing Efficiency [client]
# Reprocessing rig groups and what they bonus. M-sets name their ore class; L / XL
# "Reprocessing Monitor" rigs are assumed to cover every class [unverified].
REFINERY_RIG_GROUPS = {
    1941: frozenset({OreClass.ASTEROID}),
    1942: frozenset({OreClass.ICE}),
    1943: frozenset({OreClass.MOON}),
    1944: frozenset(OreClass),
    1945: frozenset(OreClass),
}


def ores() -> tuple[Ore, ...]:
    """Every published compressed asteroid ore, moon ore and ice, without prices."""
    return _ores(_build_key())


def reprocessing_skill_bonuses() -> dict[int, float]:
    return _skill_bonuses(_build_key())


def refinery_rig(type_id: int) -> RefineryRig | None:
    t = EveType.objects.filter(pk=type_id).first()
    if t is None or t.group_id not in REFINERY_RIG_GROUPS:
        return None
    values = dogma(type_id)
    sec = {cls: values[attr] for cls, attr in ATTR_SECURITY.items() if attr in values}
    return RefineryRig(
        type_id, t.name, REFINERY_RIG_GROUPS[t.group_id], values.get(ATTR_RIG_YIELD, 0.5), sec
    )


def hull_refining_bonus(type_id: int | None) -> float:
    return dogma(type_id).get(ATTR_HULL_YIELD, 0.0) if type_id else 0.0


@lru_cache(maxsize=2)
def _ores(build_key: int) -> tuple[Ore, ...]:
    compressed = {
        int(r["compressedTypeID"])
        for r in SdeRawRecord.objects.filter(file="compressibleTypes", removed=False).values_list(
            "data", flat=True
        )
    }
    out = []
    for t in EveType.objects.filter(
        pk__in=compressed, published=True, removed=False, group__category_id=ASTEROID_CATEGORY
    ):
        mats = (_raw("typeMaterials", t.id) or {}).get("materials", [])
        if not mats:
            continue
        cls = (
            OreClass.ICE
            if t.group_id == ICE_GROUP
            else OreClass.MOON
            if t.group_id in MOON_ORE_GROUPS
            else OreClass.ASTEROID
        )
        skill = dogma(t.id).get(ATTR_REPROCESSING_SKILL)
        out.append(
            Ore(
                t.id,
                t.name,
                cls,
                t.portion_size or 1,
                tuple(Material(int(m["materialTypeID"]), int(m["quantity"])) for m in mats),
                int(skill) if skill else None,
                None,
                t.packaged_volume or t.volume or 0.0,
            )
        )
    return tuple(sorted(out, key=lambda o: o.name))


@lru_cache(maxsize=2)
def _skill_bonuses(build_key: int) -> dict[int, float]:
    skills = {o.skill_id for o in _ores(build_key) if o.skill_id} | set(GENERAL_REPROCESSING_SKILLS)
    return {s: dogma(s).get(ATTR_SKILL_YIELD, 0.0) for s in skills}
