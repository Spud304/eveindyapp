"""Industry formulas: security class, station bonuses, materials, time, fees,
invention chance. Pure functions over engine types."""

from __future__ import annotations

import math
from collections.abc import Mapping

from . import constants as c
from .types import (
    Activity,
    Character,
    ItemType,
    Material,
    Rig,
    SecurityClass,
    Station,
    TypeId,
)


def security_class(security: float | None) -> SecurityClass:
    """CCP's rule: >= 0.45 highsec, > 0.0 lowsec, else nullsec. Positive values
    below 0.05 display as 0.1, so they are lowsec. [official: ESI system
    security guide]"""
    if security is None:
        return SecurityClass.HIGH
    if security >= 0.45:
        return SecurityClass.HIGH
    if security > 0.0:
        return SecurityClass.LOW
    return SecurityClass.NULL


def classify_manufacturing(product: ItemType | None) -> str | None:
    """Rig category for a manufactured product, or None if no rig applies."""
    if product is None:
        return None
    g, cat = product.group_id, product.category_id
    if cat == 7:
        return "equipment"
    if cat == 8:
        return "ammunition"
    if cat in (18, 87):
        return "drone_fighter"
    if cat == 6:
        for groups, name in (
            (c.BASIC_SMALL_SHIP_GROUPS, "basic_small_ship"),
            (c.BASIC_MEDIUM_SHIP_GROUPS, "basic_medium_ship"),
            (c.BASIC_LARGE_SHIP_GROUPS, "basic_large_ship"),
            (c.ADV_SMALL_SHIP_GROUPS, "adv_small_ship"),
            (c.ADV_MEDIUM_SHIP_GROUPS, "adv_medium_ship"),
            (c.ADV_LARGE_SHIP_GROUPS, "adv_large_ship"),
            (c.CAPITAL_SHIP_GROUPS, "capital_ship"),
        ):
            if g in groups:
                return name
        return None
    if cat == 17:
        if g in (334, 964):
            return "adv_component"
        if g in (873, 913):
            return "basic_capital_component"
        if g == 536:
            return "structure"
        return None
    if cat == 65:
        return "structure"
    return None


def classify_reaction(formula: ItemType | None) -> str | None:
    if formula is None:
        return None
    return c.REACTION_FORMULA_RIG_CATEGORY.get(formula.group_id)


def _rig_effect(rig: Rig, bonus: float, sec: SecurityClass) -> float:
    """Rig bonus as a fraction after the security multiplier."""
    return bonus * rig.security_multipliers.get(sec, 1.0) / 100


def best_rig(
    station: Station, activity: Activity, rig_category: str | None, sec: SecurityClass
) -> tuple[float, float, Rig | None, Rig | None]:
    """Best ME and TE rig fractions that cover `rig_category`, and the rigs."""
    coverage = c.RIG_CATEGORIES_BY_ACTIVITY.get(activity, {})
    best_me, best_te = 0.0, 0.0
    me_rig = te_rig = None
    if rig_category is None:
        return best_me, best_te, me_rig, te_rig
    for rig in station.rigs:
        if rig_category not in coverage.get(rig.group_id, frozenset()):
            continue
        me = _rig_effect(rig, rig.me_bonus, sec)
        te = _rig_effect(rig, rig.te_bonus, sec)
        if me > best_me:
            best_me, me_rig = me, rig
        if te > best_te:
            best_te, te_rig = te, rig
    return best_me, best_te, me_rig, te_rig


def station_bonuses(
    station: Station, activity: Activity, rig_category: str | None, sec: SecurityClass
) -> tuple[float, float, str]:
    """(material multiplier, time multiplier, description) for a job type at a
    station. Material multiplier excludes blueprint ME."""
    rig_me, rig_te, me_rig, te_rig = best_rig(station, activity, rig_category, sec)
    s = station.structure
    if activity == Activity.REACTION:
        mat = 1 - rig_me
        time = s.reaction_te_multiplier * (1 - rig_te)
    else:
        mat = s.me_multiplier * (1 - rig_me)
        time = s.te_multiplier * (1 - rig_te)
    parts = [s.name]
    if me_rig:
        parts.append(f"ME rig {me_rig.type_id} ({rig_me * 100:.2f}%)")
    if te_rig:
        parts.append(f"TE rig {te_rig.type_id} ({rig_te * 100:.2f}%)")
    parts.append(sec.value + "sec")
    return mat, time, ", ".join(parts)


