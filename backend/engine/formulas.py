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
    SkillRequirement,
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
    """Character skill time factor. Which skill modifies which activity comes from the
    skills' SDE dogma effects: Advanced Industry modifies manufacturing, copying and
    invention, not reactions. Implants are not modelled."""
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


def required_skill_time_multiplier(
    skills: tuple[SkillRequirement, ...],
    bonuses: Mapping[int, float],
    character: Character | None,
) -> float:
    """Manufacturing time factor from the recipe's required skills that carry attr 1982:
    product of 1 + value x level / 100. [client: industryCommon.REQUIRED_SKILL_MODIFIERS]"""
    mult = 1.0
    for req in skills:
        per_level = bonuses.get(req.skill_id)
        if per_level:
            mult *= 1 + per_level * skill(character, req.skill_id) / 100
    return mult


def max_runs(activity: Activity, time_per_run: float, time_multiplier: float) -> int:
    """Most runs one job may have on an original (or a reaction formula): its total time
    may not exceed 30 days. Copying and invention are capped at 500. [client: activity.py]
    `time_multiplier` should leave out character skills: they only shorten the job, so
    leaving them out keeps every planned job valid whoever runs it."""
    cap = (
        c.MAX_SCIENCE_RUNS
        if activity in (Activity.COPYING, Activity.INVENTION)
        else (c.MAX_RUNS_HARD_CAP)
    )
    per_run = time_per_run * time_multiplier
    if per_run <= 0:
        return cap
    return max(1, min(math.ceil(c.MAX_RUN_LENGTH / per_run), cap))


def round_half_up(x: float) -> int:
    """The client is Python 2, whose round() rounds halves away from zero."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


@dataclass(frozen=True, slots=True)
class Fee:
    base: int
    job_cost: int
    facility_tax: int
    scc_surcharge: int
    security_tax: int

    @property
    def total(self) -> int:
        return self.job_cost + self.facility_tax + self.scc_surcharge + self.security_tax


def job_fee(
    base: float,
    cost_index: float,
    cost_multiplier: float,
    facility_tax_percent: float,
    is_alpha: bool,
    safe_sec: bool,
) -> Fee:
    """Install cost as the client computes it (industry/job.py):
    job cost = base x index x cost modifiers (+ base x 0.25% if alpha, additive);
    tax, SCC and the safe-sec tax are each a share of the rounded base. Each part is
    rounded to whole ISK."""
    cost = base * cost_index * cost_multiplier
    if is_alpha:
        cost += base * c.ALPHA_CLONE_TAX
    base_r = round_half_up(base)
    return Fee(
        base=base_r,
        job_cost=round_half_up(cost),
        facility_tax=round_half_up(base_r * facility_tax_percent / 100),
        scc_surcharge=round_half_up(base_r * c.SCC_SURCHARGE),
        security_tax=round_half_up(base_r * c.INDUSTRY_SECURITY_TAX) if safe_sec else 0,
    )


def is_safe_sec(security: float | None) -> bool:
    return security is not None and security >= c.SAFE_SEC_THRESHOLD


def invention_probability(
    base: float,
    character: Character | None,
    encryption_skill: int | None,
    science_skills: tuple[int, ...],
    decryptor_multiplier: float,
) -> float:
    """base x (1 + (sci1 + sci2)/30 + encryption/40) x decryptor, at most 1. The 1/40 skills
    are SDE type list 799 (the Encryption Methods skills). [client: invention.py]"""
    sci = sum(skill(character, s) for s in science_skills)
    enc = skill(character, encryption_skill) if encryption_skill else 0
    return min(1.0, base * (1 + sci / 30 + enc / 40) * decryptor_multiplier)


def skills_met(character: Character, requirements) -> bool:
    return all(character.skills.get(r.skill_id, 0) >= r.level for r in requirements)
