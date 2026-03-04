import math

from datetime import datetime, timedelta, timezone

from flask import jsonify
from flask import render_template
from flask import request
from flask import redirect, url_for
from flask import Blueprint
from flask_login import login_required, current_user
from sqlalchemy import select

from src.models.models import db, InvTypes, cached_locations, CachedBlueprint, IndustryActivityMaterials, IndustryActivityProducts, IndustryBlueprints
from src.constants import ESI_BASE_URL
from src.utils import esi_get, esi_headers, batch_type_names

BLUEPRINT_CACHE_MAX_AGE = timedelta(hours=24)


def _load_sde_manufacturing_data():
    """Load manufacturing activity materials and products into dicts for fast DFS lookups.

    Returns:
        materials_by_bp: {typeID: [(materialTypeID, quantity), ...]}
        products_by_product: {productTypeID: (blueprintTypeID, quantity)}
    """
    materials_by_bp = {}
    for row in db.session.execute(
        select(IndustryActivityMaterials)
        .where(IndustryActivityMaterials.activityID == 1)
    ).scalars():
        materials_by_bp.setdefault(row.typeID, []).append((row.materialTypeID, row.quantity))

    products_by_product = {}
    for row in db.session.execute(
        select(IndustryActivityProducts)
        .where(IndustryActivityProducts.activityID == 1)
    ).scalars():
        products_by_product[row.productTypeID] = (row.typeID, row.quantity)

    return materials_by_bp, products_by_product


