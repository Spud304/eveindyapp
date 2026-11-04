from typing import cast

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Field, Router, Schema, Status
from ninja.errors import HttpError

from apps.accounts.models import User
from apps.sde.models import EveType, SolarSystem
from engine.types import Activity, BuildCategory

from . import stations
from .models import BuildRules, Station, StationSource

router = Router(tags=["planning"])

STRUCTURE_CATEGORY = 65
STRUCTURE_MODULE_CATEGORY = 66


class StationOut(Schema):
    id: int
    name: str
    location_id: int | None
    system_id: int
    system_name: str | None
    security: float | None
    structure_type_id: int | None
    structure_type_name: str | None
    rig_type_ids: list[int]
    rig_names: list[str]
    activities: list[str]
    facility_tax: float
    tax_confirmed: bool
    reprocessing_tax: float
    enabled: bool
    source: str


class StationIn(Schema):
    name: str = Field(..., max_length=200)
    system_id: int
    structure_type_id: int | None = None
    rig_type_ids: list[int] = []
    activities: list[Activity] = []
    facility_tax: float = Field(0.0, ge=0, le=100)


class StationPatch(Schema):
    name: str | None = Field(None, max_length=200)
    structure_type_id: int | None = None
    rig_type_ids: list[int] | None = None
    activities: list[Activity] | None = None
    facility_tax: float | None = Field(None, ge=0, le=100)
    reprocessing_tax: float | None = Field(None, ge=0, le=100)
    enabled: bool | None = None


class DiscoverOut(Schema):
    added: list[StationOut]
    already_known: list[int]
    unresolved: dict[int, str]
    asset_only_npc: dict[int, int]


class BuildRulesIO(Schema):
    item_blacklist: list[int] = []
    buy_categories: list[BuildCategory] = []


def _user(request: HttpRequest) -> User:
    return cast(User, request.user)


def _station_out(s: Station) -> dict:
    names = dict(
        EveType.objects.filter(pk__in=[*s.rig_type_ids, s.structure_type_id or 0]).values_list(
            "id", "name"
        )
    )
    system = SolarSystem.objects.filter(pk=s.system_id).first()
    return {
        "id": s.pk,
        "name": s.name,
        "location_id": s.location_id,
        "system_id": s.system_id,
        "system_name": system.name if system else None,
        "security": system.security if system else None,
        "structure_type_id": s.structure_type_id,
        "structure_type_name": names.get(s.structure_type_id),
        "rig_type_ids": s.rig_type_ids,
        "rig_names": [names.get(r, str(r)) for r in s.rig_type_ids],
        "activities": s.activities,
        "facility_tax": s.facility_tax,
        "tax_confirmed": s.tax_confirmed,
        "reprocessing_tax": s.reprocessing_tax,
        "enabled": s.enabled,
        "source": s.source,
    }


def _check_types(structure_type_id: int | None, rig_type_ids: list[int] | None) -> None:
    if (
        structure_type_id is not None
        and not EveType.objects.filter(
            pk=structure_type_id, group__category_id=STRUCTURE_CATEGORY
        ).exists()
    ):
        raise HttpError(422, f"{structure_type_id} is not a structure type")
    if rig_type_ids:
        found = set(
            EveType.objects.filter(
                pk__in=rig_type_ids, group__category_id=STRUCTURE_MODULE_CATEGORY
            ).values_list("id", flat=True)
        )
        bad = sorted(set(rig_type_ids) - found)
        if bad:
            raise HttpError(422, f"not structure rigs: {bad}")


@router.get("/stations", response=list[StationOut])
def list_stations(request: HttpRequest):
    return [_station_out(s) for s in _user(request).stations.all()]


@router.post("/stations/discover", response=DiscoverOut)
def discover_stations(request: HttpRequest):
    result = stations.discover(_user(request))
    return {
        "added": [_station_out(s) for s in result.added],
        "already_known": result.already_known,
        "unresolved": result.unresolved,
        "asset_only_npc": result.asset_only_npc,
    }


@router.post("/stations", response={201: StationOut})
def add_station(request: HttpRequest, body: StationIn):
    _check_types(body.structure_type_id, body.rig_type_ids)
    if not SolarSystem.objects.filter(pk=body.system_id).exists():
        raise HttpError(422, "unknown solar system")
    s = Station.objects.create(
        user=_user(request),
        name=body.name,
        system_id=body.system_id,
        structure_type_id=body.structure_type_id,
        rig_type_ids=body.rig_type_ids,
        activities=[a.value for a in body.activities],
        facility_tax=body.facility_tax,
        tax_confirmed=True,
        source=StationSource.MANUAL,
    )
    return Status(201, _station_out(s))


@router.patch("/stations/{station_id}", response=StationOut)
def edit_station(request: HttpRequest, station_id: int, body: StationPatch):
    s = get_object_or_404(Station, pk=station_id, user=_user(request))
    data = body.dict(exclude_unset=True)
    _check_types(data.get("structure_type_id"), data.get("rig_type_ids"))
    for field, value in data.items():
        if field == "activities":
            value = [Activity(a).value for a in value]
        setattr(s, field, value)
    if "facility_tax" in data:
        s.tax_confirmed = True
    s.save()
    return _station_out(s)


@router.delete("/stations/{station_id}", response={204: None})
def delete_station(request: HttpRequest, station_id: int):
    get_object_or_404(Station, pk=station_id, user=_user(request)).delete()
    return Status(204, None)


@router.get("/build-rules", response=BuildRulesIO)
def get_rules(request: HttpRequest):
    row = BuildRules.objects.filter(user=_user(request)).first()
    return row or {"item_blacklist": [], "buy_categories": []}


@router.put("/build-rules", response=BuildRulesIO)
def put_rules(request: HttpRequest, body: BuildRulesIO):
    row, _ = BuildRules.objects.update_or_create(
        user=_user(request),
        defaults={
            "item_blacklist": sorted(set(body.item_blacklist)),
            "buy_categories": sorted({c.value for c in body.buy_categories}),
        },
    )
    return row
