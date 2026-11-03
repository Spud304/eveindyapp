"""Typed tables derived from the raw layer. One transaction so readers switch builds atomically."""

import logging
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime

from django.db import models, transaction
from django.utils import timezone

from apps.core.importing import ImportReport

from .constants import ACTIVITIES, RAW_ITER_CHUNK, TYPED_BATCH_SIZE
from .models import (
    Blueprint,
    BlueprintActivity,
    BlueprintMaterial,
    BlueprintProduct,
    BlueprintSkill,
    EveCategory,
    EveGroup,
    EveMetaGroup,
    EveType,
    SdeBuild,
    SdeRawRecord,
    SolarSystem,
)

log = logging.getLogger(__name__)

# (SDE field, model field, cast). Absent fields stay None.
TYPE_FIELDS = (
    ("techLevel", "tech_level", int),
    ("metaLevel", "meta_level", int),
    ("volume", "volume", float),
    ("packagedVolume", "packaged_volume", float),
    ("portionSize", "portion_size", int),
    ("basePrice", "base_price", float),
    ("marketGroupID", "market_group_id", int),
)


def _name(data: dict) -> str:
    name = data.get("name")
    if isinstance(name, dict):
        return str(name.get("en") or next(iter(name.values()), ""))
    return str(name or "")


def _apply(instance: models.Model, data: dict, spec: tuple[tuple[str, str, Callable], ...]) -> None:
    for sde_field, model_field, cast in spec:
        value = data.get(sde_field)
        setattr(instance, model_field, cast(value) if value is not None else None)


def _raw(file: str) -> Iterator[SdeRawRecord]:
    return SdeRawRecord.objects.filter(file=file).order_by("pk").iterator(chunk_size=RAW_ITER_CHUNK)


def _upsert[M: models.Model](model: type[M], rows: Sequence[M], fields: list[str]) -> None:
    if rows:
        model.objects.bulk_create(
            rows,
            batch_size=TYPED_BATCH_SIZE,
            update_conflicts=True,
            unique_fields=["id"],
            update_fields=fields,
        )


def _flag_missing(model: type[models.Model], seen: set[int]) -> int:
    """Rows not produced by this derivation are no longer in the current set."""
    return model.objects.filter(removed=False).exclude(id__in=seen).update(removed=True)


def derive_all(build: int, release_date: datetime | None, report: ImportReport) -> None:
    with transaction.atomic():
        categories = _derive_categories(report)
        group_category = _derive_groups(categories, report)
        meta_groups = _derive_meta_groups(report)
        _derive_types(group_category, meta_groups, report)
        _derive_blueprints(report)
        _derive_solar_systems(report)
        report.finish()
        SdeBuild.objects.update_or_create(
            build=build,
            defaults={
                "release_date": release_date,
                "imported_at": timezone.now(),
                "source": report.source[:300],
                "files": sorted(report.files),
                "counts": report.as_dict(),
                "duration_s": report.duration_s,
            },
        )


def _derive_categories(report: ImportReport) -> set[int]:
    rows, seen = [], set()
    for raw in _raw("categories"):
        cid = int(raw.key)
        seen.add(cid)
        rows.append(
            EveCategory(
                id=cid,
                name=_name(raw.data),
                published=bool(raw.data.get("published", False)),
                removed=raw.removed,
            )
        )
    _upsert(EveCategory, rows, ["name", "published", "removed"])
    _flag_missing(EveCategory, seen)
    report.derived["categories"] = len(rows)
    return seen


def _derive_groups(categories: set[int], report: ImportReport) -> dict[int, int]:
    rows, group_category, skipped = [], {}, 0
    for raw in _raw("groups"):
        gid = int(raw.key)
        cat = raw.data.get("categoryID")
        if cat is None or int(cat) not in categories:
            skipped += 1
            continue
        rows.append(
            EveGroup(
                id=gid,
                category_id=int(cat),
                name=_name(raw.data),
                published=bool(raw.data.get("published", False)),
                removed=raw.removed,
            )
        )
        group_category[gid] = int(cat)
    _upsert(EveGroup, rows, ["category", "name", "published", "removed"])
    _flag_missing(EveGroup, set(group_category))
    report.derived["groups"] = len(rows)
    if skipped:
        report.warn(f"groups: {skipped} records skipped (unknown or missing categoryID)")
    return group_category


def _derive_meta_groups(report: ImportReport) -> set[int]:
    rows = [
        EveMetaGroup(id=int(raw.key), name=_name(raw.data))
        for raw in _raw("metaGroups")
        if not raw.removed
    ]
    _upsert(EveMetaGroup, rows, ["name"])
    report.derived["metaGroups"] = len(rows)
    return {r.id for r in rows}