class IndustryBlueprint(Blueprint):
    def __init__(self, name, import_name):
        super().__init__(name, import_name)
        self._add_routes()

    def _add_routes(self):
        self.add_url_rule('/industry', 'industry', login_required(self.get_industry), methods=['GET'])
        self.add_url_rule('/industry/blueprints', 'blueprints', login_required(self.get_blueprints), methods=['GET'])
        self.add_url_rule('/industry/blueprints/<int:type_id>/materials', 'blueprint_materials', login_required(self.get_blueprint_materials), methods=['GET'])
        self.add_url_rule('/industry/blueprints/refresh', 'blueprints_refresh', login_required(self.refresh_blueprints), methods=['POST'])
        self.add_url_rule('/industry/jobs', 'jobs', login_required(self.get_jobs), methods=['GET'])
        self.add_url_rule('/industry/calculator', 'calculator', login_required(self.get_calculator), methods=['GET'])
        self.add_url_rule('/industry/calculator/search', 'calculator_search', login_required(self.search_items), methods=['GET'])

    def get_industry(self):
        return render_template('industry.html')

    def get_blueprints(self):
        headers = esi_headers()
        char_id = current_user.character_id

        # Check cache
        cached_row = db.session.execute(
            select(CachedBlueprint.cached_at)
            .where(CachedBlueprint.character_id == char_id)
            .limit(1)
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if cached_row and (now - cached_row.replace(tzinfo=timezone.utc)) < BLUEPRINT_CACHE_MAX_AGE:
            # Serve from cache
            cached_at = cached_row.replace(tzinfo=timezone.utc)
            j = self._load_cached_blueprints(char_id)
        else:
            # Fetch from ESI and cache
            result = self._fetch_and_cache_blueprints(headers)
            if result is None:
                return jsonify({"error": "Failed to fetch blueprints info"}), 500
            j, cached_at = result

        # Batch resolve type names
        type_ids = {i['type_id'] for i in j if i.get('type_id')}
        type_names = batch_type_names(type_ids)

        # Batch resolve location names
        location_ids = {i['location_id'] for i in j if i.get('location_id')}
        location_names = self._resolve_location_names(location_ids, headers)

        for i in j:
            i['type_name'] = type_names.get(i['type_id'])
            i['location_name'] = location_names.get(i['location_id'], "Unknown Location")

        return render_template('blueprints.html', blueprints=j, cached_at=cached_at, now_utc=now)

    def _fetch_and_cache_blueprints(self, headers):
        """Fetch blueprints from ESI (with pagination), cache them, return (list_of_dicts, cached_at) or None on failure."""
        char_id = current_user.character_id
        url = f"{ESI_BASE_URL}/characters/{char_id}/blueprints"

        all_bps = []
        page = 1
        while True:
            status, data = esi_get(url, headers=headers, params={"page": page})
            if status != 200 or data is None:
                if page == 1:
                    return None
                break
            all_bps.extend(data)
            if len(data) < 1000:
                break
            page += 1

        now = datetime.now(timezone.utc)

        # Delete old cached rows for this character
        db.session.execute(
            CachedBlueprint.__table__.delete().where(CachedBlueprint.character_id == char_id)
        )

        # Bulk insert new rows
        new_rows = [
            CachedBlueprint(
                character_id=char_id,
                item_id=bp['item_id'],
                type_id=bp['type_id'],
                location_id=bp['location_id'],
                location_flag=bp['location_flag'],
                quantity=bp['quantity'],
                runs=bp['runs'],
                material_efficiency=bp['material_efficiency'],
                time_efficiency=bp['time_efficiency'],
                cached_at=now,
            )
            for bp in all_bps
        ]
        if new_rows:
            db.session.add_all(new_rows)
        db.session.commit()

        return all_bps, now

    def _load_cached_blueprints(self, character_id):
        """Load cached blueprints from DB and return as list of dicts."""
        rows = db.session.execute(
            select(CachedBlueprint).where(CachedBlueprint.character_id == character_id)
        ).scalars().all()
        return [
            {
                'item_id': r.item_id,
                'type_id': r.type_id,
                'location_id': r.location_id,
                'location_flag': r.location_flag,
                'quantity': r.quantity,
                'runs': r.runs,
                'material_efficiency': r.material_efficiency,
                'time_efficiency': r.time_efficiency,
            }
            for r in rows
        ]

    def refresh_blueprints(self):
        headers = esi_headers()
        self._fetch_and_cache_blueprints(headers)
        return redirect(url_for('industry.blueprints'))

    def get_blueprint_materials(self, type_id: int):
        blueprint = db.session.execute(
            select(InvTypes.typeName).where(InvTypes.typeID == type_id)
        ).scalar_one_or_none()

        # Parse top-level run count
        runs = max(1, request.args.get('runs', 1, type=int))

        # Pre-load SDE data for DFS
        materials_by_bp, products_by_product = _load_sde_manufacturing_data()

        # Discover all blueprints in the build tree
        tree_bp_ids = _discover_blueprints(type_id, set(), materials_by_bp, products_by_product)

        # Parse ME values from query params (me_<type_id>=<value>)
        me_levels = {}
        for bp_id in tree_bp_ids:
            val = request.args.get(f"me_{bp_id}", 0, type=int)
            me_levels[bp_id] = max(0, min(10, val))

        # Parse BPC max runs from query params (bpc_<type_id>=<value>, 0=BPO)
        bpc_runs = {}
        for bp_id in tree_bp_ids:
            val = request.args.get(f"bpc_{bp_id}", 0, type=int)
            bpc_runs[bp_id] = max(0, val)

        # Batch resolve blueprint names
        bp_names = batch_type_names(tree_bp_ids)

        tree_blueprints = sorted(
            [{"type_id": bid, "name": bp_names.get(bid, f"Unknown ({bid})"), "me": me_levels.get(bid, 0), "bpc_max_runs": bpc_runs.get(bid, 0)} for bid in tree_bp_ids],
            key=lambda b: b["name"]
        )

        raw_materials = _resolve_material_tree(type_id, {}, me_levels, materials_by_bp, products_by_product)

        # Scale raw materials by top-level run count
        if runs > 1:
            raw_materials = {tid: qty * runs for tid, qty in raw_materials.items()}

        # Compute runs needed per blueprint in the tree
        runs_needed = _compute_runs_needed(type_id, me_levels, runs, materials_by_bp, products_by_product)

        # Build BPC info list (only for blueprints set to BPC mode)
        bpc_info = []
        for bp in tree_blueprints:
            bp_id = bp["type_id"]
            max_runs = bpc_runs.get(bp_id, 0)
            if max_runs > 0:
                total_runs = runs_needed.get(bp_id, 0)
                bpc_count = math.ceil(total_runs / max_runs) if total_runs > 0 else 0
                bpc_info.append({
                    "name": bp["name"],
                    "total_runs": total_runs,
                    "max_runs": max_runs,
                    "bpc_count": bpc_count,
                })

        # Batch resolve material names
        material_names = batch_type_names(set(raw_materials.keys()))

        materials = sorted(
            [{"name": material_names.get(tid, f"Unknown ({tid})"), "quantity": qty} for tid, qty in raw_materials.items()],
            key=lambda m: m["name"]
        )

        return render_template('blueprint_materials.html', blueprint_name=blueprint, materials=materials, tree_blueprints=tree_blueprints, type_id=type_id, runs=runs, bpc_info=bpc_info)

    def search_items(self):
        q = request.args.get('q', '', type=str).strip()
        if len(q) < 2:
            return jsonify([])
        results = db.session.execute(
            select(InvTypes.typeID, InvTypes.typeName)
            .join(IndustryActivityProducts, IndustryActivityProducts.productTypeID == InvTypes.typeID)
            .where(IndustryActivityProducts.activityID == 1)
            .where(InvTypes.typeName.ilike(f'%{q}%'))
            .where(InvTypes.published == True)
            .limit(15)
        ).all()
        return jsonify([{"type_id": r.typeID, "name": r.typeName} for r in results])

    def get_calculator(self):
        product_type_id = request.args.get('product_type_id', 0, type=int)
        desired_qty = request.args.get('quantity', 1, type=int)
        desired_qty = max(1, desired_qty)
        char_id = current_user.character_id

        # Check once whether this user has any cached blueprints
        has_blueprints = db.session.execute(
            select(CachedBlueprint.id)
            .where(CachedBlueprint.character_id == char_id)
            .limit(1)
        ).scalar_one_or_none() is not None

        if not product_type_id:
            return render_template('calculator.html', product=None, has_blueprints=has_blueprints)

        # Look up product name
        product_name = db.session.execute(
            select(InvTypes.typeName).where(InvTypes.typeID == product_type_id)
        ).scalar_one_or_none()

        # Reverse-lookup: product -> blueprint
        bp_product = db.session.execute(
            select(IndustryActivityProducts)
            .where(IndustryActivityProducts.productTypeID == product_type_id)
            .where(IndustryActivityProducts.activityID == 1)
            .limit(1)
        ).scalar_one_or_none()

        if not bp_product:
            return render_template('calculator.html', product=None, has_blueprints=has_blueprints,
                                   error=f"No manufacturing blueprint found for this item.")

        top_bp_id = bp_product.typeID
        product_qty_per_run = bp_product.quantity
        top_runs = math.ceil(desired_qty / product_qty_per_run)

        # Pre-load SDE data for DFS
        materials_by_bp, products_by_product = _load_sde_manufacturing_data()

        # Discover full blueprint tree
        tree_bp_ids = _discover_blueprints(top_bp_id, set(), materials_by_bp, products_by_product)

        # Query user's cached blueprints for these types
        cached_bps = db.session.execute(
            select(CachedBlueprint)
            .where(CachedBlueprint.character_id == char_id)
            .where(CachedBlueprint.type_id.in_(tree_bp_ids))
        ).scalars().all()

        # Build ownership map: {type_id: {bpos: [...], bpcs: [...]}}
        ownership = {}
        for bp in cached_bps:
            entry = ownership.setdefault(bp.type_id, {"bpos": [], "bpcs": []})
            if bp.quantity == -1:
                entry["bpos"].append(bp)
            else:
                entry["bpcs"].append(bp)

        # Auto-populate ME from best BPO, allow query param overrides
        me_levels = {}
        for bp_id in tree_bp_ids:
            override = request.args.get(f'me_{bp_id}', None, type=int)
            if override is not None:
                me_levels[bp_id] = max(0, min(10, override))
            else:
                own = ownership.get(bp_id, {"bpos": []})
                if own["bpos"]:
                    me_levels[bp_id] = max(b.material_efficiency for b in own["bpos"])
                else:
                    me_levels[bp_id] = 0

        # Compute runs needed per blueprint
        runs_needed = _compute_runs_needed(top_bp_id, me_levels, top_runs, materials_by_bp, products_by_product)

        # Resolve raw materials
        raw_materials = _resolve_material_tree(top_bp_id, {}, me_levels, materials_by_bp, products_by_product)
        if top_runs > 1:
            raw_materials = {tid: qty * top_runs for tid, qty in raw_materials.items()}

        # Query maxProductionLimit for copy planning
        max_prod_limits = {}
        if tree_bp_ids:
            rows = db.session.execute(
                select(IndustryBlueprints.typeID, IndustryBlueprints.maxProductionLimit)
                .where(IndustryBlueprints.typeID.in_(tree_bp_ids))
            ).all()
            max_prod_limits = {r.typeID: r.maxProductionLimit for r in rows}

        # Batch resolve names
        all_type_ids = tree_bp_ids | set(raw_materials.keys())
        type_names = batch_type_names(all_type_ids)

        # Build status list per blueprint
        bp_statuses = []
        for bp_id in sorted(tree_bp_ids, key=lambda x: type_names.get(x, "")):
            own = ownership.get(bp_id, {"bpos": [], "bpcs": []})
            needed = runs_needed.get(bp_id, 0)
            max_prod = max_prod_limits.get(bp_id, 0) or 0

            if own["bpos"]:
                status = "owned_bpo"
                best_te = max(b.time_efficiency for b in own["bpos"])
                bpc_runs_available = sum(b.runs for b in own["bpcs"])
                runs_shortfall = 0
                copy_jobs = math.ceil(needed / max_prod) if max_prod > 0 else 0
            elif own["bpcs"]:
                status = "owned_bpc_only"
                best_te = 0
                bpc_runs_available = sum(b.runs for b in own["bpcs"])
                runs_shortfall = max(0, needed - bpc_runs_available)
                copy_jobs = 0
            else:
                status = "missing"
                best_te = 0
                bpc_runs_available = 0
                runs_shortfall = needed
                copy_jobs = 0

            bp_statuses.append({
                "type_id": bp_id,
                "name": type_names.get(bp_id, f"Unknown ({bp_id})"),
                "status": status,
                "me": me_levels.get(bp_id, 0),
                "te": best_te,
                "runs_needed": needed,
                "bpc_runs_available": bpc_runs_available,
                "runs_shortfall": runs_shortfall,
                "copy_jobs": copy_jobs,
                "max_prod_limit": max_prod,
                "you_have": _describe_ownership(own),
            })

        # Sort materials
        materials = sorted(
            [{"name": type_names.get(tid, f"Unknown ({tid})"), "quantity": qty} for tid, qty in raw_materials.items()],
            key=lambda m: m["name"]
        )

        # Summary counts
        owned_bpo_count = sum(1 for b in bp_statuses if b["status"] == "owned_bpo")
        bpc_only_count = sum(1 for b in bp_statuses if b["status"] == "owned_bpc_only")
        missing_count = sum(1 for b in bp_statuses if b["status"] == "missing")

        return render_template('calculator.html',
            product={"type_id": product_type_id, "name": product_name},
            desired_qty=desired_qty,
            product_qty_per_run=product_qty_per_run,
            top_runs=top_runs,
            bp_statuses=bp_statuses,
            materials=materials,
            me_levels=me_levels,
            owned_bpo_count=owned_bpo_count,
            bpc_only_count=bpc_only_count,
            missing_count=missing_count,
            has_blueprints=has_blueprints,
        )

    def get_jobs(self):
        status, data = esi_get(f"{ESI_BASE_URL}/characters/{current_user.character_id}/industry/jobs")
        if status == 200:
            return render_template('jobs.html', jobs_info=data)
        return jsonify({"error": "Failed to fetch jobs info"}), status or 500

    def _resolve_location_names(self, location_ids: set, headers: dict) -> dict:
        """Return a {location_id: name} map for all given IDs, using cache then ESI."""
        if not location_ids:
            return {}

        cached = db.session.execute(
            select(cached_locations).where(cached_locations.location_id.in_(location_ids))
        ).scalars().all()
        names = {row.location_id: row.location_name for row in cached}

        missing = location_ids - names.keys()
        new_entries = []
        for loc_id in missing:
            name = self._fetch_location_name(loc_id, headers)
            names[loc_id] = name
            new_entries.append(cached_locations(location_id=loc_id, location_name=name))  # type: ignore[call-arg]

        if new_entries:
            db.session.add_all(new_entries)
            db.session.commit()

        return names

    def _fetch_location_name(self, location_id: int, headers: dict) -> str:
        # NPC stations: 60000000–63999999
        if 60_000_000 <= location_id <= 63_999_999:
            url = f"{ESI_BASE_URL}/universe/stations/{location_id}/"
            key = "name"
        # Player-owned structures: IDs > 1 trillion
        elif location_id > 1_000_000_000_000:
            url = f"{ESI_BASE_URL}/universe/structures/{location_id}/"
            key = "name"
        # Solar systems: 30000000–39999999
        elif 30_000_000 <= location_id <= 39_999_999:
            url = f"{ESI_BASE_URL}/universe/systems/{location_id}/"
            key = "name"
        else:
            return "Unknown Location"

        status, data = esi_get(url, headers=headers)
        if status == 200 and data:
            return data.get(key, "Unknown Location")
        return "Unknown Location"


# --- DFS helpers (pure dict lookups, no DB calls) ---

def _discover_blueprints(blueprint_type_id: int, discovered: set,
                         materials_by_bp: dict, products_by_product: dict) -> set:
    """DFS to find all blueprint type IDs in the build tree."""
    if blueprint_type_id in discovered:
        return discovered
    discovered.add(blueprint_type_id)
    for material_type_id, _ in materials_by_bp.get(blueprint_type_id, []):
        sub = products_by_product.get(material_type_id)
        if sub:
            _discover_blueprints(sub[0], discovered, materials_by_bp, products_by_product)
    return discovered


def _resolve_material_tree(blueprint_type_id: int, cache: dict, me_levels: dict,
                           materials_by_bp: dict, products_by_product: dict) -> dict:
    """DFS over the manufacturing tree. Returns {material_type_id: quantity} for 1 run.
    Results are memoized in cache to avoid redundant traversal of shared sub-components.
    me_levels maps blueprint_type_id -> ME level (0-10) for material reduction."""
    if blueprint_type_id in cache:
        return cache[blueprint_type_id]

    cache[blueprint_type_id] = {}  # cycle sentinel

    me = me_levels.get(blueprint_type_id, 0)

    result = {}
    for material_type_id, base_qty in materials_by_bp.get(blueprint_type_id, []):
        adjusted_qty = max(1, math.ceil(base_qty * (1 - me / 100)))

        sub = products_by_product.get(material_type_id)
        if sub:
            sub_bp_id, sub_product_qty = sub
            sub_tree = _resolve_material_tree(sub_bp_id, cache, me_levels, materials_by_bp, products_by_product)
            runs_needed = math.ceil(adjusted_qty / sub_product_qty)
            for raw_id, raw_qty in sub_tree.items():
                result[raw_id] = result.get(raw_id, 0) + raw_qty * runs_needed
        else:
            result[material_type_id] = result.get(material_type_id, 0) + adjusted_qty

    cache[blueprint_type_id] = result
    return result


def _compute_runs_needed(blueprint_type_id, me_levels, top_runs,
                         materials_by_bp, products_by_product):
    """Returns {bp_type_id: total_runs_needed} across the full tree."""
    runs_needed = {blueprint_type_id: top_runs}
    _runs_dfs(blueprint_type_id, top_runs, me_levels, runs_needed, materials_by_bp, products_by_product)
    return runs_needed


def _runs_dfs(blueprint_type_id, parent_runs, me_levels, runs_needed,
              materials_by_bp, products_by_product):
    """Recursive helper: propagate run counts down the build tree."""
    me = me_levels.get(blueprint_type_id, 0)

    for material_type_id, base_qty in materials_by_bp.get(blueprint_type_id, []):
        adjusted_qty = max(1, math.ceil(base_qty * (1 - me / 100)))

        sub = products_by_product.get(material_type_id)
        if sub:
            sub_bp_id, sub_product_qty = sub
            child_runs = math.ceil(adjusted_qty * parent_runs / sub_product_qty)
            runs_needed[sub_bp_id] = runs_needed.get(sub_bp_id, 0) + child_runs
            _runs_dfs(sub_bp_id, child_runs, me_levels, runs_needed, materials_by_bp, products_by_product)


def _describe_ownership(own):
    parts = []
    if own["bpos"]:
        best = max(own["bpos"], key=lambda b: b.material_efficiency)
        parts.append(f"BPO (ME {best.material_efficiency})")
    if own["bpcs"]:
        total_runs = sum(b.runs for b in own["bpcs"])
        count = len(own["bpcs"])
        parts.append(f"{count} BPC{'s' if count > 1 else ''} ({total_runs} runs)")
    return " + ".join(parts) if parts else None
