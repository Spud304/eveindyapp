import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import select

from src.models.models import db, EveType, BlueprintProduct, BlueprintActivityMaterial
from src.utils import batch_type_names, batch_market_info, get_industry_cost_index
from src.industry import _build_decryptor_comparison, _format_duration
from src.config import load_user_config
from src.industry_utils import (
    load_sde_invention_data,
    load_decryptor_data,
    load_invention_times,
    load_activity_times,
    load_invention_skill_requirements,
    load_character_skills,
    compute_character_capabilities,
    get_character_names,
)

logger = logging.getLogger(__name__)


class InventionBlueprint(Blueprint):
    def __init__(self, name, import_name):
        super().__init__(name, import_name)
        self._add_routes()

    def _add_routes(self):
        self.add_url_rule(
            "/invention",
            "invention",
            login_required(self.get_invention),
            methods=["GET"],
        )
        self.add_url_rule(
            "/invention/search",
            "invention_search",
            login_required(self.search_t2_items),
            methods=["GET"],
        )

    def search_t2_items(self):
        q = request.args.get("q", "", type=str).strip()
        if len(q) < 2:
            return jsonify([])

        _, invention_products, _ = load_sde_invention_data()
        t2_bp_ids = set(invention_products.keys())

        results = db.session.execute(
            select(EveType.typeID, EveType.typeName)
            .join(
                BlueprintProduct,
                BlueprintProduct.productTypeID == EveType.typeID,
            )
            .where(BlueprintProduct.activityID == "manufacturing")
            .where(EveType.typeName.ilike(f"%{q}%"))
            .where(EveType.published == 1)
            .where(BlueprintProduct.typeID.in_(t2_bp_ids))
            .limit(15)
        ).all()
        return jsonify([{"type_id": r.typeID, "name": r.typeName} for r in results])

    def get_invention(self):
        product_type_id = request.args.get("product_type_id", 0, type=int)
        bpc_sell_price = request.args.get("bpc_sell_price", 0.0, type=float)

        if not product_type_id:
            return render_template("invention.html", product=None)

        # Look up the T2 item
        product_name = db.session.execute(
            select(EveType.typeName).where(EveType.typeID == product_type_id)
        ).scalar_one_or_none()

        if not product_name:
            return render_template(
                "invention.html", product=None, error="Item not found."
            )

        # Find T2 manufacturing blueprint
        bp_row = db.session.execute(
            select(BlueprintProduct.typeID)
            .where(BlueprintProduct.productTypeID == product_type_id)
            .where(BlueprintProduct.activityID == "manufacturing")
            .limit(1)
        ).scalar_one_or_none()

        if not bp_row:
            return render_template(
                "invention.html",
                product=None,
                error="No blueprint found for this item.",
            )

        t2_bp_id = bp_row

        # Load invention data
        invention_materials, invention_products, invention_probabilities = (
            load_sde_invention_data()
        )

        if t2_bp_id not in invention_products:
            return render_template(
                "invention.html",
                product={"type_id": product_type_id, "name": product_name},
                error="This is not a T2 item (no invention source found).",
            )

        t1_bp_id, base_runs = invention_products[t2_bp_id]

        # Load supporting data
        decryptors = load_decryptor_data()
        invention_times = load_invention_times()
        activity_times = load_activity_times()
        invention_skill_reqs = load_invention_skill_requirements()

        # Load linked characters and their skills
        from src.user import get_linked_character_ids
        from src.config import get_character_roles

        config = load_user_config(current_user.character_id)
        char_ids = get_linked_character_ids(current_user)
        char_skills_map = load_character_skills(char_ids)
        char_names = get_character_names(char_ids)
        has_characters = bool(char_ids) and any(char_skills_map.values())

        # Build per-character invention data
        characters = []
        best_char_skills = None
        best_success_rate = 0.0

        # Resolve skill names for display
        reqs = invention_skill_reqs.get(t1_bp_id, {})
        all_req_skill_ids = {s[0] for s in reqs.get("all_skills", [])}
        skill_names = batch_type_names(all_req_skill_ids) if all_req_skill_ids else {}

        for cid in char_ids:
            roles = get_character_roles(config, cid)
            if not roles.get("invention", True):
                continue

            skills = char_skills_map.get(cid, {})
            if not skills:
                continue

            caps = compute_character_capabilities(skills)

            # Check invention capability for this T1 blueprint
            enc_id = reqs.get("encryption_skill")
            sci_ids = reqs.get("science_skills", [])
            enc_level = skills.get(enc_id, 0) if enc_id else 0
            can_invent = enc_level > 0

            # Compute success rate with skills
            sci_sum = sum(skills.get(sid, 0) for sid in sci_ids)
            base_prob = invention_probabilities.get((t1_bp_id, t2_bp_id), 0.0)
            skill_modifier = (1 + enc_level / 40) * (1 + sci_sum / 30)
            success_rate = base_prob * skill_modifier

            # Find missing/low skills
            missing_skills = []
            for skill_id, min_level in reqs.get("all_skills", []):
                current_level = skills.get(skill_id, 0)
                if current_level < min_level:
                    sname = skill_names.get(skill_id, f"Skill {skill_id}")
                    if current_level == 0:
                        impact = "Blocks invention"
                    else:
                        impact = "Below required level (reduces success rate)"
                    missing_skills.append(
                        {
                            "name": sname,
                            "required": min_level,
                            "current": current_level,
                            "impact": impact,
                        }
                    )

            char_info = {
                "char_id": cid,
                "char_name": char_names.get(cid, f"Character {cid}"),
                "can_invent": can_invent,
                "success_rate": success_rate,
                "lab_slots": caps["copy_slots"],
                "mfg_slots": caps["mfg_slots"],
                "missing_skills": missing_skills,
                "enc_level": enc_level,
                "sci_levels": [skills.get(sid, 0) for sid in sci_ids],
            }
            characters.append(char_info)

            if can_invent and success_rate > best_success_rate:
                best_success_rate = success_rate
                best_char_skills = skills

        # Gather type IDs for pricing (datacores + decryptors)
        price_ids = set()
        for mat_id, _ in invention_materials.get(t1_bp_id, []):
            price_ids.add(mat_id)
        for d in decryptors:
            price_ids.add(d["type_id"])

        prices, _ = batch_market_info(price_ids)

        # Build decryptor comparison using best character's skills (or no skills)
        decryptor_comparison = _build_decryptor_comparison(
            t1_bp_id,
            t2_bp_id,
            base_runs,
            base_runs,
            invention_materials,
            invention_probabilities,
            invention_times,
            decryptors,
            prices,
            char_skills=best_char_skills,
            invention_skill_reqs=invention_skill_reqs,
        )

        # Compute invention job cost from system cost index
        SCC_SURCHARGE = 0.015
        config = load_user_config(current_user.character_id)
        stations = config.get("stations", [])
        invention_job_cost_per_run = 0.0

        if stations:
            # Use first station with a system_id
            station = next((s for s in stations if s.get("system_id")), stations[0])
            sys_id = station.get("system_id")
            facility_tax = station.get("facility_tax", 10.0)

            if sys_id:
                invention_cost_index = get_industry_cost_index(sys_id, "invention")

                # EIV for invention = sum of adjusted_price * base_qty of T2 item at ME 0
                _, adjusted_prices = batch_market_info(price_ids)
                t2_base_mats = db.session.execute(
                    select(
                        BlueprintActivityMaterial.materialTypeID,
                        BlueprintActivityMaterial.quantity,
                    )
                    .where(BlueprintActivityMaterial.typeID == t2_bp_id)
                    .where(BlueprintActivityMaterial.activityID == "manufacturing")
                ).all()

                eiv = sum(
                    adjusted_prices.get(mat.materialTypeID, 0.0) * (mat.quantity or 0)
                    for mat in t2_base_mats
                )
                invention_job_cost_per_run = eiv * (
                    invention_cost_index + facility_tax / 100 + SCC_SURCHARGE
                )

        # If sell price provided, compute profit and re-sort by profit
        has_sell_price = bpc_sell_price > 0
        if has_sell_price:
            for opt in decryptor_comparison:
                runs = opt["runs_per_bpc"]
                if runs > 0 and opt["bpcs_needed"] > 0:
                    material_cost_per_bpc = opt["total_cost"] / opt["bpcs_needed"]
                    job_cost_per_bpc = (
                        invention_job_cost_per_run * opt["expected_attempts"]
                    )
                    invention_cost_per_bpc = material_cost_per_bpc + job_cost_per_bpc
                    opt["invention_cost_per_bpc"] = invention_cost_per_bpc
                    opt["job_cost_per_bpc"] = job_cost_per_bpc
                    opt["profit_per_bpc"] = bpc_sell_price - invention_cost_per_bpc
                else:
                    opt["invention_cost_per_bpc"] = 0
                    opt["job_cost_per_bpc"] = 0
                    opt["profit_per_bpc"] = 0

            decryptor_comparison.sort(
                key=lambda o: o.get("profit_per_bpc", 0), reverse=True
            )
            for opt in decryptor_comparison:
                opt["optimal"] = False
            if decryptor_comparison:
                decryptor_comparison[0]["optimal"] = True

        # Resolve names
        t1_bp_name = batch_type_names({t1_bp_id}).get(t1_bp_id, f"Unknown ({t1_bp_id})")

        # Datacore display
        datacores_display = []
        datacore_ids = {m[0] for m in invention_materials.get(t1_bp_id, [])}
        datacore_names = batch_type_names(datacore_ids)
        for mat_id, qty in invention_materials.get(t1_bp_id, []):
            datacores_display.append(
                {
                    "name": datacore_names.get(mat_id, f"Unknown ({mat_id})"),
                    "type_id": mat_id,
                    "quantity": qty,
                    "unit_price": prices.get(mat_id, 0.0),
                }
            )

        # Copy and invention times
        copy_time = activity_times.get(t1_bp_id, (0, 0))[1]
        invention_time = invention_times.get(t1_bp_id, 0)
        base_prob = invention_probabilities.get((t1_bp_id, t2_bp_id), 0.0)

        # Optimal slot split and supply chain
        supply_chain = None
        slot_allocation = None
        datacore_consumption = None

        if invention_time > 0 and copy_time > 0:
            copy_ratio = copy_time / invention_time
            attempts_per_day_per_slot = 86400 / invention_time

            # Use best decryptor option for projections
            best_opt = next(
                (o for o in decryptor_comparison if o.get("optimal")),
                decryptor_comparison[0] if decryptor_comparison else None,
            )

            cost_per_attempt = 0.0
            profit_per_bpc = None
            if best_opt:
                cost_per_attempt = best_opt["total_cost"] / max(
                    best_opt["expected_attempts"], 1
                )
                profit_per_bpc = best_opt.get("profit_per_bpc")

            # Per-character optimal split
            allocations = []
            total_lab_slots = 0
            total_invention_slots = 0
            total_copy_slots = 0
            total_bpos_needed = 0
            total_daily_attempts = 0.0
            total_daily_bpcs = 0.0
            total_daily_cost = 0.0
            total_daily_profit = 0.0

            for char in characters:
                if not char["can_invent"]:
                    continue

                lab_slots = char["lab_slots"]
                inv_slots = max(1, int(lab_slots / (1 + copy_ratio)))
                cp_slots = lab_slots - inv_slots
                bpos = cp_slots

                char_success = char["success_rate"]
                daily_attempts = attempts_per_day_per_slot * inv_slots
                daily_bpcs = daily_attempts * char_success
                daily_cost_val = daily_attempts * cost_per_attempt
                daily_profit_val = (
                    daily_bpcs * profit_per_bpc if profit_per_bpc is not None else None
                )

                total_lab_slots += lab_slots
                total_invention_slots += inv_slots
                total_copy_slots += cp_slots
                total_bpos_needed += bpos
                total_daily_attempts += daily_attempts
                total_daily_bpcs += daily_bpcs
                total_daily_cost += daily_cost_val
                if daily_profit_val is not None:
                    total_daily_profit += daily_profit_val

                allocations.append(
                    {
                        "char_name": char["char_name"],
                        "lab_slots": lab_slots,
                        "invention_slots": inv_slots,
                        "copy_slots": cp_slots,
                        "bpos_needed": bpos,
                        "success_rate": char_success,
                        "daily_attempts": daily_attempts,
                        "daily_bpcs": daily_bpcs,
                        "daily_cost": daily_cost_val,
                        "daily_profit": daily_profit_val,
                    }
                )

            # Supply chain summary
            supply_chain = {
                "copy_time_fmt": _format_duration(copy_time),
                "invention_time_fmt": _format_duration(invention_time),
                "copy_ratio": copy_ratio,
                "total_lab_slots": total_lab_slots,
                "total_invention_slots": total_invention_slots,
                "total_copy_slots": total_copy_slots,
                "total_bpos_needed": total_bpos_needed,
            }

            # Slot allocation
            if allocations:
                slot_allocation = {
                    "allocations": allocations,
                    "total_lab_slots": total_lab_slots,
                    "total_invention_slots": total_invention_slots,
                    "total_copy_slots": total_copy_slots,
                    "total_bpos_needed": total_bpos_needed,
                    "total_daily_bpcs": total_daily_bpcs,
                    "total_daily_cost": total_daily_cost,
                    "total_daily_profit": total_daily_profit
                    if has_sell_price
                    else None,
                    "total_monthly_profit": total_daily_profit * 30
                    if has_sell_price
                    else None,
                    "decryptor_name": best_opt["decryptor_name"]
                    if best_opt
                    else "None",
                }

            # Datacore consumption (total across all invention slots)
            daily_datacores = []
            daily_dc_total = 0.0
            for dc in datacores_display:
                daily_qty = dc["quantity"] * total_daily_attempts
                daily_cost_dc = daily_qty * dc["unit_price"]
                daily_dc_total += daily_cost_dc
                daily_datacores.append(
                    {
                        "name": dc["name"],
                        "daily_qty": daily_qty,
                        "daily_cost": daily_cost_dc,
                    }
                )
            datacore_consumption = {
                "datacores": daily_datacores,
                "daily_total_cost": daily_dc_total,
                "monthly_total_cost": daily_dc_total * 30,
            }

        return render_template(
            "invention.html",
            product={"type_id": product_type_id, "name": product_name},
            t1_bp_id=t1_bp_id,
            t1_bp_name=t1_bp_name,
            base_runs=base_runs,
            base_probability=base_prob,
            copy_time=copy_time,
            copy_time_fmt=_format_duration(copy_time),
            invention_time=invention_time,
            invention_time_fmt=_format_duration(invention_time),
            datacores=datacores_display,
            decryptor_comparison=decryptor_comparison,
            bpc_sell_price=bpc_sell_price if has_sell_price else "",
            has_sell_price=has_sell_price,
            invention_job_cost_per_run=invention_job_cost_per_run,
            characters=characters,
            has_characters=has_characters,
            supply_chain=supply_chain,
            datacore_consumption=datacore_consumption,
            slot_allocation=slot_allocation,
        )
