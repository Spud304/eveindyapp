import logging
import threading

logger = logging.getLogger(__name__)

from sqlalchemy import select, text

from src.models.models import (
    db,
    EveType,
    EveGroup,
    BlueprintActivityMaterial,
    BlueprintProduct,
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
    ATTR_INVENTION_PROB_MULT,
    ATTR_INVENTION_ME_MOD,
    ATTR_INVENTION_TE_MOD,
    ATTR_INVENTION_RUN_MOD,
    SKILL_INDUSTRY,
    SKILL_ADV_INDUSTRY,
    SKILL_MASS_PRODUCTION,
    SKILL_ADV_MASS_PRODUCTION,
    SKILL_LAB_OPERATION,
    SKILL_ADV_LAB_OPERATION,
    SKILL_MASS_REACTIONS,
    SKILL_ADV_MASS_REACTIONS,
)


_sde_cache = {}
_sde_cache_lock = threading.Lock()


def load_type_group_category_maps():
    """Load {typeID: groupID} and {groupID: categoryID} from SDE. Cached after first call."""
    key = "type_group_category"
    if key in _sde_cache:
        return _sde_cache[key]

    type_to_group = {}
    for row in db.session.execute(select(EveType.typeID, EveType.groupID)).all():
        if row.groupID is not None:
            type_to_group[row.typeID] = row.groupID

    group_to_category = {}
    for row in db.session.execute(select(EveGroup.groupID, EveGroup.categoryID)).all():
        if row.categoryID is not None:
            group_to_category[row.groupID] = row.categoryID

    result = (type_to_group, group_to_category)
    with _sde_cache_lock:
        _sde_cache[key] = result
    return result


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
        select(EveType.typeID, EveType.groupID)
        .where(EveType.groupID.in_(ALL_ME_RIG_GROUPS))
        .where(EveType.published == 1)
    ).all()
    if not rig_rows:
        return {}

    rig_type_ids = {r.typeID for r in rig_rows}
    type_to_rig_group = {r.typeID: r.groupID for r in rig_rows}

    # Fetch dogma attributes from static DB via engine
    type_list = ",".join(str(t) for t in rig_type_ids)
    attr_ids = f"{ATTR_ME_BONUS},{ATTR_TE_BONUS},{ATTR_HIGHSEC_MODIFIER},{ATTR_LOWSEC_MODIFIER},{ATTR_NULLSEC_MODIFIER}"
    attrs_sql = text(f"""
        SELECT typeID, attributeID, value
        FROM TypeDogmaAttribute
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
    """Load manufacturing and copy times from SDE BlueprintActivityType table.

    Returns {bp_type_id: (mfg_seconds, copy_seconds)}.
    """
    engine = db.engines["static"]
    sql = text(
        "SELECT blueprintTypeID, activityName, time FROM BlueprintActivityType WHERE activityName IN ('manufacturing', 'copying')"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()

    times = {}  # {typeID: {'manufacturing': time, 'copying': time}}
    for type_id, activity_name, time_val in rows:
        times.setdefault(type_id, {})[activity_name] = time_val

    return {
        type_id: (acts.get("manufacturing", 0), acts.get("copying", 0))
        for type_id, acts in times.items()
    }


def load_sde_manufacturing_data():
    """Load manufacturing activity materials and products into dicts for fast DFS lookups. Cached after first call.

    Returns:
        materials_by_bp: {typeID: [(materialTypeID, quantity), ...]}
        products_by_product: {productTypeID: (blueprintTypeID, quantity)}
        bp_to_product: {blueprintTypeID: productTypeID}
    """
    key = "manufacturing_data"
    if key in _sde_cache:
        return _sde_cache[key]

    materials_by_bp = {}
    for row in db.session.execute(
        select(BlueprintActivityMaterial).where(
            BlueprintActivityMaterial.activityID == "manufacturing"
        )
    ).scalars():
        materials_by_bp.setdefault(row.typeID, []).append(
            (row.materialTypeID, row.quantity)
        )

    products_by_product = {}
    bp_to_product = {}
    for row in db.session.execute(
        select(BlueprintProduct).where(BlueprintProduct.activityID == "manufacturing")
    ).scalars():
        products_by_product[row.productTypeID] = (row.typeID, row.quantity)
        bp_to_product[row.typeID] = row.productTypeID

    result = (materials_by_bp, products_by_product, bp_to_product)
    with _sde_cache_lock:
        _sde_cache[key] = result
    return result


def load_blueprint_skill_requirements():
    """Load skill requirements for manufacturing and copying from SDE.

    Returns (mfg_skill_reqs, copy_skill_reqs) where each is
    {bp_type_id: [(skill_id, min_level), ...]}.
    """
    engine = db.engines["static"]
    sql = text(
        "SELECT parentTypeId, activityName, typeID, level FROM BlueprintSkill WHERE activityName IN ('manufacturing', 'copying')"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()

    mfg_skill_reqs = {}
    copy_skill_reqs = {}
    for bp_id, activity_name, skill_id, level in rows:
        if activity_name == "manufacturing":
            mfg_skill_reqs.setdefault(bp_id, []).append((skill_id, level))
        else:
            copy_skill_reqs.setdefault(bp_id, []).append((skill_id, level))

    return mfg_skill_reqs, copy_skill_reqs


def load_character_skills(character_ids):
    """Load cached skills for given character IDs.

    Returns {character_id: {skill_id: active_skill_level}}.
    """
    from src.models.models import CachedSkill

    if not character_ids:
        return {}

    rows = db.session.execute(
        select(
            CachedSkill.character_id,
            CachedSkill.skill_id,
            CachedSkill.active_skill_level,
        ).where(CachedSkill.character_id.in_(character_ids))
    ).all()

    result = {}
    for char_id, skill_id, level in rows:
        result.setdefault(char_id, {})[skill_id] = level
    return result


def compute_character_capabilities(char_skills):
    """Pure function: compute slot counts and skill levels from a character's skill map.

    Returns dict with mfg_slots, copy_slots, reaction_slots, industry_level, adv_industry_level.
    """
    industry_level = char_skills.get(SKILL_INDUSTRY, 0)
    adv_industry_level = char_skills.get(SKILL_ADV_INDUSTRY, 0)
    mass_prod = char_skills.get(SKILL_MASS_PRODUCTION, 0)
    adv_mass_prod = char_skills.get(SKILL_ADV_MASS_PRODUCTION, 0)
    lab_op = char_skills.get(SKILL_LAB_OPERATION, 0)
    adv_lab_op = char_skills.get(SKILL_ADV_LAB_OPERATION, 0)
    mass_react = char_skills.get(SKILL_MASS_REACTIONS, 0)
    adv_mass_react = char_skills.get(SKILL_ADV_MASS_REACTIONS, 0)

    return {
        "mfg_slots": 1 + mass_prod + adv_mass_prod,
        "copy_slots": 1 + lab_op + adv_lab_op,
        "reaction_slots": 1 + mass_react + adv_mass_react,
        "industry_level": industry_level,
        "adv_industry_level": adv_industry_level,
    }


def can_character_build(bp_type_id, char_skills, skill_reqs):
    """Check if a character meets all skill requirements for a blueprint. Returns bool."""
    reqs = skill_reqs.get(bp_type_id, [])
    for skill_id, min_level in reqs:
        if char_skills.get(skill_id, 0) < min_level:
            return False
    return True


def get_character_names(character_ids):
    """Query User model for character names. Returns {char_id: name}."""
    from src.models.models import User

    if not character_ids:
        return {}

    rows = db.session.execute(
        select(User.character_id, User.character_name).where(
            User.character_id.in_(character_ids)
        )
    ).all()
    return {r.character_id: r.character_name for r in rows}


def load_sde_invention_data():
    """Load invention activity materials, products, and probabilities into dicts. Cached after first call.

    Returns:
        invention_materials: {t1_bp_id: [(materialTypeID, quantity), ...]} -- datacores per attempt
        invention_products: {t2_bp_id: (t1_bp_id, base_runs)} -- reverse lookup
        invention_probabilities: {(t1_bp_id, t2_bp_id): base_probability}
    """
    key = "invention_data"
    if key in _sde_cache:
        return _sde_cache[key]

    # Materials for invention
    invention_materials = {}
    for row in db.session.execute(
        select(BlueprintActivityMaterial).where(
            BlueprintActivityMaterial.activityID == "invention"
        )
    ).scalars():
        invention_materials.setdefault(row.typeID, []).append(
            (row.materialTypeID, row.quantity)
        )

    # Products + probabilities: T1 BP -> T2 BP mapping (now includes probability on same table)
    invention_products = {}
    invention_probabilities = {}
    for row in db.session.execute(
        select(BlueprintProduct).where(BlueprintProduct.activityID == "invention")
    ).scalars():
        invention_products[row.productTypeID] = (row.typeID, row.quantity)
        if row.probability is not None:
            invention_probabilities[(row.typeID, row.productTypeID)] = row.probability

    result = (invention_materials, invention_products, invention_probabilities)
    with _sde_cache_lock:
        _sde_cache[key] = result
    return result


def load_decryptor_data():
    """Load decryptor types with their dogma attributes. Cached after first call.

    Returns list of dicts: [{type_id, name, prob_mult, me_mod, te_mod, run_mod}, ...]
    """
    key = "decryptor_data"
    if key in _sde_cache:
        return _sde_cache[key]

    # Find published decryptor types (groupID 1304 = Decryptors)
    decryptor_rows = db.session.execute(
        select(EveType.typeID, EveType.typeName)
        .where(EveType.groupID == 1304)
        .where(EveType.published == 1)
    ).all()

    if not decryptor_rows:
        with _sde_cache_lock:
            _sde_cache[key] = []
        return []

    type_ids = {r.typeID for r in decryptor_rows}
    type_names = {r.typeID: r.typeName for r in decryptor_rows}

    # Fetch dogma attributes
    type_list = ",".join(str(t) for t in type_ids)
    attr_ids = f"{ATTR_INVENTION_PROB_MULT},{ATTR_INVENTION_ME_MOD},{ATTR_INVENTION_TE_MOD},{ATTR_INVENTION_RUN_MOD}"
    attrs_sql = text(f"""
        SELECT typeID, attributeID, value
        FROM TypeDogmaAttribute
        WHERE typeID IN ({type_list}) AND attributeID IN ({attr_ids})
    """)
    engine = db.engines["static"]
    with engine.connect() as conn:
        attr_rows = conn.execute(attrs_sql).all()

    type_attrs = {}
    for type_id, attr_id, value in attr_rows:
        type_attrs.setdefault(type_id, {})[attr_id] = value

    decryptors = []
    for type_id in type_ids:
        attrs = type_attrs.get(type_id, {})
        decryptors.append(
            {
                "type_id": type_id,
                "name": type_names[type_id],
                "prob_mult": attrs.get(ATTR_INVENTION_PROB_MULT, 1.0),
                "me_mod": int(attrs.get(ATTR_INVENTION_ME_MOD, 0)),
                "te_mod": int(attrs.get(ATTR_INVENTION_TE_MOD, 0)),
                "run_mod": int(attrs.get(ATTR_INVENTION_RUN_MOD, 0)),
            }
        )

    decryptors.sort(key=lambda d: d["name"])
    with _sde_cache_lock:
        _sde_cache[key] = decryptors
    return decryptors


def load_invention_times():
    """Load invention times from SDE BlueprintActivityType table. Cached after first call.

    Returns {t1_bp_id: invention_seconds}.
    """
    key = "invention_times"
    if key in _sde_cache:
        return _sde_cache[key]

    engine = db.engines["static"]
    sql = text(
        "SELECT blueprintTypeID, time FROM BlueprintActivityType WHERE activityName = 'invention'"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()

    result = {type_id: time_val for type_id, time_val in rows}
    with _sde_cache_lock:
        _sde_cache[key] = result
    return result


def assign_jobs_to_characters(phase_bps, characters, skill_reqs, job_type="mfg"):
    """Greedy LPT scheduler: assign jobs to characters based on skill eligibility and slots.

    Args:
        phase_bps: list of bp_status dicts for a single phase
        characters: list of character capability dicts (with 'char_id', 'char_name', 'skills', 'mfg_slots', 'copy_slots')
        skill_reqs: {bp_type_id: [(skill_id, min_level), ...]}
        job_type: "mfg" or "copy"

    Returns list of unassignable bp_status dicts.
    """
    slot_key = "mfg_slots" if job_type == "mfg" else "copy_slots"
    remaining_slots = {c["char_id"]: c[slot_key] for c in characters}

    # Sort jobs by estimated time descending (longest first)
    def get_time(bp):
        s = bp["build_strategy"]
        if s["recommended"] == "bpc" and s.get("bpc_time"):
            return s["bpc_time"]
        return s.get("bpo_time", 0)

    sorted_bps = sorted(phase_bps, key=get_time, reverse=True)

    unassignable = []
    for bp in sorted_bps:
        bp_id = bp["type_id"]
        # Each job consumes 1 slot on the assigned character.
        # The build_strategy.slots_used reflects parallel BPC splitting across
        # aggregate slots, but assignment is per-character — one job per slot.
        slots_needed = 1

        # Find eligible characters
        eligible = []
        for c in characters:
            cid = c["char_id"]
            if remaining_slots[cid] >= slots_needed and can_character_build(
                bp_id, c["skills"], skill_reqs
            ):
                eligible.append(c)

        if eligible:
            # Pick character with most remaining slots (tie-break: best industry skill)
            best = max(
                eligible,
                key=lambda c: (
                    remaining_slots[c["char_id"]],
                    c.get("industry_level", 0),
                ),
            )
            remaining_slots[best["char_id"]] -= slots_needed
            bp["assigned_character"] = {
                "char_id": best["char_id"],
                "char_name": best["char_name"],
            }
        else:
            # Check if it's a skill issue vs a slot issue
            skill_eligible = [
                c
                for c in characters
                if can_character_build(bp_id, c["skills"], skill_reqs)
            ]
            if not skill_eligible:
                # Find which skills are missing
                reqs = skill_reqs.get(bp_id, [])
                missing_skills = []
                for skill_id, min_level in reqs:
                    if all(
                        c["skills"].get(skill_id, 0) < min_level for c in characters
                    ):
                        missing_skills.append((skill_id, min_level))
                bp["unassignable_reason"] = "No character has required skills"
                bp["missing_skill_reqs"] = missing_skills
            else:
                bp["unassignable_reason"] = "All eligible characters out of slots"
            unassignable.append(bp)

    return unassignable
