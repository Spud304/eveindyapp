"""Compressed ore calculator (step 8): the cheapest compressed ore for a plan's mineral shortfall."""

import dataclasses
from typing import cast

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError

from apps.accounts.models import User
from apps.sde import gamedata
from apps.sde.models import EveType
from engine import formulas as f
from engine.reprocess import OreClass, OreMix, Refinery, cheapest_mix, station_efficiency

from . import inputs, reservation
from .models import Plan

router = Router(tags=["plans"])

MINERAL_GROUP = 18


class Choice(Schema):
    id: int
    name: str
    detail: str = ""


class CompressedOreOut(Schema):
    station_id: int | None
    character_id: int | None
    stations: list[Choice]  # with each one's asteroid-ore station efficiency
    characters: list[Choice]
    ore_classes: list[OreClass]
    names: dict[int, str]  # minerals in the mix
    mix: OreMix | None
    note: str = ""


@router.get("/plans/{plan_id}/compressed-ore", response=CompressedOreOut)
def compressed_ore(
    request: HttpRequest,
    plan_id: int,
    station_id: int | None = None,
    character_id: int | None = None,
    ore_classes: str = "asteroid",
):
    """Minerals on the plan's shopping list, bought as compressed ore and reprocessed at one of
    your stations by one of your characters. Defaults: the station with the best yield on
    asteroid ore, and the character whose mix costs least."""
    user = cast(User, request.user)
    p = get_object_or_404(Plan, pk=plan_id, user=user)
    try:
        classes = [OreClass(c) for c in ore_classes.split(",") if c]
    except ValueError as exc:
        raise HttpError(422, str(exc)) from exc
    data = reservation.load(user)
    run = reservation.run_plans(user, [p], data)[p.pk]
    if run.result is None:
        raise HttpError(422, run.error or "the plan has no result")
    minerals = {t for t, it in data.game.types.items() if it.group_id == MINERAL_GROUP}
    need = {s.type_id: s.quantity for s in run.result.shopping_list if s.type_id in minerals}

    rows = list(user.stations.filter(enabled=True).order_by("name"))
    systems = inputs.systems(s.system_id for s in rows)
    refineries = {}
    for s in rows:
        system = systems.get(s.system_id)
        rigs = tuple(r for r in (gamedata.refinery_rig(t) for t in s.rig_type_ids) if r)
        refineries[s.pk] = Refinery(
            s.name,
            gamedata.hull_refining_bonus(s.structure_type_id),
            f.security_class(system.security if system else None),
            rigs,
        )
    if not refineries:
        raise HttpError(422, "add a station in Setup first")
    station_choices = [
        Choice(
            id=pk,
            name=r.name,
            detail=f"{station_efficiency(r, OreClass.ASTEROID)[0]:.1%} on asteroid ore",
        )
        for pk, r in refineries.items()
    ]
    if station_id is None:
        station_id = max(
            refineries, key=lambda pk: station_efficiency(refineries[pk], OreClass.ASTEROID)[0]
        )
    if station_id not in refineries:
        raise HttpError(422, "not one of your stations")

    prices = {t: pr.unit_price for t, pr in data.prices.items()}
    ores = [
        dataclasses.replace(o, price=prices.get(o.type_id))
        for o in gamedata.ores()
        if o.ore_class in classes
    ]
    bonuses = gamedata.reprocessing_skill_bonuses()
    chars = {c.character_id: c for c in data.characters}
    character_choices = [Choice(id=c.character_id, name=c.name) for c in data.characters]

    def mix_for(cid: int | None) -> OreMix:
        skills = chars[cid].skills if cid in chars else {}
        return cheapest_mix(
            need,
            ores,
            refineries[station_id],
            skills,
            bonuses,
            gamedata.GENERAL_REPROCESSING_SKILLS,
            {m: prices.get(m) for m in minerals},
        )

    if character_id is not None and character_id not in chars:
        raise HttpError(422, "not one of your characters")
    if character_id is None and chars:
        mixes = {cid: mix_for(cid) for cid in chars}
        character_id = min(mixes, key=lambda cid: (not mixes[cid].feasible, mixes[cid].ore_cost))
        mix = mixes[character_id]
    else:
        mix = mix_for(character_id)
    names = dict(
        EveType.objects.filter(pk__in=[m.type_id for m in mix.minerals]).values_list("id", "name")
    )
    return {
        "station_id": station_id,
        "character_id": character_id,
        "stations": station_choices,
        "characters": character_choices,
        "ore_classes": classes,
        "names": names,
        "mix": mix,
        "note": "" if need else "The shopping list has no minerals.",
    }
