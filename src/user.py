from flask import jsonify
from flask import render_template
from flask import Blueprint
from flask_login import login_required, current_user

from src.constants import ESI_BASE_URL
from src.utils import esi_get


class UserBlueprint(Blueprint):
    def __init__(self, name, import_name):
        super().__init__(name, import_name)
        self._add_routes()

    def _add_routes(self):
        self.add_url_rule('/user', 'user', login_required(self.get_user), methods=['GET'])

    def get_user(self):
        status, data = esi_get(f"{ESI_BASE_URL}/characters/{current_user.character_id}")
        if status == 200:
            return render_template('user.html', user_info=data)
        return jsonify({"error": "Failed to fetch user info"}), status or 500
