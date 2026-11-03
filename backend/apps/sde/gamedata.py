"""Build the planning engine's static inputs from the imported SDE.

- `game_data()`: every live type, blueprint and decryptor as `engine.types.GameData`.
- `structure(type_id)` / `rig(type_id)`: hull and rig bonuses from CCP's
  industryModifierSources + industryTargetFilters, with values from typeDogma.

Results are cached per process and keyed by the live SDE build, so a new import is picked up
without a restart.
"""

from collections import defaultdict
from functools import lru_cache

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
ATTR_SECURITY = {SecurityClass.HIGH: 2355, SecurityClass.LOW: 2356, SecurityClass.NULL: 2357}
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
    latest = SdeBuild.latest()
    return latest.pk if latest else 0


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
        tid: ItemType(tid, name, gid, group_category.get(gid, 0))
        for tid, name, gid in EveType.objects.filter(removed=False).values_list(
            "id", "name", "group_id"
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
    return GameData(types=types, blueprints=blueprints, decryptors=tuple(decryptors))


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
    bonuses = []
    for activity, kind, entry in _sources(type_id):
        attrs = ATTR_REACTOR_RIG if activity == Activity.REACTION else ATTR_ENGINEERING_RIG
        attr = attrs.get(kind)
        percent = abs(values.get(attr, 0.0)) if attr else 0.0
        if not percent:
            continue
        target = _filter(build_key, int(entry["filterID"])) if "filterID" in entry else None
        bonuses.append(RigBonus(activity, kind, percent, target))
    sec = {cls: values[attr] for cls, attr in ATTR_SECURITY.items() if attr in values}
    return Rig(type_id, t.name, tuple(bonuses), sec)
