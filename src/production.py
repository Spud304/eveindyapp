import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import select

from src.models.models import db, EveType, BlueprintProduct, Blueprints, MapSolarSystem
from src.utils import (
    batch_type_names,
    batch_market_info,
    get_industry_cost_index,
    get_jita_sell_price,
)
from src.config import load_user_config, get_character_roles
from src.industry import (
    _build_decryptor_comparison,
    _format_duration,
    _resolve_material_tree,
)
from src.industry_utils import (
    load_sde_manufacturing_data,
    load_sde_invention_data,
    load_decryptor_data,
    load_invention_times,
    load_activity_times,
    load_invention_skill_requirements,
    load_character_skills,
    compute_character_capabilities,
    get_character_names,
    load_rig_data,
    load_type_group_category_maps,
    classify_product_for_rig,
    pick_best_station,
    load_sde_reaction_data,
    build_reaction_toggle_map,
    load_reaction_rig_data,
    classify_reaction_for_rig,
    pick_best_reaction_station,
)

logger = logging.getLogger(__name__)

SCC_SURCHARGE = 0.015


class ProductionBlueprint(Blueprint):
    def __init__(self, name, import_name):
        super().__init__(name, import_name)
        self._add_routes()

    def _add_routes(self):
        self.add_url_rule(
            "/production",
            "production",
            login_required(self.get_production),
            methods=["GET"],
        )
        self.add_url_rule(
            "/production/search",
            "production_search",
            login_required(self.search_items),
            methods=["GET"],
        )

    def search_items(self):
        q = request.args.get("q", "", type=str).strip()
        if len(q) < 2:
            return jsonify([])
        results = db.session.execute(
            select(EveType.typeID, EveType.typeName)
            .join(
                BlueprintProduct,
                BlueprintProduct.productTypeID == EveType.typeID,
            )
            .where(BlueprintProduct.activityID == "manufacturing")
            .where(EveType.typeName.ilike(f"%{q}%"))
            .where(EveType.published == 1)
            .limit(15)
        ).all()
        return jsonify([{"type_id": r.typeID, "name": r.typeName} for r in results])

    def get_production(self):
        product_type_id = request.args.get("product_type_id", 0, type=int)
        sell_price_override = request.args.get("sell_price_override", 0.0, type=float)
        num_bpos = request.args.get("num_bpos", 1, type=int)
        num_bpos = max(1, num_bpos)

        if not product_type_id:
            return render_template("production.html", product=None)

        # Look up product
        product_name = db.session.execute(
            select(EveType.typeName).where(EveType.typeID == product_type_id)
        ).scalar_one_or_none()

        if not product_name:
            return render_template(
                "production.html", product=None, error="Item not found."
            )

        # Find manufacturing blueprint
        bp_row = db.session.execute(
            select(BlueprintProduct.typeID, BlueprintProduct.quantity)
            .where(BlueprintProduct.productTypeID == product_type_id)
            .where(BlueprintProduct.activityID == "manufacturing")
            .limit(1)
        ).first()

        if not bp_row:
            return render_template(
                "production.html",
                product=None,
                error="No blueprint found for this item.",
            )

        mfg_bp_id = bp_row.typeID
        product_qty_per_run = bp_row.quantity or 1

        # Check if T2
        _, invention_products, _ = load_sde_invention_data()
        is_t2 = mfg_bp_id in invention_products

        # Load config and characters
        char_id = current_user.character_id
        config = load_user_config(char_id)
        stations = config.get("stations", [])

        from src.user import get_linked_character_ids

        char_ids = get_linked_character_ids(current_user)
        char_skills_map = load_character_skills(char_ids)
        char_names_map = get_character_names(char_ids)

        # Build character lists by role
        characters = []
        for cid in char_ids:
            skills = char_skills_map.get(cid, {})
            if not skills:
                continue
            caps = compute_character_capabilities(skills)
            roles = get_character_roles(config, cid)
            characters.append(
                {
                    "char_id": cid,
                    "char_name": char_names_map.get(cid, f"Character {cid}"),
                    "skills": skills,
                    "roles": roles,
                    **caps,
                }
            )

        mfg_characters = [c for c in characters if c["roles"]["manufacturing"]]
        inv_characters = [c for c in characters if c["roles"]["invention"]]

        total_mfg_slots = sum(c["mfg_slots"] for c in mfg_characters)
        total_lab_slots = sum(c["copy_slots"] for c in inv_characters)

        # Load manufacturing data
        materials_by_bp, products_by_product, _ = load_sde_manufacturing_data()
        activity_times = load_activity_times()
        rig_data = load_rig_data()
        type_to_group, group_to_category = load_type_group_category_maps()

        # --- Reaction support: merge enabled reactions ---
        reaction_materials_raw, reaction_products_raw = load_sde_reaction_data()
        reaction_toggle_map = build_reaction_toggle_map(
            reaction_products_raw, reaction_materials_raw, type_to_group
        )
        reaction_config = {
            k: config.get(k, False)
            for k in (
                "react_intermediates",
                "react_composites",
                "react_hybrid",
                "react_biochemical",
                "react_molecular_forged",
            )
        }
        combined_materials = dict(materials_by_bp)
        combined_products = dict(products_by_product)
        enabled_reaction_formula_ids = set()
        for product_id, (formula_id, qty) in reaction_products_raw.items():
            toggle = reaction_toggle_map.get(product_id)
            if toggle and reaction_config.get(toggle, False):
                combined_products[product_id] = (formula_id, qty)
                enabled_reaction_formula_ids.add(formula_id)
        for formula_id in enabled_reaction_formula_ids:
            if formula_id in reaction_materials_raw:
                combined_materials[formula_id] = reaction_materials_raw[formula_id]

        # Find best station for this product
        product_rig_cat = classify_product_for_rig(
            product_type_id, type_to_group, group_to_category
        )

        system_securities = {}
        for station in stations:
            sid = station.get("system_id")
            if sid and sid not in system_securities:
                row = db.session.execute(
                    select(MapSolarSystem.security).where(
                        MapSolarSystem.solarSystemID == sid
                    )
                ).scalar_one_or_none()
                system_securities[sid] = row

        best_station, struct_me_pct, struct_te_mult = pick_best_station(
            stations, product_rig_cat, system_securities, rig_data
        )

        # Build structure_me_by_bp for reaction formulas in the tree
        reaction_rig_data = load_reaction_rig_data()
        me_levels = {mfg_bp_id: 10}  # Assume ME 10 BPO for top-level
        structure_me_by_bp = {mfg_bp_id: struct_me_pct / 100}

        # Pre-populate ME for reaction formulas (discover tree first)
        blacklist = set(config.get("blacklist", []))
        from src.industry import _discover_blueprints

        tree_bp_ids = _discover_blueprints(
            mfg_bp_id, set(), combined_materials, combined_products, blacklist
        )
        for bp_id in tree_bp_ids:
            if bp_id in enabled_reaction_formula_ids:
                me_levels[bp_id] = 0
                rig_cat = classify_reaction_for_rig(bp_id, type_to_group)
                if rig_cat and stations:
                    _, rxn_me, _ = pick_best_reaction_station(
                        stations, rig_cat, system_securities, reaction_rig_data
                    )
                    structure_me_by_bp[bp_id] = rxn_me / 100
                else:
                    structure_me_by_bp[bp_id] = 0

        # Get cost index
        sys_id = best_station.get("system_id") if best_station else None
        facility_tax = best_station.get("facility_tax", 10.0) if best_station else 10.0
        mfg_cost_index = (
            get_industry_cost_index(sys_id, "manufacturing") if sys_id else 0.0
        )

        # Manufacturing time
        base_mfg_time = activity_times.get(mfg_bp_id, (0, 0))[0]
        copy_time = activity_times.get(mfg_bp_id, (0, 0))[1]

        # TE skill bonus from best manufacturer
        best_industry = max((c["industry_level"] for c in mfg_characters), default=0)
        best_adv_industry = max(
            (c["adv_industry_level"] for c in mfg_characters), default=0
        )
        skill_te_mult = 1 - 0.04 * best_industry - 0.03 * best_adv_industry
        mfg_time = base_mfg_time * struct_te_mult * max(0.0, skill_te_mult)

        # Material cost (1 run)
        cache = {}
        raw_materials = _resolve_material_tree(
            mfg_bp_id,
            cache,
            me_levels,
            combined_materials,
            combined_products,
            blacklist,
            structure_me_by_bp,
        )

        # Price all materials
        all_price_ids = set(raw_materials.keys())
        all_price_ids.add(product_type_id)
        prices, adjusted_prices = batch_market_info(all_price_ids)

        material_cost_per_run = sum(
            prices.get(tid, 0.0) * qty for tid, qty in raw_materials.items()
        )
        material_cost_per_unit = material_cost_per_run / product_qty_per_run

        # EIV for job cost
        base_materials = materials_by_bp.get(mfg_bp_id, [])
        eiv_per_run = sum(
            adjusted_prices.get(mat_id, 0.0) * qty for mat_id, qty in base_materials
        )
        job_cost_per_run = eiv_per_run * (
            mfg_cost_index + facility_tax / 100 + SCC_SURCHARGE
        )
        job_cost_per_unit = job_cost_per_run / product_qty_per_run

        # Resolve material names for display
        mat_names = batch_type_names(set(raw_materials.keys()))
        materials_display = sorted(
            [
                {
                    "name": mat_names.get(tid, f"Unknown ({tid})"),
                    "quantity": qty,
                    "unit_price": prices.get(tid, 0.0),
                    "total_price": prices.get(tid, 0.0) * qty,
                }
                for tid, qty in raw_materials.items()
            ],
            key=lambda m: m["total_price"],
            reverse=True,
        )

        # === T2-specific: invention pipeline ===
        invention_data = None
        invention_cost_per_unit = 0.0

        if is_t2:
            t1_bp_id, base_inv_runs = invention_products[mfg_bp_id]
            invention_materials, _, invention_probabilities = load_sde_invention_data()
            decryptors = load_decryptor_data()
            invention_times = load_invention_times()
            invention_skill_reqs = load_invention_skill_requirements()

            # Price datacores + decryptors
            inv_price_ids = set()
            for mat_id, _ in invention_materials.get(t1_bp_id, []):
                inv_price_ids.add(mat_id)
            for d in decryptors:
                inv_price_ids.add(d["type_id"])
            inv_prices, _ = batch_market_info(inv_price_ids)
            inv_prices.update(prices)

            # Find best inventor
            best_inv_skills = None
            best_success = 0.0
            for c in inv_characters:
                reqs = invention_skill_reqs.get(t1_bp_id, {})
                enc_id = reqs.get("encryption_skill")
                sci_ids = reqs.get("science_skills", [])
                enc_level = c["skills"].get(enc_id, 0) if enc_id else 0
                if enc_level == 0:
                    continue
                sci_sum = sum(c["skills"].get(sid, 0) for sid in sci_ids)
                base_prob = invention_probabilities.get((t1_bp_id, mfg_bp_id), 0.0)
                skill_mod = (1 + enc_level / 40) * (1 + sci_sum / 30)
                rate = base_prob * skill_mod
                if rate > best_success:
                    best_success = rate
                    best_inv_skills = c["skills"]

            # Decryptor comparison
            decryptor_comparison = _build_decryptor_comparison(
                t1_bp_id,
                mfg_bp_id,
                base_inv_runs,
                base_inv_runs,
                invention_materials,
                invention_probabilities,
                invention_times,
                decryptors,
                inv_prices,
                char_skills=best_inv_skills,
                invention_skill_reqs=invention_skill_reqs,
            )

            best_dec = next(
                (o for o in decryptor_comparison if o.get("optimal")),
                decryptor_comparison[0] if decryptor_comparison else None,
            )

            if best_dec:
                runs_per_bpc = best_dec["runs_per_bpc"]
                inv_cost_per_bpc = best_dec["total_cost"]
                # Invention cost per manufactured unit
                units_per_bpc = runs_per_bpc * product_qty_per_run
                invention_cost_per_unit = inv_cost_per_bpc / max(units_per_bpc, 1)

            # Invention slot split
            inv_time = invention_times.get(t1_bp_id, 0)
            t1_copy_time = activity_times.get(t1_bp_id, (0, 0))[1]

            inv_allocations = []
            total_inv_slots = 0
            total_cp_slots = 0
            total_bpos_needed = 0
            total_daily_t2_bpcs = 0.0

            if inv_time > 0 and t1_copy_time > 0:
                copy_ratio = t1_copy_time / inv_time
                attempts_per_slot = 86400 / inv_time

                for c in inv_characters:
                    reqs = invention_skill_reqs.get(t1_bp_id, {})
                    enc_id = reqs.get("encryption_skill")
                    if not c["skills"].get(enc_id, 0):
                        continue

                    lab = c["copy_slots"]
                    inv_s = max(1, int(lab / (1 + copy_ratio)))
                    cp_s = lab - inv_s
                    bpos = cp_s

                    sci_ids = reqs.get("science_skills", [])
                    enc_level = c["skills"].get(enc_id, 0)
                    sci_sum = sum(c["skills"].get(sid, 0) for sid in sci_ids)
                    base_prob = invention_probabilities.get((t1_bp_id, mfg_bp_id), 0.0)
                    char_skill_mod = (1 + enc_level / 40) * (1 + sci_sum / 30)
                    dec_mult = (
                        best_dec["decryptor"]["prob_mult"]
                        if best_dec and best_dec.get("decryptor")
                        else 1.0
                    )
                    char_prob = min(base_prob * char_skill_mod * dec_mult, 1.0)
                    daily_attempts = attempts_per_slot * inv_s
                    daily_bpcs = daily_attempts * char_prob

                    total_inv_slots += inv_s
                    total_cp_slots += cp_s
                    total_bpos_needed += bpos
                    total_daily_t2_bpcs += daily_bpcs

                    inv_allocations.append(
                        {
                            "char_name": c["char_name"],
                            "lab_slots": lab,
                            "invention_slots": inv_s,
                            "copy_slots": cp_s,
                            "bpos_needed": bpos,
                            "success_rate": char_prob,
                        }
                    )

            runs_per_bpc = best_dec["runs_per_bpc"] if best_dec else 1
            daily_inventable_runs = total_daily_t2_bpcs * runs_per_bpc

            invention_data = {
                "t1_bp_name": batch_type_names({t1_bp_id}).get(t1_bp_id, "Unknown"),
                "decryptor_name": best_dec["decryptor_name"] if best_dec else "None",
                "success_rate": best_dec["probability"] if best_dec else 0,
                "runs_per_bpc": runs_per_bpc,
                "inv_cost_per_unit": invention_cost_per_unit,
                "total_inv_slots": total_inv_slots,
                "total_cp_slots": total_cp_slots,
                "total_bpos_needed": total_bpos_needed,
                "total_daily_t2_bpcs": total_daily_t2_bpcs,
                "daily_inventable_runs": daily_inventable_runs,
                "allocations": inv_allocations,
                "copy_time_fmt": _format_duration(t1_copy_time)
                if t1_copy_time
                else "N/A",
                "inv_time_fmt": _format_duration(inv_time) if inv_time else "N/A",
            }

        # === T1-specific: BPO strategy ===
        t1_strategy = None
        if not is_t2:
            # Get max runs for BPC from Blueprints table
            bp_meta = db.session.execute(
                select(Blueprints.maxProductionLimit).where(
                    Blueprints.typeID == mfg_bp_id
                )
            ).scalar_one_or_none()
            max_runs = bp_meta if bp_meta else 1

            if mfg_time > 0:
                runs_per_slot_per_day = 86400 / mfg_time

                # Option A: Build from BPO directly
                bpo_slots = min(num_bpos, total_mfg_slots)
                daily_units_bpo = (
                    runs_per_slot_per_day * bpo_slots * product_qty_per_run
                )

                # Option B: Copy to BPCs, build from BPCs
                # Split lab slots for copying, use all mfg slots for building
                if copy_time > 0 and total_lab_slots > 0:
                    # Each copy slot with a BPO produces max_runs BPCs per copy cycle
                    copy_slots_available = min(num_bpos, total_lab_slots)
                    copies_per_day = (86400 / copy_time) * copy_slots_available
                    bpc_runs_per_day = copies_per_day * max_runs
                    mfg_capacity = (
                        runs_per_slot_per_day * total_mfg_slots * product_qty_per_run
                    )
                    daily_units_bpc = min(
                        bpc_runs_per_day * product_qty_per_run, mfg_capacity
                    )
                else:
                    daily_units_bpc = 0
                    copy_slots_available = 0
                    copies_per_day = 0

                recommended = "bpc" if daily_units_bpc > daily_units_bpo else "bpo"
                daily_units = max(daily_units_bpo, daily_units_bpc)

                t1_strategy = {
                    "num_bpos": num_bpos,
                    "max_runs": max_runs,
                    "bpo_daily_units": daily_units_bpo,
                    "bpo_slots_used": bpo_slots,
                    "bpc_daily_units": daily_units_bpc,
                    "bpc_copy_slots": copy_slots_available,
                    "bpc_copies_per_day": copies_per_day,
                    "recommended": recommended,
                    "daily_units": daily_units,
                    "copy_time_fmt": _format_duration(copy_time)
                    if copy_time > 0
                    else "N/A",
                }

        # === Throughput ===
        if is_t2 and invention_data:
            # T2: limited by invention output or mfg capacity
            mfg_capacity_per_day = (
                (86400 / mfg_time) * total_mfg_slots * product_qty_per_run
                if mfg_time > 0
                else 0
            )
            daily_inventable_units = (
                invention_data["daily_inventable_runs"] * product_qty_per_run
            )
            daily_units = min(daily_inventable_units, mfg_capacity_per_day)
            bottleneck = (
                "invention"
                if daily_inventable_units <= mfg_capacity_per_day
                else "manufacturing"
            )
        elif t1_strategy:
            daily_units = t1_strategy["daily_units"]
            bottleneck = (
                "bpo" if t1_strategy["recommended"] == "bpo" else "manufacturing"
            )
            mfg_capacity_per_day = (
                (86400 / mfg_time) * total_mfg_slots * product_qty_per_run
                if mfg_time > 0
                else 0
            )
        else:
            daily_units = 0
            bottleneck = "unknown"
            mfg_capacity_per_day = 0

        # === Costs per unit ===
        total_cost_per_unit = (
            material_cost_per_unit + job_cost_per_unit + invention_cost_per_unit
        )

        # === Revenue & Profit ===
        sell_price = None
        if sell_price_override > 0:
            sell_price = sell_price_override
        else:
            sell_price = get_jita_sell_price(product_type_id)

        net_revenue_per_unit = None
        profit_per_unit = None
        margin_pct = None
        daily_revenue = None
        daily_profit = None
        monthly_profit = None
        monthly_revenue = None
        monthly_cost = None

        sales_tax = config.get("sales_tax", 3.6) / 100
        broker_fee = config.get("broker_fee", 2.0) / 100

        if sell_price and sell_price > 0:
            net_revenue_per_unit = sell_price * (1 - sales_tax - broker_fee)
            profit_per_unit = net_revenue_per_unit - total_cost_per_unit
            margin_pct = (profit_per_unit / sell_price * 100) if sell_price > 0 else 0
            daily_revenue = net_revenue_per_unit * daily_units
            daily_profit = profit_per_unit * daily_units
            monthly_revenue = daily_revenue * 30
            monthly_cost = total_cost_per_unit * daily_units * 30
            monthly_profit = daily_profit * 30

        return render_template(
            "production.html",
            product={"type_id": product_type_id, "name": product_name},
            is_t2=is_t2,
            num_bpos=num_bpos,
            sell_price_override=sell_price_override if sell_price_override > 0 else "",
            # Manufacturing
            mfg_time_fmt=_format_duration(mfg_time),
            product_qty_per_run=product_qty_per_run,
            total_mfg_slots=total_mfg_slots,
            total_lab_slots=total_lab_slots,
            mfg_capacity_per_day=mfg_capacity_per_day,
            station_name=best_station.get("name", "None") if best_station else "None",
            struct_me_pct=struct_me_pct,
            # Materials
            materials=materials_display,
            material_cost_per_run=material_cost_per_run,
            material_cost_per_unit=material_cost_per_unit,
            # Costs
            job_cost_per_unit=job_cost_per_unit,
            invention_cost_per_unit=invention_cost_per_unit,
            total_cost_per_unit=total_cost_per_unit,
            # Throughput
            daily_units=daily_units,
            bottleneck=bottleneck,
            # Invention (T2 only)
            invention_data=invention_data,
            # T1 strategy
            t1_strategy=t1_strategy,
            # Revenue
            sales_tax_pct=config.get("sales_tax", 3.6),
            broker_fee_pct=config.get("broker_fee", 2.0),
            sell_price=sell_price,
            net_revenue_per_unit=net_revenue_per_unit,
            profit_per_unit=profit_per_unit,
            margin_pct=margin_pct,
            # Projections
            daily_revenue=daily_revenue,
            daily_profit=daily_profit,
            monthly_revenue=monthly_revenue,
            monthly_cost=monthly_cost,
            monthly_profit=monthly_profit,
        )
