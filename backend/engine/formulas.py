"""Industry formulas: security class, station bonuses, materials, time, fees,
invention chance. Pure functions over engine types."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from . import constants as c
from .types import (
    Activity,
    Character,
    ItemType,
    Material,
    ModifierKind,
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


@dataclass(frozen=True, slots=True)
class StationBonuses:
    """Combined multipliers for one activity and product at one station.
    `material` excludes blueprint ME; `time` excludes blueprint TE and skills;
    `cost` multiplies the system cost index."""

    material: float
    time: float
    cost: float
    description: str


def station_bonuses(
    station: Station, activity: Activity, product: ItemType | None, sec: SecurityClass
) -> StationBonuses:
    """Apply every structure modifier for `activity`, and every rig bonus for
    `activity` whose target filter matches `product`, multiplicatively. This
    is CCP's industryModifierSources model; overlapping rigs of the same kind
    cannot be fitted together, so stacking only combines hull with rig."""
    mult = {kind: 1.0 for kind in ModifierKind}
    parts = [station.structure.name]
    for m in station.structure.modifiers:
        if m.activity == activity:
            mult[m.kind] *= m.multiplier
    for rig in station.rigs:
        sec_mult = rig.security_multipliers.get(sec, 1.0)
        for b in rig.bonuses:
            if b.activity != activity:
                continue
            if b.target is not None and not b.target.matches(product):
                continue
            effect = b.percent * sec_mult / 100
            mult[b.kind] *= 1 - effect
            target = f" ({b.target.name})" if b.target else ""
            parts.append(f"{rig.name}: {b.kind.value} -{effect * 100:.2f}%{target}")
    parts.append(sec.value + "sec")
    return StationBonuses(
        mult[ModifierKind.MATERIAL],
        mult[ModifierKind.TIME],
        mult[ModifierKind.COST],
        ", ".join(parts),
    )


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
