from flask import jsonify
from flask import render_template
from flask import Blueprint
from flask_login import login_required, current_user
from sqlalchemy import select

from src.constants import ESI_BASE_URL
from src.models.models import db, CachedToonInfo, User
from src.utils import esi_get


class UserBlueprint(Blueprint):
    def __init__(self, name, import_name):
        super().__init__(name, import_name)
        self._add_routes()

    def _add_routes(self):
        self.add_url_rule('/user', 'user', login_required(self.get_user), methods=['GET'])

    def get_user(self):
        user_info = self._fetch_and_cache_character_info(current_user)
        if user_info is None:
            return jsonify({"error": "Failed to fetch user info"}), 500

        linked_users = self.find_linked_users()
        linked_characters = []
        for linked_user in linked_users:
            info = self._fetch_and_cache_character_info(linked_user)
            if info:
                linked_characters.append(info)

        return render_template('user.html', user_info=user_info, linked_characters=linked_characters)

    def _fetch_and_cache_character_info(self, user):
        """Fetch character info from cache or ESI. Returns a user_info dict or None on failure."""
        character_id = user.character_id
        headers = {
            "Authorization": f"Bearer {user.access_token}",
            "Content-Type": "application/json"
        }

        cached_info = CachedToonInfo.query.filter_by(character_id=character_id).first()
        if cached_info:
            if cached_info.wallet_balance is None:
                wallet_status, wallet_data = esi_get(
                    f"{ESI_BASE_URL}/characters/{character_id}/wallet", headers=headers
                )
                cached_info.wallet_balance = wallet_data if wallet_status == 200 and wallet_data is not None else 0.0
                db.session.commit()
            return {
                'character_id': cached_info.character_id,
                'character_name': cached_info.character_name,
                'corporation_id': cached_info.corporation_id,
                'corporation_name': cached_info.corporation_name,
                'alliance_id': cached_info.alliance_id,
                'alliance_name': cached_info.alliance_name,
                'wallet_balance': cached_info.wallet_balance,
            }

        status, data = esi_get(f"{ESI_BASE_URL}/characters/{character_id}", headers=headers)
        if status != 200:
            return None

        alliance_id = data.get('alliance_id')
        corporation_id = data.get('corporation_id')
        data['alliance_name'] = self._alliance_id_to_name(alliance_id) if alliance_id else None
        data['corporation_name'] = self._corporation_id_to_name(corporation_id) if corporation_id else None

        wallet_status, wallet_data = esi_get(
            f"{ESI_BASE_URL}/characters/{character_id}/wallet", headers=headers
        )
        data['wallet_balance'] = wallet_data if wallet_status == 200 and wallet_data is not None else 0.0

        entry = CachedToonInfo(
            character_id=character_id,
            character_name=data['name'],
            corporation_id=data['corporation_id'],
            corporation_name=data['corporation_name'],
            alliance_id=data.get('alliance_id'),
            alliance_name=data.get('alliance_name'),
            wallet_balance=data['wallet_balance'],
        )
        db.session.add(entry)
        db.session.commit()

        return {
            'character_id': character_id,
            'character_name': data['name'],
            'corporation_id': data['corporation_id'],
            'corporation_name': data['corporation_name'],
            'alliance_id': data.get('alliance_id'),
            'alliance_name': data.get('alliance_name'),
            'wallet_balance': data['wallet_balance'],
        }

    def find_linked_users(self):
        """Return all User records sharing the same main_character_id, excluding current_user."""
        return db.session.execute(
            select(User).where(
                User.main_character_id == current_user.main_character_id,
                User.character_id != current_user.character_id
            )
        ).scalars().all()

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
