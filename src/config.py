import json

from datetime import datetime, timezone

from flask import jsonify, render_template, request, Blueprint
from flask_login import login_required, current_user
from sqlalchemy import select

from src.models.models import (
    db,
    UserConfig,
    InvTypes,
    IndustryActivityMaterials,
)
from src.industry_constants import ALL_ME_RIG_GROUPS
from src.utils import search_systems as _search_systems


DEFAULT_CONFIG = {
    "stations": [],
    "blacklist": [],
    "build_slots": 10,
    "copy_slots": 10,
    "default_timeframe_hours": None,
    "industry_level": 5,
    "adv_industry_level": 5,
    "use_character_skills": False,
}


def load_user_config(character_id):
    """Load user config merged with defaults for any missing keys."""
    row = db.session.execute(
        select(UserConfig).where(UserConfig.character_id == character_id)
    ).scalar_one_or_none()

    if not row:
        return json.loads(json.dumps(DEFAULT_CONFIG))

    try:
        stored = json.loads(row.config_json)
    except (json.JSONDecodeError, TypeError):
        return json.loads(json.dumps(DEFAULT_CONFIG))

    config = json.loads(json.dumps(DEFAULT_CONFIG))
    for key in (
        "stations",
        "blacklist",
        "build_slots",
        "copy_slots",
        "default_timeframe_hours",
        "industry_level",
        "adv_industry_level",
        "use_character_skills",
    ):
        if key in stored:
            config[key] = stored[key]

    return config


