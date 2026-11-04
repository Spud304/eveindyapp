"""Lookups the frontend needs: item, structure and rig search, solar systems, type names."""

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema

from .models import BlueprintProduct, EveType, SdeRawRecord, SolarSystem

router = Router(tags=["sde"])

STRUCTURE_CATEGORY = 65
STRUCTURE_MODULE_CATEGORY = 66


class TypeOut(Schema):
    id: int
    name: str
    group_id: int


class SystemOut(Schema):
    id: int
    name: str
    security: float


class SearchIn(Schema):
    q: str = Field("", max_length=100)
    kind: str = Field("buildable", pattern="^(buildable|structure|rig|any)$")
    limit: int = Field(20, ge=1, le=100)


def _ranked(qs, q: str, limit: int):
    """Exact name first, then prefix matches, then contains, each alphabetical."""
    q = q.strip()
    if len(q) < 2:
        return []
    rows = list(qs.filter(name__icontains=q).order_by("name")[:500])
    low = q.lower()
    rows.sort(key=lambda t: (t.name.lower() != low, not t.name.lower().startswith(low), t.name))
    return rows[:limit]


@router.get("/types/search", response=list[TypeOut])
def search_types(request: HttpRequest, params: Query[SearchIn]):
    """`buildable`: products of manufacturing or reactions (plan lines). `structure`: Upwell
    hulls. `rig`: structure modules with industry bonuses. `any`: every published type."""
    qs = EveType.objects.filter(published=True, removed=False)
    if params.kind == "buildable":
        product_ids = BlueprintProduct.objects.filter(
            activity__activity__in=["manufacturing", "reaction"]
        ).values("type_id")
        qs = qs.filter(pk__in=product_ids)
    elif params.kind == "structure":
        qs = qs.filter(group__category_id=STRUCTURE_CATEGORY)
    elif params.kind == "rig":
        rig_ids = [
            int(k)
            for k in SdeRawRecord.objects.filter(
                file="industryModifierSources", removed=False
            ).values_list("key", flat=True)
        ]
        qs = qs.filter(pk__in=rig_ids, group__category_id=STRUCTURE_MODULE_CATEGORY)
    return [
        {"id": t.id, "name": t.name, "group_id": t.group_id}
        for t in _ranked(qs, params.q, params.limit)
    ]


@router.get("/types", response=list[TypeOut])
def type_names(request: HttpRequest, ids: str = ""):
    """Names for a comma-separated list of type ids (at most 500)."""
    wanted = [int(i) for i in ids.split(",") if i.strip().isdigit()][:500]
    return [
        {"id": t.id, "name": t.name, "group_id": t.group_id}
        for t in EveType.objects.filter(pk__in=wanted)
    ]


@router.get("/systems/search", response=list[SystemOut])
def search_systems(request: HttpRequest, q: str = "", limit: int = 20):
    rows = _ranked(SolarSystem.objects.filter(removed=False), q, max(1, min(limit, 50)))
    return [{"id": s.id, "name": s.name, "security": s.security} for s in rows]
