import logging

logger = logging.getLogger(__name__)

from sqlalchemy import select, text

from src.models.models import (
    db,
    InvTypes,
    InvGroups,
    IndustryActivityMaterials,
    IndustryActivityProducts,
)
from src.industry_constants import (
    STRUCTURE_BASE_ME,
    STRUCTURE_BASE_TE,
    BASIC_SMALL_SHIP_GROUPS,
    BASIC_MEDIUM_SHIP_GROUPS,
    BASIC_LARGE_SHIP_GROUPS,
    ADV_SMALL_SHIP_GROUPS,
    ADV_MEDIUM_SHIP_GROUPS,
    ADV_LARGE_SHIP_GROUPS,
    CAPITAL_SHIP_GROUPS,
    RIG_GROUP_TO_CATEGORIES,
    ALL_ME_RIG_GROUPS,
    ATTR_ME_BONUS,
    ATTR_TE_BONUS,
    ATTR_HIGHSEC_MODIFIER,
    ATTR_LOWSEC_MODIFIER,
    ATTR_NULLSEC_MODIFIER,
)


def load_type_group_category_maps():
    """Load {typeID: groupID} and {groupID: categoryID} from SDE."""
    type_to_group = {}
    for row in db.session.execute(select(InvTypes.typeID, InvTypes.groupID)).all():
        if row.groupID is not None:
            type_to_group[row.typeID] = row.groupID

    group_to_category = {}
    for row in db.session.execute(
        select(InvGroups.groupID, InvGroups.categoryID)
    ).all():
        if row.categoryID is not None:
            group_to_category[row.groupID] = row.categoryID

    return type_to_group, group_to_category


def classify_product_for_rig(product_type_id, type_to_group, group_to_category):
    """Classify a product into a rig category for station ME matching.

    Returns one of: equipment, ammunition, drone_fighter,
    basic_small_ship, basic_medium_ship, basic_large_ship,
    adv_small_ship, adv_medium_ship, adv_large_ship,
    capital_ship, adv_component, basic_capital_component, structure, or None.
    """
    group_id = type_to_group.get(product_type_id)
    if group_id is None:
        return None

    category_id = group_to_category.get(group_id)
    if category_id is None:
        return None

    if category_id == 7:
        return "equipment"
    if category_id == 8:
        return "ammunition"
    if category_id in (18, 87):
        return "drone_fighter"
    if category_id == 6:
        if group_id in BASIC_SMALL_SHIP_GROUPS:
            return "basic_small_ship"
        if group_id in BASIC_MEDIUM_SHIP_GROUPS:
            return "basic_medium_ship"
        if group_id in BASIC_LARGE_SHIP_GROUPS:
            return "basic_large_ship"
        if group_id in ADV_SMALL_SHIP_GROUPS:
            return "adv_small_ship"
        if group_id in ADV_MEDIUM_SHIP_GROUPS:
            return "adv_medium_ship"
        if group_id in ADV_LARGE_SHIP_GROUPS:
            return "adv_large_ship"
        if group_id in CAPITAL_SHIP_GROUPS:
            return "capital_ship"
        return None
    if category_id == 17:
        if group_id in (334, 964):
            return "adv_component"
        if group_id in (873, 913):
            return "basic_capital_component"
        if group_id == 536:
            return "structure"
        return None
    if category_id == 65:
        return "structure"

    return None


def load_rig_data():
    """Load ME bonus + security multipliers from dgmTypeAttributes for all ME rig types.

    Returns {typeID: {'me_bonus': float, 'sec_mult': {'hs': float, 'ls': float, 'ns': float}, 'group_id': int}}
    """
    # Get all typeIDs in ME rig groups (ORM routes to static DB)
    rig_rows = db.session.execute(
        select(InvTypes.typeID, InvTypes.groupID)
        .where(InvTypes.groupID.in_(ALL_ME_RIG_GROUPS))
        .where(InvTypes.published)
    ).all()
    if not rig_rows:
        return {}

    rig_type_ids = {r.typeID for r in rig_rows}
    type_to_rig_group = {r.typeID: r.groupID for r in rig_rows}

    # Fetch dogma attributes from static DB via engine
    type_list = ",".join(str(t) for t in rig_type_ids)
    attr_ids = f"{ATTR_ME_BONUS},{ATTR_TE_BONUS},{ATTR_HIGHSEC_MODIFIER},{ATTR_LOWSEC_MODIFIER},{ATTR_NULLSEC_MODIFIER}"
    attrs_sql = text(f"""
        SELECT typeID, attributeID, COALESCE(valueFloat, valueInt) as value
        FROM dgmTypeAttributes
        WHERE typeID IN ({type_list}) AND attributeID IN ({attr_ids})
    """)
    engine = db.engines["static"]
    with engine.connect() as conn:
        attr_rows = conn.execute(attrs_sql).all()

    # Build per-type attribute map
    type_attrs = {}
    for type_id, attr_id, value in attr_rows:
        type_attrs.setdefault(type_id, {})[attr_id] = value

    rig_data = {}
    for type_id in rig_type_ids:
        attrs = type_attrs.get(type_id, {})
        me_bonus = abs(attrs.get(ATTR_ME_BONUS, 0.0))
        te_bonus = abs(attrs.get(ATTR_TE_BONUS, 0.0))
        rig_data[type_id] = {
            "me_bonus": me_bonus,
            "te_bonus": te_bonus,
            "sec_mult": {
                "hs": attrs.get(ATTR_HIGHSEC_MODIFIER, 1.0),
                "ls": attrs.get(ATTR_LOWSEC_MODIFIER, 1.9),
                "ns": attrs.get(ATTR_NULLSEC_MODIFIER, 2.1),
            },
            "group_id": type_to_rig_group[type_id],
        }

    return rig_data


