from flask import jsonify
from flask import render_template
from flask import Blueprint
from flask_login import login_required, current_user

from src.constants import ESI_BASE_URL
from src.models.models import db, cached_toon_info
from src.utils import esi_get


class UserBlueprint(Blueprint):
    def __init__(self, name, import_name):
        super().__init__(name, import_name)
        self._add_routes()

    def _add_routes(self):
        self.add_url_rule('/user', 'user', login_required(self.get_user), methods=['GET'])

    def get_user(self):
        cached_info = cached_toon_info.query.filter_by(character_id=current_user.character_id).first()
        if cached_info:
            if cached_info.wallet_balance is None: # since its a seperate call that could fail independently, we want to try to update it if its missing
                wallet_status, wallet_data = esi_get(f"{ESI_BASE_URL}/characters/{current_user.character_id}/wallet")
                cached_info.wallet_balance = wallet_data[0]['balance'] if wallet_status == 200 and wallet_data else 0.0
                db.session.commit()
            return render_template('user.html', user_info={
                'character_id': cached_info.character_id,
                'character_name': cached_info.character_name,
                'corporation_id': cached_info.corporation_id,
                'corporation_name': cached_info.corporation_name,
                'alliance_id': cached_info.alliance_id,
                'alliance_name': cached_info.alliance_name,
                'wallet_balance': cached_info.wallet_balance
            })
        status, data = esi_get(f"{ESI_BASE_URL}/characters/{current_user.character_id}")
        if status == 200:
            alliance_id = data.get('alliance_id')
            corporation_id = data.get('corporation_id')
            data['alliance_name'] = self._alliance_id_to_name(alliance_id) if alliance_id else None
            data['corporation_name'] = self._corporation_id_to_name(corporation_id) if corporation_id else None
            wallet_status, wallet_data = esi_get(f"{ESI_BASE_URL}/characters/{current_user.character_id}/wallet")
            data['wallet_balance'] = wallet_data if wallet_status == 200 and wallet_data else 0.0
            cached_toon_info_entry = cached_toon_info(
                character_id=current_user.character_id,
                character_name=data['name'],
                corporation_id=data['corporation_id'],
                corporation_name=data['corporation_name'],
                alliance_id=data.get('alliance_id'),
                alliance_name=data.get('alliance_name'),
                wallet_balance=data['wallet_balance']
            )
            db.session.add(cached_toon_info_entry)
            db.session.commit()
            return render_template('user.html', user_info=data)
        return jsonify({"error": "Failed to fetch user info"}), status or 500

    def _alliance_id_to_name(self, alliance_id):
        status, data = esi_get(f"{ESI_BASE_URL}/alliances/{alliance_id}")
        if status == 200:
            return data.get('name', 'Unknown Alliance')
        return 'Unknown Alliance'

    def _corporation_id_to_name(self, corporation_id):
        status, data = esi_get(f"{ESI_BASE_URL}/corporations/{corporation_id}")
        if status == 200:
            return data.get('name', 'Unknown Corporation')
        return 'Unknown Corporation'

    def get_wallet_info(self):
        status, data = esi_get(f"{ESI_BASE_URL}/characters/{current_user.character_id}/wallet")
        if status == 200:
            return jsonify(data)
        return jsonify({"error": "Failed to fetch wallet info"}), status or 500