def job_materials(
    materials: tuple[Material, ...],
    runs: int,
    me: int,
    station_multiplier: float,
) -> tuple[Material, ...]:
    """Materials for one job: max(runs, ceil(round(base * runs * mods, 2))).
    Rounding applies to the whole job, not per run. The round(…, 2) avoids
    float noise before the ceiling. [community, CCP-confirmed on forums]"""
    mult = (1 - me / 100) * station_multiplier
    out = []
    for m in materials:
        qty = max(runs, math.ceil(round(m.quantity * runs * mult, 2)))
        out.append(Material(m.type_id, qty))
    return tuple(out)


def skill(character: Character | None, skill_id: int) -> int:
    if character is None:
        return 0
    return character.skills.get(skill_id, 0)


def skill_time_multiplier(activity: Activity, character: Character | None) -> float:
    """Character skill time factor. [SDE skill attributes; which activities
    Advanced Industry covers is community]"""
    adv = 1 - c.ADV_INDUSTRY_TIME_BONUS * skill(character, c.SKILL_ADV_INDUSTRY)
    if activity == Activity.MANUFACTURING:
        return (1 - c.INDUSTRY_TIME_BONUS * skill(character, c.SKILL_INDUSTRY)) * adv
    if activity == Activity.REACTION:
        return 1 - c.REACTIONS_TIME_BONUS * skill(character, c.SKILL_REACTIONS)
    if activity == Activity.COPYING:
        return (1 - c.SCIENCE_COPY_BONUS * skill(character, c.SKILL_SCIENCE)) * adv
    return adv  # invention


def slots(character: Character, activity: Activity) -> int:
    if activity == Activity.MANUFACTURING:
        ids = (c.SKILL_MASS_PRODUCTION, c.SKILL_ADV_MASS_PRODUCTION)
    elif activity == Activity.REACTION:
        ids = (c.SKILL_MASS_REACTIONS, c.SKILL_ADV_MASS_REACTIONS)
    else:  # copying and invention share science slots
        ids = (c.SKILL_LAB_OPERATION, c.SKILL_ADV_LAB_OPERATION)
    return 1 + sum(skill(character, i) for i in ids)


def estimated_item_value(
    materials: tuple[Material, ...],
    runs: int,
    adjusted_prices: Mapping[TypeId, float | None],
) -> float:
    """EIV: ME 0 material quantities times CCP adjusted price."""
    return runs * sum(m.quantity * (adjusted_prices.get(m.type_id) or 0.0) for m in materials)


def job_fee(
    eiv: float,
    cost_index: float,
    structure_cost_multiplier: float,
    facility_tax_percent: float,
    is_alpha: bool,
) -> float:
    """EIV x (SCI x structure bonus + facility tax + SCC [+ alpha tax]).
    [community]"""
    rate = cost_index * structure_cost_multiplier + facility_tax_percent / 100 + c.SCC_SURCHARGE
    if is_alpha:
        rate += c.ALPHA_CLONE_TAX
    return eiv * rate


def invention_probability(
    base: float,
    character: Character | None,
    encryption_skill: int | None,
    science_skills: tuple[int, ...],
    decryptor_multiplier: float,
) -> float:
    """base x (1 + (sci1 + sci2)/30 + encryption/40) x decryptor. [community]"""
    sci = sum(skill(character, s) for s in science_skills)
    enc = skill(character, encryption_skill) if encryption_skill else 0
    return min(1.0, base * (1 + sci / 30 + enc / 40) * decryptor_multiplier)


def skills_met(character: Character, requirements) -> bool:
    return all(character.skills.get(r.skill_id, 0) >= r.level for r in requirements)
