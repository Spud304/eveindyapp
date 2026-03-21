import logging
import math

from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

from flask import jsonify
from flask import render_template
from flask import request
from flask import redirect, url_for
from flask import Blueprint
from flask_login import login_required, current_user
from sqlalchemy import select

from src.models.models import (
    db,
    InvTypes,
    CachedLocations,
    CachedBlueprint,
    IndustryActivityProducts,
    IndustryBlueprints,
    MapSolarSystems,
)
from src.constants import ESI_BASE_URL
from celery.result import AsyncResult
from src.utils import (
    esi_get,
    batch_type_names,
    batch_market_info,
    get_manufacturing_cost_index,
    search_systems as _search_systems,
)
from src.tasks import fetch_blueprints_task
from src.config import load_user_config
from src.industry_utils import (
    load_rig_data,
    load_sde_manufacturing_data,
    load_activity_times,
    load_type_group_category_maps,
    pick_best_station,
    classify_product_for_rig,
    load_blueprint_skill_requirements,
    load_character_skills,
    compute_character_capabilities,
    get_character_names,
    assign_jobs_to_characters,
)


BLUEPRINT_CACHE_MAX_AGE = timedelta(hours=24)


class IndustryBlueprint(Blueprint):
    def __init__(self, name, import_name):
        super().__init__(name, import_name)
        self._add_routes()

    def _add_routes(self):
        self.add_url_rule(
            "/industry", "industry", login_required(self.get_industry), methods=["GET"]
        )
        self.add_url_rule(
            "/industry/blueprints",
            "blueprints",
            login_required(self.get_blueprints),
            methods=["GET"],
        )
        self.add_url_rule(
            "/industry/blueprints/<int:type_id>/materials",
            "blueprint_materials",
            login_required(self.get_blueprint_materials),
            methods=["GET"],
        )
        self.add_url_rule(
            "/industry/blueprints/refresh",
            "blueprints_refresh",
            login_required(self.refresh_blueprints),
            methods=["POST"],
        )
        self.add_url_rule(
            "/industry/blueprints/status",
            "blueprints_status",
            login_required(self.blueprints_status),
            methods=["GET"],
        )
        self.add_url_rule(
            "/industry/jobs", "jobs", login_required(self.get_jobs), methods=["GET"]
        )
        self.add_url_rule(
            "/industry/calculator",
            "calculator",
            login_required(self.get_calculator),
            methods=["GET"],
        )
        self.add_url_rule(
            "/industry/calculator/search",
            "calculator_search",
            login_required(self.search_items),
            methods=["GET"],
        )
        self.add_url_rule(
            "/industry/calculator/search_systems",
            "calculator_search_systems",
            login_required(self.search_systems),
            methods=["GET"],
        )

    def get_industry(self):
        return render_template("industry.html")

    def get_blueprints(self):
        char_id = current_user.character_id
        now = datetime.now(timezone.utc)
        refreshing = False

        # Check cache
        cached_row = db.session.execute(
            select(CachedBlueprint.cached_at)
            .where(CachedBlueprint.character_id == char_id)
            .limit(1)
        ).scalar_one_or_none()

        has_cache = cached_row is not None
        cache_fresh = (
            has_cache
            and (now - cached_row.replace(tzinfo=timezone.utc))
            < BLUEPRINT_CACHE_MAX_AGE
        )

        if not cache_fresh:
            # Kick off background fetch
            task = self._start_blueprint_task(char_id)
            refreshing = task is not None

        if not has_cache:
            # No cache at all — show loading page
            task_id = request.args.get("task_id") or (task.id if refreshing else None)
            return render_template(
                "blueprints.html",
                blueprints=[],
                cached_at=None,
                now_utc=now,
                loading=True,
                task_id=task_id,
            )

        # Serve from cache (possibly stale while refreshing)
        cached_at = cached_row.replace(tzinfo=timezone.utc)
        j = self._load_cached_blueprints(char_id)

        # Batch resolve type names
        type_ids = {i["type_id"] for i in j if i.get("type_id")}
        type_names = batch_type_names(type_ids)

        # Resolve location names from cache only (locations resolved by task)
        location_ids = {i["location_id"] for i in j if i.get("location_id")}
        location_names = self._resolve_cached_location_names(location_ids)

        for i in j:
            i["type_name"] = type_names.get(i["type_id"])
            i["location_name"] = location_names.get(
                i["location_id"], "Unknown Location"
            )

        task_id = request.args.get("task_id") or (task.id if refreshing else None)
        return render_template(
            "blueprints.html",
            blueprints=j,
            cached_at=cached_at,
            now_utc=now,
            refreshing=refreshing,
            task_id=task_id,
        )

    def _start_blueprint_task(self, char_id):
        """Dispatch a Celery task to fetch blueprints in the background."""
        try:
            task = fetch_blueprints_task.delay(char_id)
            return task
        except Exception:
            logger.exception("Failed to dispatch blueprint fetch task")
            return None

    def _load_cached_blueprints(self, character_id):
        """Load cached blueprints from DB and return as list of dicts."""
        rows = (
            db.session.execute(
                select(CachedBlueprint).where(
                    CachedBlueprint.character_id == character_id
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "item_id": r.item_id,
                "type_id": r.type_id,
                "location_id": r.location_id,
                "location_flag": r.location_flag,
                "quantity": r.quantity,
                "runs": r.runs,
                "material_efficiency": r.material_efficiency,
                "time_efficiency": r.time_efficiency,
            }
            for r in rows
        ]

    def refresh_blueprints(self):
        char_id = current_user.character_id
        task = self._start_blueprint_task(char_id)
        if task is None:
            return jsonify({"error": "Failed to start blueprint refresh"}), 500
        return redirect(url_for("industry.blueprints", task_id=task.id))

    def blueprints_status(self):
        """Poll endpoint: returns task state as JSON."""
        task_id = request.args.get("task_id")
        if not task_id:
            return jsonify({"state": "UNKNOWN"})
        result = AsyncResult(task_id)
        response = {"state": result.state}
        if result.state == "FAILURE":
            response["error"] = str(result.result)
        return jsonify(response)

    def get_blueprint_materials(self, type_id: int):
        blueprint = db.session.execute(
            select(InvTypes.typeName).where(InvTypes.typeID == type_id)
        ).scalar_one_or_none()

        # Parse top-level run count
        runs = max(1, request.args.get("runs", 1, type=int))

        # Pre-load SDE data for DFS
        materials_by_bp, products_by_product, _bp_to_product = (
            load_sde_manufacturing_data()
        )

        # Discover all blueprints in the build tree
        tree_bp_ids = _discover_blueprints(
            type_id, set(), materials_by_bp, products_by_product
        )

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
            [
                {
                    "type_id": bid,
                    "name": bp_names.get(bid, f"Unknown ({bid})"),
                    "me": me_levels.get(bid, 0),
                    "bpc_max_runs": bpc_runs.get(bid, 0),
                }
                for bid in tree_bp_ids
            ],
            key=lambda b: b["name"],
        )

        raw_materials = _resolve_material_tree(
            type_id, {}, me_levels, materials_by_bp, products_by_product
        )

        # Scale raw materials by top-level run count
        if runs > 1:
            raw_materials = {tid: qty * runs for tid, qty in raw_materials.items()}

        # Compute runs needed per blueprint in the tree
        runs_needed = _compute_runs_needed(
            type_id, me_levels, runs, materials_by_bp, products_by_product
        )

        # Build BPC info list (only for blueprints set to BPC mode)
        bpc_info = []
        for bp in tree_blueprints:
            bp_id = bp["type_id"]
            max_runs = bpc_runs.get(bp_id, 0)
            if max_runs > 0:
                total_runs = runs_needed.get(bp_id, 0)
                bpc_count = math.ceil(total_runs / max_runs) if total_runs > 0 else 0
                bpc_info.append(
                    {
                        "name": bp["name"],
                        "total_runs": total_runs,
                        "max_runs": max_runs,
                        "bpc_count": bpc_count,
                    }
                )

        # Batch resolve material names
        material_names = batch_type_names(set(raw_materials.keys()))

        materials = sorted(
            [
                {"name": material_names.get(tid, f"Unknown ({tid})"), "quantity": qty}
                for tid, qty in raw_materials.items()
            ],
            key=lambda m: m["name"],
        )

        return render_template(
            "blueprint_materials.html",
            blueprint_name=blueprint,
            materials=materials,
            tree_blueprints=tree_blueprints,
            type_id=type_id,
            runs=runs,
            bpc_info=bpc_info,
        )

    def search_items(self):
        q = request.args.get("q", "", type=str).strip()
        if len(q) < 2:
            return jsonify([])
        results = db.session.execute(
            select(InvTypes.typeID, InvTypes.typeName)
            .join(
                IndustryActivityProducts,
                IndustryActivityProducts.productTypeID == InvTypes.typeID,
            )
            .where(IndustryActivityProducts.activityID == 1)
            .where(InvTypes.typeName.ilike(f"%{q}%"))
            .where(InvTypes.published)
            .limit(15)
        ).all()
        return jsonify([{"type_id": r.typeID, "name": r.typeName} for r in results])

    def search_systems(self):
        q = request.args.get("q", "", type=str).strip()
        return jsonify(_search_systems(q))

    def get_calculator(self):
        product_type_id = request.args.get("product_type_id", 0, type=int)
        desired_qty = request.args.get("quantity", 1, type=int)
        desired_qty = max(1, desired_qty)
        char_id = current_user.character_id

        # Load user config
        config = load_user_config(char_id)
        stations = config.get("stations", [])
        blacklist = set(config.get("blacklist", []))

        # Check once whether this user has any cached blueprints
        has_blueprints = (
            db.session.execute(
                select(CachedBlueprint.id)
                .where(CachedBlueprint.character_id == char_id)
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

        # Read build settings from config
        use_char_skills = config.get("use_character_skills", False)
        characters = []
        mfg_skill_reqs = {}
        copy_skill_reqs = {}
        if use_char_skills:
            from src.user import get_linked_character_ids
            char_ids = get_linked_character_ids(current_user)
            char_skills_map = load_character_skills(char_ids)
            char_names = get_character_names(char_ids)
            mfg_skill_reqs, copy_skill_reqs = load_blueprint_skill_requirements()
            for cid in char_ids:
                skills = char_skills_map.get(cid, {})
                caps = compute_character_capabilities(skills)
                characters.append({
                    "char_id": cid,
                    "char_name": char_names.get(cid, f"Character {cid}"),
                    "skills": skills,
                    **caps,
                })
            build_slots = sum(c["mfg_slots"] for c in characters)
            copy_slots = sum(c["copy_slots"] for c in characters)
            industry_level = max((c["industry_level"] for c in characters), default=5)
            adv_industry_level = max((c["adv_industry_level"] for c in characters), default=5)
        else:
            build_slots = config.get("build_slots", 10)
            copy_slots = config.get("copy_slots", 10)
            industry_level = config.get("industry_level", 5)
            adv_industry_level = config.get("adv_industry_level", 5)

        default_timeframe = config.get("default_timeframe_hours")

        # Read timeframe from query params (overrides config default)
        timeframe_hours = request.args.get("timeframe_hours", None, type=float)
        if timeframe_hours is None and default_timeframe:
            timeframe_hours = default_timeframe
        timeframe_seconds = timeframe_hours * 3600 if timeframe_hours else None
        suggest_mode = request.args.get("suggest_mode", "none")

        if not product_type_id:
            return render_template(
                "calculator.html",
                product=None,
                has_blueprints=has_blueprints,
                stations=stations,
                build_slots=build_slots,
                copy_slots=copy_slots,
                timeframe_hours=timeframe_hours,
            )

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
            return render_template(
                "calculator.html",
                product=None,
                has_blueprints=has_blueprints,
                stations=stations,
                error="No manufacturing blueprint found for this item.",
            )

        top_bp_id = bp_product.typeID
        product_qty_per_run = bp_product.quantity
        top_runs = math.ceil(desired_qty / product_qty_per_run)

        # Pre-load SDE data for DFS
        materials_by_bp, products_by_product, bp_to_product = (
            load_sde_manufacturing_data()
        )

        # Load classification maps
        type_to_group, group_to_category = load_type_group_category_maps()

        # Pre-fetch security status for all station systems
        system_ids = {s["system_id"] for s in stations if s.get("system_id")}
        system_securities = {}
        if system_ids:
            sec_rows = db.session.execute(
                select(MapSolarSystems.solarSystemID, MapSolarSystems.security).where(
                    MapSolarSystems.solarSystemID.in_(system_ids)
                )
            ).all()
            system_securities = {r.solarSystemID: r.security for r in sec_rows}

        # Load rig data from SDE
        rig_data = load_rig_data()

        # Load activity times (mfg + copy) from SDE
        activity_times = load_activity_times()

        # Discover full blueprint tree (respecting blacklist)
        tree_bp_ids = _discover_blueprints(
            top_bp_id, set(), materials_by_bp, products_by_product, blacklist
        )

        # Build structure_me_by_bp and structure_te_by_bp: classify each blueprint's product, pick best station
        structure_me_by_bp = {}
        structure_te_by_bp = {}
        bp_rig_categories = {}
        bp_station_assignments = {}
        for bp_id in tree_bp_ids:
            prod_id = bp_to_product.get(bp_id)
            if prod_id:
                rig_cat = classify_product_for_rig(
                    prod_id, type_to_group, group_to_category
                )
            else:
                rig_cat = None
            bp_rig_categories[bp_id] = rig_cat

            if rig_cat and stations:
                best_station, best_me, best_te = pick_best_station(
                    stations, rig_cat, system_securities, rig_data
                )
                structure_me_by_bp[bp_id] = best_me
                structure_te_by_bp[bp_id] = best_te
                bp_station_assignments[bp_id] = best_station
            else:
                structure_me_by_bp[bp_id] = 0
                structure_te_by_bp[bp_id] = 1.0
                bp_station_assignments[bp_id] = None

        # Query user's cached blueprints for these types
        cached_bps = (
            db.session.execute(
                select(CachedBlueprint)
                .where(CachedBlueprint.character_id == char_id)
                .where(CachedBlueprint.type_id.in_(tree_bp_ids))
            )
            .scalars()
            .all()
        )

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
            override = request.args.get(f"me_{bp_id}", None, type=int)
            if override is not None:
                me_levels[bp_id] = max(0, min(10, override))
            else:
                own = ownership.get(bp_id, {"bpos": []})
                if own["bpos"]:
                    me_levels[bp_id] = max(b.material_efficiency for b in own["bpos"])
                else:
                    me_levels[bp_id] = 0

        # Parse extra BPOs per blueprint
        extra_bpos = {}
        for bp_id in tree_bp_ids:
            val = request.args.get(f"extra_bpos_{bp_id}", 0, type=int)
            extra_bpos[bp_id] = max(0, val)

        # Parse bought BPCs per blueprint
        bought_bpcs = {}
        for bp_id in tree_bp_ids:
            val = request.args.get(f"bought_bpcs_{bp_id}", 0, type=int)
            bought_bpcs[bp_id] = max(0, val)

        # Compute runs needed per blueprint
        runs_needed = _compute_runs_needed(
            top_bp_id,
            me_levels,
            top_runs,
            materials_by_bp,
            products_by_product,
            blacklist,
            structure_me_by_bp,
        )

        # Resolve raw materials
        raw_materials = _resolve_material_tree(
            top_bp_id,
            {},
            me_levels,
            materials_by_bp,
            products_by_product,
            blacklist,
            structure_me_by_bp,
        )
        if top_runs > 1:
            raw_materials = {tid: qty * top_runs for tid, qty in raw_materials.items()}

        # Query maxProductionLimit for copy planning
        max_prod_limits = {}
        if tree_bp_ids:
            rows = db.session.execute(
                select(
                    IndustryBlueprints.typeID, IndustryBlueprints.maxProductionLimit
                ).where(IndustryBlueprints.typeID.in_(tree_bp_ids))
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

            assigned_station = bp_station_assignments.get(bp_id)

            # Compute build strategy (BPO vs BPC)
            bp_times = activity_times.get(bp_id, (0, 0))
            mfg_time_per_run = bp_times[0]
            copy_time_per_run = bp_times[1]
            bp_mats = materials_by_bp.get(bp_id, [])
            strategy = _compute_build_strategy(
                runs_needed=needed,
                max_prod_limit=max_prod,
                te=best_te,
                mfg_time_per_run=mfg_time_per_run,
                copy_time_per_run=copy_time_per_run,
                mfg_slots=build_slots,
                bp_materials=bp_mats,
                me=me_levels.get(bp_id, 0),
                struct_me=structure_me_by_bp.get(bp_id, 0),
                timeframe_seconds=timeframe_seconds,
                num_bpos=1 + extra_bpos.get(bp_id, 0),
                bought_bpcs=bought_bpcs.get(bp_id, 0),
                struct_te=structure_te_by_bp.get(bp_id, 1.0),
                industry_level=industry_level,
                adv_industry_level=adv_industry_level,
            )

            bp_statuses.append(
                {
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
                    "station_name": assigned_station["name"]
                    if assigned_station
                    else None,
                    "structure_me": structure_me_by_bp.get(bp_id, 0),
                    "extra_bpos": extra_bpos.get(bp_id, 0),
                    "bought_bpcs": bought_bpcs.get(bp_id, 0),
                    "build_strategy": strategy,
                }
            )

        # Sort materials
        materials = sorted(
            [
                {"name": type_names.get(tid, f"Unknown ({tid})"), "quantity": qty}
                for tid, qty in raw_materials.items()
            ],
            key=lambda m: m["name"],
        )
        # Batch fetch prices (average + adjusted) for all materials
        all_material_ids = set(raw_materials.keys())
        # Also need adjusted prices for EIV computation (base qty materials for each BP)
        eiv_material_ids = set()
        for bp_id in tree_bp_ids:
            for mat_id, _ in materials_by_bp.get(bp_id, []):
                eiv_material_ids.add(mat_id)
        all_price_ids = all_material_ids | eiv_material_ids
        prices, adjusted_prices = batch_market_info(all_price_ids)

        name_to_type_id = {name: tid for tid, name in type_names.items()}
        for m in materials:
            type_id = name_to_type_id.get(m["name"])
            price = prices.get(type_id) if type_id else None
            m["unit_price"] = price
            m["total_price"] = price * m["quantity"] if price else None

        total_material_cost = sum(
            (m["total_price"] for m in materials if m["total_price"] is not None), 0.0
        )

        # Compute job costs per blueprint using station assignments
        SCC_SURCHARGE = 0.015

        # Pre-fetch cost indices for all unique station system_ids
        cost_indices = {}
        for station in stations:
            sid = station.get("system_id")
            if sid and sid not in cost_indices:
                cost_indices[sid] = get_manufacturing_cost_index(sid)

        for bp in bp_statuses:
            bp_id = bp["type_id"]
            assigned_station = bp_station_assignments.get(bp_id)
            if assigned_station:
                sys_id = assigned_station.get("system_id")
                facility_tax = assigned_station.get("facility_tax", 10.0)
                system_cost_index = cost_indices.get(sys_id, 0.0) if sys_id else 0.0
            else:
                facility_tax = 0.0
                system_cost_index = 0.0

            # EIV = sum of (adjusted_price * base_qty) for ME 0 materials
            eiv_per_run = 0.0
            for mat_id, base_qty in materials_by_bp.get(bp_id, []):
                eiv_per_run += adjusted_prices.get(mat_id, 0.0) * base_qty
            bp["eiv_per_run"] = eiv_per_run
            bp["job_cost"] = (
                eiv_per_run
                * bp["runs_needed"]
                * (system_cost_index + facility_tax / 100 + SCC_SURCHARGE)
            )

        total_job_cost = sum(bp["job_cost"] for bp in bp_statuses)
        grand_total = total_material_cost + total_job_cost

        # Summary counts
        owned_bpo_count = sum(1 for b in bp_statuses if b["status"] == "owned_bpo")
        bpc_only_count = sum(1 for b in bp_statuses if b["status"] == "owned_bpc_only")
        missing_count = sum(1 for b in bp_statuses if b["status"] == "missing")

        # Compute blueprint depths for phase-aware timing
        depths = _compute_blueprint_depths(
            top_bp_id, materials_by_bp, products_by_product, blacklist
        )
        for bp in bp_statuses:
            bp["depth"] = depths.get(bp["type_id"], 0)

        # Auto-apply bought BPCs when suggest_mode == 'bpc'
        if suggest_mode == "bpc" and timeframe_seconds:
            for bp in bp_statuses:
                s = bp["build_strategy"]
                if s["recommended"] == "bpc" and not bought_bpcs.get(bp["type_id"]):
                    suggested = _suggest_buy_bpcs(
                        s["num_bpcs"],
                        s["num_bpos"],
                        s.get("bpc_copy_time", 0) / max(s.get("copies_to_make", 1), 1)
                        if s.get("copies_to_make", 0) > 0
                        else 0,
                        s["bpc_mfg_time"],
                        timeframe_seconds,
                    )
                    if suggested and suggested > 0:
                        bp["bought_bpcs"] = suggested
                        # Recompute strategy with new bought_bpcs
                        bp_times = activity_times.get(bp["type_id"], (0, 0))
                        bp["build_strategy"] = _compute_build_strategy(
                            runs_needed=bp["runs_needed"],
                            max_prod_limit=bp["max_prod_limit"],
                            te=bp["te"],
                            mfg_time_per_run=bp_times[0],
                            copy_time_per_run=bp_times[1],
                            mfg_slots=build_slots,
                            bp_materials=materials_by_bp.get(bp["type_id"], []),
                            me=bp["me"],
                            struct_me=bp["structure_me"],
                            timeframe_seconds=timeframe_seconds,
                            num_bpos=1 + extra_bpos.get(bp["type_id"], 0),
                            bought_bpcs=suggested,
                            struct_te=structure_te_by_bp.get(bp["type_id"], 1.0),
                            industry_level=industry_level,
                            adv_industry_level=adv_industry_level,
                        )

        # Character-aware job assignment
        unassignable_warnings = []
        if use_char_skills and characters:
            # Group bps by depth for per-phase assignment
            phases_by_depth = {}
            for bp in bp_statuses:
                d = bp.get("depth", 0)
                phases_by_depth.setdefault(d, []).append(bp)

            max_depth = max(phases_by_depth.keys()) if phases_by_depth else 0
            for depth in range(max_depth, -1, -1):
                phase_bps = phases_by_depth.get(depth, [])
                if not phase_bps:
                    continue
                # Assign manufacturing jobs
                unassignable = assign_jobs_to_characters(phase_bps, characters, mfg_skill_reqs, job_type="mfg")
                unassignable_warnings.extend(unassignable)

                # Assign copy jobs for BPC-mode blueprints
                copy_bps = [bp for bp in phase_bps if bp["build_strategy"]["recommended"] == "bpc" and bp["build_strategy"].get("copies_to_make", 0) > 0]
                if copy_bps:
                    assign_jobs_to_characters(copy_bps, characters, copy_skill_reqs, job_type="copy")

            # Recompute strategy using assigned character's skill levels
            for bp in bp_statuses:
                ac = bp.get("assigned_character")
                if ac:
                    char = next((c for c in characters if c["char_id"] == ac["char_id"]), None)
                    if char:
                        bp_times = activity_times.get(bp["type_id"], (0, 0))
                        bp["build_strategy"] = _compute_build_strategy(
                            runs_needed=bp["runs_needed"],
                            max_prod_limit=bp["max_prod_limit"],
                            te=bp["te"],
                            mfg_time_per_run=bp_times[0],
                            copy_time_per_run=bp_times[1],
                            mfg_slots=char["mfg_slots"],
                            bp_materials=materials_by_bp.get(bp["type_id"], []),
                            me=bp["me"],
                            struct_me=bp["structure_me"],
                            timeframe_seconds=timeframe_seconds,
                            num_bpos=1 + extra_bpos.get(bp["type_id"], 0),
                            bought_bpcs=bought_bpcs.get(bp["type_id"], 0),
                            struct_te=structure_te_by_bp.get(bp["type_id"], 1.0),
                            industry_level=char["industry_level"],
                            adv_industry_level=char["adv_industry_level"],
                        )

        # Phase-aware timeline (replaces flat time_summary)
        phase_timeline = _compute_phase_timeline(bp_statuses, use_char_skills)
        phase_timeline["timeframe_seconds"] = timeframe_seconds
        phase_timeline["exceeds_timeframe"] = (
            timeframe_seconds is not None
            and phase_timeline["total_wall_seconds"] > timeframe_seconds
        )

        return render_template(
            "calculator.html",
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
            total_material_cost=total_material_cost,
            total_job_cost=total_job_cost,
            grand_total=grand_total,
            stations=stations,
            build_slots=build_slots,
            copy_slots=copy_slots,
            timeframe_hours=timeframe_hours,
            phase_timeline=phase_timeline,
            suggest_mode=suggest_mode,
            use_character_skills=use_char_skills,
            characters=characters,
            unassignable_warnings=unassignable_warnings,
        )

    def get_jobs(self):
        status, data = esi_get(
            f"{ESI_BASE_URL}/characters/{current_user.character_id}/industry/jobs"
        )
        if status == 200:
            return render_template("jobs.html", jobs_info=data)
        return jsonify({"error": "Failed to fetch jobs info"}), status or 500

    def _resolve_cached_location_names(self, location_ids: set) -> dict:
        """Return {location_id: name} from the DB cache only (no ESI calls)."""
        if not location_ids:
            return {}
        cached = (
            db.session.execute(
                select(CachedLocations).where(
                    CachedLocations.location_id.in_(location_ids)
                )
            )
            .scalars()
            .all()
        )
        return {row.location_id: row.location_name for row in cached}



# --- Build strategy computation ---


def _format_duration(seconds):
    """Format seconds into 'Xd Yh Zm' string."""
    if seconds <= 0:
        return "0m"
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _suggest_extra_bpos(num_bpcs, single_bpc_copy_time, bpc_mfg_time, timeframe_seconds):
    """Return minimum total BPOs needed to fit timeframe, or None if impossible."""
    if timeframe_seconds is None or bpc_mfg_time >= timeframe_seconds:
        return None
    available_for_copy = timeframe_seconds - bpc_mfg_time
    if single_bpc_copy_time <= 0:
        return None
    max_copies_per_bpo = int(available_for_copy / single_bpc_copy_time)
    if max_copies_per_bpo < 1:
        return None
    return math.ceil(num_bpcs / max_copies_per_bpo)


def _suggest_buy_bpcs(num_bpcs, num_bpos, single_bpc_copy_time, bpc_mfg_time, timeframe_seconds):
    """Return number of BPCs to buy to fit timeframe, or None if impossible."""
    if timeframe_seconds is None or bpc_mfg_time >= timeframe_seconds:
        return None
    available_for_copy = timeframe_seconds - bpc_mfg_time
    if single_bpc_copy_time <= 0:
        return None
    max_copies_per_bpo = int(available_for_copy / single_bpc_copy_time)
    total_copyable = max_copies_per_bpo * num_bpos
    if total_copyable >= num_bpcs:
        return None  # already fits
    return num_bpcs - total_copyable


def _compute_build_strategy(
    runs_needed,
    max_prod_limit,
    te,
    mfg_time_per_run,
    copy_time_per_run,
    mfg_slots,
    bp_materials,
    me,
    struct_me,
    timeframe_seconds=None,
    num_bpos=1,
    bought_bpcs=0,
    struct_te=1.0,
    industry_level=5,
    adv_industry_level=5,
):
    """Compute BPO vs BPC build strategy for a blueprint.

    Returns dict with mode recommendation, times, and material waste info.
    """
    te_factor = 1 - te / 100
    bought_te_factor = 1 - 20 / 100  # market BPCs are always TE 20
    skill_factor = (1 - 0.04 * industry_level) * (1 - 0.03 * adv_industry_level)
    time_mult = te_factor * struct_te * skill_factor
    bought_time_mult = bought_te_factor * struct_te * skill_factor

    # BPO serial time
    bpo_time = runs_needed * mfg_time_per_run * time_mult

    # If no parallelism benefit possible, always BPO
    if max_prod_limit <= 1 or runs_needed <= 1 or copy_time_per_run <= 0:
        return {
            "mode": "bpo",
            "bpo_time": bpo_time,
            "bpc_time": None,
            "bpc_copy_time": None,
            "bpc_mfg_time": None,
            "num_bpcs": 0,
            "runs_per_bpc": 0,
            "slots_used": 1,
            "recommended": "bpo",
            "material_waste": {},
            "bpo_time_fmt": _format_duration(bpo_time),
            "bpc_time_fmt": None,
            "bought_bpcs": 0,
            "copies_to_make": 0,
            "copy_only_time": None,
            "te_warning": te < 20,
        }

    # BPC strategy: use as few BPCs as needed to fill mfg slots
    num_bpcs = min(mfg_slots, math.ceil(runs_needed / 1))
    runs_per_bpc = min(max_prod_limit, math.ceil(runs_needed / num_bpcs))
    num_bpcs = math.ceil(runs_needed / runs_per_bpc)

    single_bpc_copy_time = copy_time_per_run * runs_per_bpc * te_factor
    # Mfg time depends on whether BPCs are copied (user's TE) or bought (TE 20)
    # Structure TE, rig TE, and skills apply to manufacturing only, not copying
    copied_mfg_time = runs_per_bpc * mfg_time_per_run * time_mult
    bought_mfg_time = runs_per_bpc * mfg_time_per_run * bought_time_mult

    # Reduce copies needed by bought BPCs
    copies_to_make = max(0, num_bpcs - bought_bpcs)

    # Critical path mfg: if any copied BPCs exist, bottleneck is the slower copied time
    bpc_mfg_time = copied_mfg_time if copies_to_make > 0 else bought_mfg_time

    # Pipelined: BPOs copy in parallel, then last BPC's mfg completes
    copies_per_bpo = math.ceil(copies_to_make / num_bpos) if num_bpos > 0 else copies_to_make
    bpc_total_time = (copies_per_bpo * single_bpc_copy_time) + bpc_mfg_time

    # Copy-only time: what if bought_bpcs were 0?
    copy_only_copies_per_bpo = math.ceil(num_bpcs / num_bpos) if num_bpos > 0 else num_bpcs
    copy_only_time = (copy_only_copies_per_bpo * single_bpc_copy_time) + copied_mfg_time

    # Material waste: compare BPC split rounding vs single BPO job rounding
    material_waste = {}
    if bp_materials:
        me_factor = (1 - me / 100) * (1 - struct_me / 100)
        for mat_id, base_qty in bp_materials:
            # Single BPO job: material for all runs
            bpo_qty = max(runs_needed, math.ceil(runs_needed * base_qty * me_factor))
            # BPC split: material per BPC * num BPCs
            per_bpc_qty = max(runs_per_bpc, math.ceil(runs_per_bpc * base_qty * me_factor))
            # Last BPC might have fewer runs
            last_bpc_runs = runs_needed - (num_bpcs - 1) * runs_per_bpc
            if last_bpc_runs > 0 and last_bpc_runs != runs_per_bpc:
                last_bpc_qty = max(last_bpc_runs, math.ceil(last_bpc_runs * base_qty * me_factor))
                bpc_total_qty = per_bpc_qty * (num_bpcs - 1) + last_bpc_qty
            else:
                bpc_total_qty = per_bpc_qty * num_bpcs
            waste = bpc_total_qty - bpo_qty
            if waste > 0:
                material_waste[mat_id] = waste

    # Recommendation
    if timeframe_seconds is not None:
        bpo_fits = bpo_time <= timeframe_seconds
        bpc_fits = bpc_total_time <= timeframe_seconds
        if bpo_fits:
            recommended = "bpo"
        elif bpc_fits:
            recommended = "bpc"
        else:
            recommended = "bpc"  # still recommend BPC as faster, flag red in UI
    else:
        recommended = "bpo" if bpo_time <= bpc_total_time else "bpc"

    result = {
        "mode": recommended,
        "bpo_time": bpo_time,
        "bpc_time": bpc_total_time,
        "bpc_copy_time": copies_per_bpo * single_bpc_copy_time,
        "bpc_mfg_time": bpc_mfg_time,
        "num_bpcs": num_bpcs,
        "runs_per_bpc": runs_per_bpc,
        "slots_used": min(num_bpcs, mfg_slots),
        "recommended": recommended,
        "material_waste": material_waste,
        "bpo_time_fmt": _format_duration(bpo_time),
        "bpc_time_fmt": _format_duration(bpc_total_time),
        "bpc_copy_time_fmt": _format_duration(copies_per_bpo * single_bpc_copy_time),
        "bpc_mfg_time_fmt": _format_duration(bpc_mfg_time),
        "num_bpos": num_bpos,
        "bought_bpcs": bought_bpcs,
        "copies_to_make": copies_to_make,
        "copy_only_time": copy_only_time,
        "te_warning": te < 20,
    }

    # Suggest extra BPOs when BPC mode exceeds timeframe
    if timeframe_seconds is not None and bpc_total_time > timeframe_seconds:
        suggested = _suggest_extra_bpos(
            num_bpcs, single_bpc_copy_time, bpc_mfg_time, timeframe_seconds
        )
        if suggested is not None and suggested > num_bpos:
            result["suggested_total_bpos"] = suggested

        buy_bpcs = _suggest_buy_bpcs(
            num_bpcs, num_bpos, single_bpc_copy_time, bpc_mfg_time, timeframe_seconds
        )
        if buy_bpcs is not None and buy_bpcs > 0:
            result["suggested_buy_bpcs"] = buy_bpcs

    return result


def _compute_blueprint_depths(top_bp_id, materials_by_bp, products_by_product, blacklist=None):
    """BFS from top blueprint. Each child gets depth = parent_depth + 1.
    Diamond dependencies take max depth."""
    depths = {top_bp_id: 0}
    queue = [(top_bp_id, 0)]
    while queue:
        bp_id, d = queue.pop(0)
        for mat_id, _ in materials_by_bp.get(bp_id, []):
            if blacklist and mat_id in blacklist:
                continue
            sub = products_by_product.get(mat_id)
            if sub:
                child_bp_id = sub[0]
                new_depth = d + 1
                if child_bp_id not in depths or new_depth > depths[child_bp_id]:
                    depths[child_bp_id] = new_depth
                    queue.append((child_bp_id, new_depth))
    return depths


def _compute_phase_timeline(bp_statuses, use_char_skills=False):
    """Group bp_statuses by depth, compute per-phase critical paths, sum phases sequentially."""
    phases_by_depth = {}
    for bp in bp_statuses:
        d = bp.get("depth", 0)
        phases_by_depth.setdefault(d, []).append(bp)

    max_depth = max(phases_by_depth.keys()) if phases_by_depth else 0
    phases = []
    total_wall = 0
    total_copy_only_wall = 0
    total_slot_hours = 0

    for phase_num, depth in enumerate(range(max_depth, -1, -1), 1):
        bps = phases_by_depth.get(depth, [])
        if not bps:
            continue

        phase_wall = 0
        phase_copy_only = 0
        phase_copy_secs = 0
        phase_mfg_secs = 0

        if use_char_skills:
            # Multi-character: group by assigned character, per-character wall = max of that char's jobs
            char_mfg_times = {}
            char_copy_times = {}
            for bp in bps:
                s = bp["build_strategy"]
                total_slot_hours += s["bpo_time"] / 3600
                ac = bp.get("assigned_character")
                char_id = ac["char_id"] if ac else "__unassigned__"

                if s["recommended"] == "bpc" and s.get("bpc_mfg_time"):
                    char_mfg_times[char_id] = max(char_mfg_times.get(char_id, 0), s["bpc_mfg_time"])
                    if s.get("bpc_copy_time"):
                        char_copy_times[char_id] = max(char_copy_times.get(char_id, 0), s["bpc_copy_time"])
                else:
                    char_mfg_times[char_id] = max(char_mfg_times.get(char_id, 0), s["bpo_time"])

            phase_mfg_secs = max(char_mfg_times.values()) if char_mfg_times else 0
            phase_copy_secs = max(char_copy_times.values()) if char_copy_times else 0
            phase_wall = max(phase_mfg_secs, phase_copy_secs + phase_mfg_secs) if phase_copy_secs > 0 else phase_mfg_secs
            # For copy+mfg pipeline: copy and mfg can overlap when different characters handle them
            # but conservatively, wall = max(copy) + max(mfg) for the bottleneck character
            if phase_copy_secs > 0:
                phase_wall = phase_copy_secs + phase_mfg_secs
            phase_copy_only = phase_wall
        else:
            for bp in bps:
                s = bp["build_strategy"]
                rec_time = s["bpc_time"] if s["recommended"] == "bpc" and s["bpc_time"] else s["bpo_time"]
                phase_wall = max(phase_wall, rec_time)
                total_slot_hours += s["bpo_time"] / 3600

                # Copy-only: what if bought_bpcs were 0?
                if s["recommended"] == "bpc" and s.get("copy_only_time"):
                    phase_copy_only = max(phase_copy_only, s["copy_only_time"])
                else:
                    phase_copy_only = max(phase_copy_only, rec_time)

                # Per-phase copy vs mfg breakdown
                if s["recommended"] == "bpc" and s["bpc_copy_time"]:
                    phase_copy_secs = max(phase_copy_secs, s["bpc_copy_time"])
                    phase_mfg_secs = max(phase_mfg_secs, s["bpc_mfg_time"])
                else:
                    phase_mfg_secs = max(phase_mfg_secs, s["bpo_time"])

        phases.append({
            "depth": depth,
            "phase_num": phase_num,
            "blueprints": bps,
            "wall_seconds": phase_wall,
            "wall_fmt": _format_duration(phase_wall),
            "copy_seconds": phase_copy_secs,
            "copy_fmt": _format_duration(phase_copy_secs),
            "mfg_seconds": phase_mfg_secs,
            "mfg_fmt": _format_duration(phase_mfg_secs),
        })
        total_wall += phase_wall
        total_copy_only_wall += phase_copy_only

    return {
        "phases": phases,
        "total_wall_seconds": total_wall,
        "total_wall_fmt": _format_duration(total_wall),
        "copy_only_seconds": total_copy_only_wall,
        "copy_only_fmt": _format_duration(total_copy_only_wall),
        "total_slot_hours": total_slot_hours,
    }


# --- DFS helpers (pure dict lookups, no DB calls) ---


def _discover_blueprints(
    blueprint_type_id: int,
    discovered: set,
    materials_by_bp: dict,
    products_by_product: dict,
    blacklist: set = None,
) -> set:
    """DFS to find all blueprint type IDs in the build tree."""
    if blueprint_type_id in discovered:
        return discovered
    discovered.add(blueprint_type_id)
    for material_type_id, _ in materials_by_bp.get(blueprint_type_id, []):
        if blacklist and material_type_id in blacklist:
            continue
        sub = products_by_product.get(material_type_id)
        if sub:
            _discover_blueprints(
                sub[0], discovered, materials_by_bp, products_by_product, blacklist
            )
    return discovered


def _resolve_material_tree(
    blueprint_type_id: int,
    cache: dict,
    me_levels: dict,
    materials_by_bp: dict,
    products_by_product: dict,
    blacklist: set = None,
    structure_me_by_bp: dict = None,
) -> dict:
    """DFS over the manufacturing tree. Returns {material_type_id: quantity} for 1 run.
    Results are memoized in cache to avoid redundant traversal of shared sub-components.
    me_levels maps blueprint_type_id -> ME level (0-10) for material reduction.
    structure_me_by_bp maps blueprint_type_id -> structure ME bonus (0-100) for additional reduction."""
    if blueprint_type_id in cache:
        return cache[blueprint_type_id]

    cache[blueprint_type_id] = {}  # cycle sentinel

    me = me_levels.get(blueprint_type_id, 0)
    struct_me = (structure_me_by_bp or {}).get(blueprint_type_id, 0)

    result = {}
    for material_type_id, base_qty in materials_by_bp.get(blueprint_type_id, []):
        adjusted_qty = max(
            1, math.ceil(base_qty * (1 - me / 100) * (1 - struct_me / 100))
        )

        if blacklist and material_type_id in blacklist:
            result[material_type_id] = result.get(material_type_id, 0) + adjusted_qty
        else:
            sub = products_by_product.get(material_type_id)
            if sub:
                sub_bp_id, sub_product_qty = sub
                sub_tree = _resolve_material_tree(
                    sub_bp_id,
                    cache,
                    me_levels,
                    materials_by_bp,
                    products_by_product,
                    blacklist,
                    structure_me_by_bp,
                )
                runs_needed = math.ceil(adjusted_qty / sub_product_qty)
                for raw_id, raw_qty in sub_tree.items():
                    result[raw_id] = result.get(raw_id, 0) + raw_qty * runs_needed
            else:
                result[material_type_id] = (
                    result.get(material_type_id, 0) + adjusted_qty
                )

    cache[blueprint_type_id] = result
    return result


def _compute_runs_needed(
    blueprint_type_id,
    me_levels,
    top_runs,
    materials_by_bp,
    products_by_product,
    blacklist: set = None,
    structure_me_by_bp: dict = None,
):
    """Returns {bp_type_id: total_runs_needed} across the full tree."""
    runs_needed = {blueprint_type_id: top_runs}
    _runs_dfs(
        blueprint_type_id,
        top_runs,
        me_levels,
        runs_needed,
        materials_by_bp,
        products_by_product,
        blacklist,
        structure_me_by_bp,
    )
    return runs_needed


def _runs_dfs(
    blueprint_type_id,
    parent_runs,
    me_levels,
    runs_needed,
    materials_by_bp,
    products_by_product,
    blacklist: set = None,
    structure_me_by_bp: dict = None,
):
    """Recursive helper: propagate run counts down the build tree."""
    me = me_levels.get(blueprint_type_id, 0)
    struct_me = (structure_me_by_bp or {}).get(blueprint_type_id, 0)

    for material_type_id, base_qty in materials_by_bp.get(blueprint_type_id, []):
        adjusted_qty = max(
            1, math.ceil(base_qty * (1 - me / 100) * (1 - struct_me / 100))
        )

        if blacklist and material_type_id in blacklist:
            continue

        sub = products_by_product.get(material_type_id)
        if sub:
            sub_bp_id, sub_product_qty = sub
            child_runs = math.ceil(adjusted_qty * parent_runs / sub_product_qty)
            runs_needed[sub_bp_id] = runs_needed.get(sub_bp_id, 0) + child_runs
            _runs_dfs(
                sub_bp_id,
                child_runs,
                me_levels,
                runs_needed,
                materials_by_bp,
                products_by_product,
                blacklist,
                structure_me_by_bp,
            )


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