def _derive_types(group_category: dict[int, int], meta_groups: set[int], report: ImportReport):
    rows: list[EveType] = []
    seen: set[int] = set()
    unknown_group = unknown_meta = 0

    def flush() -> None:
        _upsert(
            EveType,
            rows,
            ["group", "name", "published", "removed", "meta_group"]
            + [f for _, f, _ in TYPE_FIELDS],
        )
        rows.clear()

    for raw in _raw("types"):
        gid = raw.data.get("groupID")
        if gid is None or int(gid) not in group_category:
            unknown_group += 1
            continue
        meta = raw.data.get("metaGroupID")
        if meta is not None and int(meta) not in meta_groups:
            unknown_meta += 1
            meta = None
        tid = int(raw.key)
        seen.add(tid)
        eve_type = EveType(
            id=tid,
            group_id=int(gid),
            name=_name(raw.data),
            published=bool(raw.data.get("published", False)),
            removed=raw.removed,
            meta_group_id=int(meta) if meta is not None else None,
        )
        _apply(eve_type, raw.data, TYPE_FIELDS)
        rows.append(eve_type)
        if len(rows) >= TYPED_BATCH_SIZE:
            flush()
    flush()
    flagged = _flag_missing(EveType, seen)
    report.derived["types"] = len(seen)
    if unknown_group:
        report.warn(f"types: {unknown_group} records skipped (groupID not in groups)")
    if unknown_meta:
        report.warn(f"types: {unknown_meta} records had an unknown metaGroupID; set to null")
    log.info("types: %d derived, %d flagged removed", len(seen), flagged)


def _derive_blueprints(report: ImportReport) -> None:
    """Blueprints upsert; their activity rows are rebuilt from scratch for the live build."""
    BlueprintActivity.objects.all().delete()  # cascades to materials, products, skills
    blueprints: list[Blueprint] = []
    activities: list[BlueprintActivity] = []
    children: list[tuple[BlueprintActivity, dict]] = []
    seen: set[int] = set()
    unknown_activity: set[str] = set()
    for raw in _raw("blueprints"):
        if raw.removed:
            continue
        bid = int(raw.key)
        seen.add(bid)
        blueprints.append(
            Blueprint(
                id=bid,
                max_production_limit=int(raw.data.get("maxProductionLimit") or 0),
                removed=False,
            )
        )
        for name, act in (raw.data.get("activities") or {}).items():
            if name not in ACTIVITIES:
                unknown_activity.add(name)
                continue
            row = BlueprintActivity(blueprint_id=bid, activity=name, time=int(act.get("time") or 0))
            activities.append(row)
            children.append((row, act))
    _upsert(Blueprint, blueprints, ["max_production_limit", "removed"])
    _flag_missing(Blueprint, seen)
    BlueprintActivity.objects.bulk_create(activities, batch_size=TYPED_BATCH_SIZE)

    materials, products, skills = [], [], []
    for row, act in children:
        for m in act.get("materials") or []:
            materials.append(
                BlueprintMaterial(
                    activity=row, type_id=int(m["typeID"]), quantity=int(m["quantity"])
                )
            )
        for p in act.get("products") or []:
            prob = p.get("probability")
            products.append(
                BlueprintProduct(
                    activity=row,
                    type_id=int(p["typeID"]),
                    quantity=int(p["quantity"]),
                    probability=float(prob) if prob is not None else None,
                )
            )
        for s in act.get("skills") or []:
            skills.append(
                BlueprintSkill(activity=row, skill_id=int(s["typeID"]), level=int(s["level"]))
            )
    BlueprintMaterial.objects.bulk_create(materials, batch_size=TYPED_BATCH_SIZE)
    BlueprintProduct.objects.bulk_create(products, batch_size=TYPED_BATCH_SIZE)
    BlueprintSkill.objects.bulk_create(skills, batch_size=TYPED_BATCH_SIZE)
    report.derived["blueprints"] = len(blueprints)
    report.derived["blueprint_activities"] = len(activities)
    if unknown_activity:
        report.warn(f"blueprints: unknown activities ignored: {sorted(unknown_activity)}")


def _derive_solar_systems(report: ImportReport) -> None:
    rows, seen = [], set()
    for raw in _raw("mapSolarSystems"):
        sid = int(raw.key)
        security = raw.data.get("securityStatus")
        if security is None:
            continue
        seen.add(sid)
        rows.append(
            SolarSystem(
                id=sid,
                name=_name(raw.data),
                security=float(security),
                region_id=raw.data.get("regionID"),
                constellation_id=raw.data.get("constellationID"),
                removed=raw.removed,
            )
        )
    _upsert(SolarSystem, rows, ["name", "security", "region_id", "constellation_id", "removed"])
    _flag_missing(SolarSystem, seen)
    report.derived["mapSolarSystems"] = len(rows)