def _get_security_class(security_status):
    """Determine security class from system security status."""
    if security_status is None:
        return "hs"
    if security_status >= 0.45:
        return "hs"
    if security_status > 0.0:
        return "ls"
    return "ns"


def _compute_station_me(station, product_rig_category, system_security, rig_data):
    """Compute effective ME% for a station given a product rig category.

    Returns the total ME% (0-100 scale) or 0 if no matching rig.
    """
    structure_type = station.get("structure_type", "")
    base_me = STRUCTURE_BASE_ME.get(structure_type, 0.0)

    # Find best matching rig in this station's rig slots
    best_rig_effective = 0.0
    sec_class = _get_security_class(system_security)

    for rig_id in station.get("rigs", []):
        if rig_id is None:
            continue
        rig = rig_data.get(rig_id)
        if not rig:
            continue
        # Check if this rig covers the product category
        categories_covered = RIG_GROUP_TO_CATEGORIES.get(rig["group_id"], set())
        if product_rig_category not in categories_covered:
            continue
        # Compute effective ME for this rig
        rig_effective = rig["me_bonus"] * rig["sec_mult"].get(sec_class, 1.0) / 100
        best_rig_effective = max(best_rig_effective, rig_effective)

    # structure_total_me = 1 - (1 - base_me/100) * (1 - rig_effective_me)
    total_me = (1 - (1 - base_me / 100) * (1 - best_rig_effective)) * 100
    return total_me


def _compute_station_te(station, product_rig_category, system_security, rig_data):
    """Compute effective TE multiplier for a station.

    Returns a multiplier (0.0-1.0) where lower = faster.
    """
    structure_type = station.get("structure_type", "")
    base_te = STRUCTURE_BASE_TE.get(structure_type, 1.0)

    best_rig_te = 0.0
    sec_class = _get_security_class(system_security)

    for rig_id in station.get("rigs", []):
        if rig_id is None:
            continue
        rig = rig_data.get(rig_id)
        if not rig:
            continue
        categories_covered = RIG_GROUP_TO_CATEGORIES.get(rig["group_id"], set())
        if product_rig_category not in categories_covered:
            continue
        rig_effective = rig["te_bonus"] * rig["sec_mult"].get(sec_class, 1.0) / 100
        best_rig_te = max(best_rig_te, rig_effective)

    return base_te * (1 - best_rig_te)


def pick_best_station(stations, product_rig_category, system_securities, rig_data):
    """For a product rig category, find the station with highest effective ME.

    Returns (station_dict, effective_me_percent, effective_te_multiplier) or (None, 0, 1.0).
    """
    best_station = None
    best_me = 0.0
    best_te = 1.0

    for station in stations:
        sec = system_securities.get(station.get("system_id"))
        me = _compute_station_me(station, product_rig_category, sec, rig_data)
        if me > best_me:
            best_me = me
            best_station = station
            best_te = _compute_station_te(station, product_rig_category, sec, rig_data)

    return best_station, best_me, best_te


def load_activity_times():
    """Load manufacturing and copy times from SDE industryActivity table.

    Returns {bp_type_id: (mfg_seconds, copy_seconds)}.
    """
    engine = db.engines["static"]
    sql = text(
        "SELECT typeID, activityID, time FROM industryActivity WHERE activityID IN (1, 5)"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()

    times = {}  # {typeID: {1: mfg_time, 5: copy_time}}
    for type_id, activity_id, time_val in rows:
        times.setdefault(type_id, {})[activity_id] = time_val

    return {
        type_id: (acts.get(1, 0), acts.get(5, 0))
        for type_id, acts in times.items()
    }


def load_sde_manufacturing_data():
    """Load manufacturing activity materials and products into dicts for fast DFS lookups.

    Returns:
        materials_by_bp: {typeID: [(materialTypeID, quantity), ...]}
        products_by_product: {productTypeID: (blueprintTypeID, quantity)}
        bp_to_product: {blueprintTypeID: productTypeID}
    """
    materials_by_bp = {}
    for row in db.session.execute(
        select(IndustryActivityMaterials).where(
            IndustryActivityMaterials.activityID == 1
        )
    ).scalars():
        materials_by_bp.setdefault(row.typeID, []).append(
            (row.materialTypeID, row.quantity)
        )

    products_by_product = {}
    bp_to_product = {}
    for row in db.session.execute(
        select(IndustryActivityProducts).where(IndustryActivityProducts.activityID == 1)
    ).scalars():
        products_by_product[row.productTypeID] = (row.typeID, row.quantity)
        bp_to_product[row.typeID] = row.productTypeID

    return materials_by_bp, products_by_product, bp_to_product