class ConfigBlueprint(Blueprint):
    def __init__(self, name, import_name):
        super().__init__(name, import_name)
        self._add_routes()

    def _add_routes(self):
        self.add_url_rule(
            "/config", "config", login_required(self.get_config), methods=["GET"]
        )
        self.add_url_rule(
            "/config/search_systems",
            "config_search_systems",
            login_required(self.search_systems),
            methods=["GET"],
        )
        self.add_url_rule(
            "/config/search_items",
            "config_search_items",
            login_required(self.search_items),
            methods=["GET"],
        )
        self.add_url_rule(
            "/config/search_rigs",
            "config_search_rigs",
            login_required(self.search_rigs),
            methods=["GET"],
        )
        self.add_url_rule(
            "/config/stations/add",
            "station_add",
            login_required(self.station_add),
            methods=["POST"],
        )
        self.add_url_rule(
            "/config/stations/update",
            "station_update",
            login_required(self.station_update),
            methods=["POST"],
        )
        self.add_url_rule(
            "/config/stations/remove",
            "station_remove",
            login_required(self.station_remove),
            methods=["POST"],
        )
        self.add_url_rule(
            "/config/blacklist/add",
            "blacklist_add",
            login_required(self.blacklist_add),
            methods=["POST"],
        )
        self.add_url_rule(
            "/config/blacklist/remove",
            "blacklist_remove",
            login_required(self.blacklist_remove),
            methods=["POST"],
        )
        self.add_url_rule(
            "/config/settings/update",
            "settings_update",
            login_required(self.settings_update),
            methods=["POST"],
        )

    def get_config(self):
        config = load_user_config(current_user.character_id)

        # Resolve blacklist names
        blacklist_ids = config.get("blacklist", [])
        blacklist_items = []
        if blacklist_ids:
            rows = db.session.execute(
                select(InvTypes.typeID, InvTypes.typeName).where(
                    InvTypes.typeID.in_(blacklist_ids)
                )
            ).all()
            name_map = {r.typeID: r.typeName for r in rows}
            blacklist_items = [
                {"type_id": tid, "name": name_map.get(tid, f"Unknown ({tid})")}
                for tid in blacklist_ids
            ]

        # Resolve rig names for display
        all_rig_ids = set()
        for station in config.get("stations", []):
            for rig_id in station.get("rigs", []):
                if rig_id is not None:
                    all_rig_ids.add(rig_id)
        rig_names = {}
        if all_rig_ids:
            rows = db.session.execute(
                select(InvTypes.typeID, InvTypes.typeName).where(
                    InvTypes.typeID.in_(all_rig_ids)
                )
            ).all()
            rig_names = {r.typeID: r.typeName for r in rows}

        # Compute character summaries when use_character_skills is enabled
        character_summaries = []
        if config.get("use_character_skills"):
            from src.user import get_linked_character_ids
            from src.industry_utils import (
                load_character_skills,
                compute_character_capabilities,
                get_character_names,
            )

            char_ids = get_linked_character_ids(current_user)
            char_skills_map = load_character_skills(char_ids)
            char_names = get_character_names(char_ids)
            for cid in char_ids:
                skills = char_skills_map.get(cid, {})
                caps = compute_character_capabilities(skills)
                character_summaries.append(
                    {
                        "char_id": cid,
                        "name": char_names.get(cid, f"Character {cid}"),
                        "has_skills": bool(skills),
                        **caps,
                    }
                )

        return render_template(
            "config.html",
            config=config,
            blacklist_items=blacklist_items,
            rig_names=rig_names,
            character_summaries=character_summaries,
        )

    def search_systems(self):
        q = request.args.get("q", "", type=str).strip()
        return jsonify(_search_systems(q))

    def search_items(self):
        q = request.args.get("q", "", type=str).strip()
        if len(q) < 2:
            return jsonify([])
        results = db.session.execute(
            select(InvTypes.typeID, InvTypes.typeName)
            .join(
                IndustryActivityMaterials,
                IndustryActivityMaterials.materialTypeID == InvTypes.typeID,
            )
            .where(IndustryActivityMaterials.activityID == 1)
            .where(InvTypes.typeName.ilike(f"%{q}%"))
            .where(InvTypes.published)
            .distinct()
            .limit(15)
        ).all()
        return jsonify([{"type_id": r.typeID, "name": r.typeName} for r in results])

    def search_rigs(self):
        """Autocomplete for engineering complex rigs, filtered by rig size."""
        q = request.args.get("q", "", type=str).strip()
        rig_size = request.args.get("rig_size", 0, type=int)
        if len(q) < 2:
            return jsonify([])

        # Filter groups by rig size
        size_to_groups = {2: set(), 3: set(), 4: set()}
        for group_id in ALL_ME_RIG_GROUPS:
            if group_id <= 1840:
                size_to_groups[2].add(group_id)
            elif group_id <= 1862:
                size_to_groups[3].add(group_id)
            else:
                size_to_groups[4].add(group_id)

        allowed_groups = set()
        if rig_size in size_to_groups:
            allowed_groups = size_to_groups[rig_size]

        if not allowed_groups:
            return jsonify([])

        results = db.session.execute(
            select(InvTypes.typeID, InvTypes.typeName)
            .where(InvTypes.groupID.in_(allowed_groups))
            .where(InvTypes.typeName.ilike(f"%{q}%"))
            .where(InvTypes.published)
            .limit(15)
        ).all()
        return jsonify([{"type_id": r.typeID, "name": r.typeName} for r in results])

    def station_add(self):
        char_id = current_user.character_id
        data = request.json
        if not data or not data.get("name"):
            return jsonify({"error": "station name required"}), 400

        config = load_user_config(char_id)
        stations = config.get("stations", [])

        # Generate next ID
        next_id = max((s.get("id", 0) for s in stations), default=0) + 1

        station = {
            "id": next_id,
            "name": data["name"],
            "system_id": data.get("system_id"),
            "system_name": data.get("system_name"),
            "structure_type": data.get("structure_type", "raitaru"),
            "facility_tax": data.get("facility_tax", 10.0),
            "rigs": data.get("rigs", [None, None, None]),
        }
        stations.append(station)
        config["stations"] = stations

        self._save_config_json(char_id, config)
        return jsonify(self._stations_response(config["stations"]))

    def station_update(self):
        char_id = current_user.character_id
        data = request.json
        station_id = data.get("id") if data else None
        if station_id is None:
            return jsonify({"error": "station id required"}), 400

        config = load_user_config(char_id)
        stations = config.get("stations", [])

        for s in stations:
            if s.get("id") == station_id:
                s["name"] = data.get("name", s["name"])
                s["system_id"] = data.get("system_id", s.get("system_id"))
                s["system_name"] = data.get("system_name", s.get("system_name"))
                s["structure_type"] = data.get(
                    "structure_type", s.get("structure_type")
                )
                s["facility_tax"] = data.get("facility_tax", s.get("facility_tax"))
                s["rigs"] = data.get("rigs", s.get("rigs"))
                break
        else:
            return jsonify({"error": "station not found"}), 404

        config["stations"] = stations
        self._save_config_json(char_id, config)
        return jsonify(self._stations_response(config["stations"]))

    def station_remove(self):
        char_id = current_user.character_id
        data = request.json
        station_id = data.get("id") if data else None
        if station_id is None:
            return jsonify({"error": "station id required"}), 400

        config = load_user_config(char_id)
        config["stations"] = [
            s for s in config.get("stations", []) if s.get("id") != station_id
        ]

        self._save_config_json(char_id, config)
        return jsonify(self._stations_response(config["stations"]))

    def blacklist_add(self):
        char_id = current_user.character_id
        type_id = (
            request.json.get("type_id")
            if request.is_json
            else request.form.get("type_id", type=int)
        )
        if not type_id:
            return jsonify({"error": "type_id required"}), 400

        type_id = int(type_id)
        config = load_user_config(char_id)
        if type_id not in config["blacklist"]:
            config["blacklist"].append(type_id)

        self._save_config_json(char_id, config)
        return jsonify(self._blacklist_response(config["blacklist"]))

    def blacklist_remove(self):
        char_id = current_user.character_id
        type_id = (
            request.json.get("type_id")
            if request.is_json
            else request.form.get("type_id", type=int)
        )
        if not type_id:
            return jsonify({"error": "type_id required"}), 400

        type_id = int(type_id)
        config = load_user_config(char_id)
        config["blacklist"] = [t for t in config["blacklist"] if t != type_id]

        self._save_config_json(char_id, config)
        return jsonify(self._blacklist_response(config["blacklist"]))

    def settings_update(self):
        char_id = current_user.character_id
        data = request.json
        if not data:
            return jsonify({"error": "no data"}), 400

        config = load_user_config(char_id)

        if "build_slots" in data:
            val = int(data["build_slots"])
            config["build_slots"] = max(1, min(50, val))
        if "copy_slots" in data:
            val = int(data["copy_slots"])
            config["copy_slots"] = max(1, min(50, val))
        if "default_timeframe_hours" in data:
            val = data["default_timeframe_hours"]
            if val is None or val == "" or val == 0:
                config["default_timeframe_hours"] = None
            else:
                config["default_timeframe_hours"] = max(1, float(val))
        if "industry_level" in data:
            val = int(data["industry_level"])
            config["industry_level"] = max(0, min(5, val))
        if "adv_industry_level" in data:
            val = int(data["adv_industry_level"])
            config["adv_industry_level"] = max(0, min(5, val))
        if "use_character_skills" in data:
            config["use_character_skills"] = bool(data["use_character_skills"])

        self._save_config_json(char_id, config)
        return jsonify(
            {
                "build_slots": config["build_slots"],
                "copy_slots": config["copy_slots"],
                "default_timeframe_hours": config["default_timeframe_hours"],
                "industry_level": config["industry_level"],
                "adv_industry_level": config["adv_industry_level"],
                "use_character_skills": config["use_character_skills"],
            }
        )

    def _save_config_json(self, char_id, config):
        row = db.session.execute(
            select(UserConfig).where(UserConfig.character_id == char_id)
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if row:
            row.config_json = json.dumps(config)
            row.updated_at = now
        else:
            row = UserConfig(
                character_id=char_id,
                config_json=json.dumps(config),
                updated_at=now,
            )
            db.session.add(row)
        db.session.commit()

    def _stations_response(self, stations):
        """Build response with resolved rig names."""
        all_rig_ids = set()
        for s in stations:
            for rig_id in s.get("rigs", []):
                if rig_id is not None:
                    all_rig_ids.add(rig_id)
        rig_names = {}
        if all_rig_ids:
            rows = db.session.execute(
                select(InvTypes.typeID, InvTypes.typeName).where(
                    InvTypes.typeID.in_(all_rig_ids)
                )
            ).all()
            rig_names = {r.typeID: r.typeName for r in rows}

        return {"stations": stations, "rig_names": rig_names}

    def _blacklist_response(self, blacklist_ids):
        items = []
        if blacklist_ids:
            rows = db.session.execute(
                select(InvTypes.typeID, InvTypes.typeName).where(
                    InvTypes.typeID.in_(blacklist_ids)
                )
            ).all()
            name_map = {r.typeID: r.typeName for r in rows}
            items = [
                {"type_id": tid, "name": name_map.get(tid, f"Unknown ({tid})")}
                for tid in blacklist_ids
            ]
        return {"blacklist": items}
