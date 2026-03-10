import requests
import os
import base64

from flask import redirect
from flask import request
from flask import session
from flask import url_for
from flask import jsonify
from flask import Blueprint
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import select

from src.models.models import db, User
from src.utils import generate_token
from src.constants import ESI_BASE_URL
from src.tasks import fetch_skills_task

from datetime import datetime, timedelta, timezone


class AuthBlueprint(Blueprint):
    def __init__(self, name, import_name, client_id, client_secret, scopes):
        self.client_id = client_id
        self.client_secret = client_secret
        self.callback_url = os.environ.get("CALLBACK_URL")
        self.scopes = scopes
        # self.scope = self.scopes.split(',') if self.scopes else 'publicData'
        super().__init__(name, import_name)

        self._add_routes()

    def _add_routes(self):
        self.add_url_rule("/login", "login", self.login, methods=["GET"])
        self.add_url_rule("/callback", "callback", self.callback, methods=["GET"])
        self.add_url_rule("/logout", "logout", self.logout, methods=["GET"])
        self.add_url_rule(
            "/link",
            "link_character",
            login_required(self.link_character),
            methods=["GET"],
        )

    def _get_user_info(self, token):
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        character_id = session.get("user_id")
        if character_id is None:
            return None
        response = requests.get(
            f"{ESI_BASE_URL}/characters/{character_id}", headers=headers, timeout=10
        )
        if response.status_code == 200:
            return response.json()
        return None

    def login(self):
        """Redirect to the SSO login page"""
        token = generate_token()
        session["state"] = token
        sso_url = (
            f"https://login.eveonline.com/v2/oauth/authorize?response_type=code&"
            f"redirect_uri={url_for('auth.callback', _external=True)}&"
            f"client_id={self.client_id}&scope={self.scopes}&state={token}"
        )
        return redirect(sso_url)

    def link_character(self):
        """Redirect to the SSO login page"""
        token = generate_token()
        session["state"] = token
        sso_url = (
            f"https://login.eveonline.com/v2/oauth/authorize?response_type=code&"
            f"redirect_uri={url_for('auth.callback', _external=True)}&"
            f"client_id={self.client_id}&scope={self.scopes}&state={token}"
        )
        return redirect(sso_url)

    def callback(self):
        """Handle the SSO callback"""
        code = request.args.get("code")
        state = request.args.get("state")

        if state != session.get("state"):
            # State does not match, possible CSRF attack
            return "Invalid state", 400

        token_url = "https://login.eveonline.com/v2/oauth/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {base64.urlsafe_b64encode(f'{self.client_id}:{self.client_secret}'.encode()).decode()}",
        }
        data = {
            "grant_type": "authorization_code",
            "code": code,
            # 'redirect_uri': url_for('auth.callback', _external=True)
        }

        response = requests.post(token_url, headers=headers, data=data, timeout=10)
        token_response = response.json()
        if response.status_code != 200:
            return jsonify(response), response.status_code

        # Store the user in the database
        user_info_url = "https://login.eveonline.com/oauth/verify"
        user_info_headers = {
            "Authorization": f"Bearer {token_response['access_token']}"
        }

        user_info_response = requests.get(
            user_info_url, headers=user_info_headers, timeout=10
        )

        if user_info_response.status_code != 200:
            return jsonify(user_info_response.json()), user_info_response.status_code

        user_info = user_info_response.json()

        if current_user.is_authenticated:
            existing_user = db.session.execute(
                select(User).where(User.character_id == user_info["CharacterID"])
            ).scalar_one_or_none()

            if existing_user:
                existing_user.update_token(token_response)
                existing_user.token_refresh_failed = False
                old_main_id = existing_user.main_character_id
                new_main_id = current_user.main_character_id
                if old_main_id != new_main_id:
                    old_group = (
                        db.session.execute(
                            select(User).where(User.main_character_id == old_main_id)
                        )
                        .scalars()
                        .all()
                    )
                    for user in old_group:
                        user.main_character_id = new_main_id
                db.session.commit()
                try:
                    fetch_skills_task.delay(existing_user.character_id)
                except Exception:
                    pass
                session["user_id"] = current_user.character_id
                return redirect(url_for("user.user"))

            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=token_response["expires_in"]
            )

            new_user = User(
                character_id=user_info["CharacterID"],
                character_name=user_info["CharacterName"],
                character_owner_hash=user_info["CharacterOwnerHash"],
                main_character_id=current_user.character_id,
                access_token=token_response["access_token"],
                access_token_expires=expires_at,
                refresh_token=token_response["refresh_token"],
            )

            db.session.add(new_user)
            db.session.commit()
            try:
                fetch_skills_task.delay(new_user.character_id)
            except Exception:
                pass

            session["user_id"] = current_user.character_id
            return redirect(url_for("user.user"))

        try:
            # Check if the user already exists
            existing_user = db.session.execute(
                select(User).where(User.character_id == user_info["CharacterID"])
            ).scalar_one_or_none()

            if existing_user:
                existing_user.update_token(token_response)
                existing_user.token_refresh_failed = False
                db.session.commit()
                session["user_id"] = existing_user.character_id
                login_user(existing_user)
                return redirect(url_for("user.user"))

            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=token_response["expires_in"]
            )

            # Create a new user
            new_user = User(
                character_id=user_info["CharacterID"],
                character_name=user_info["CharacterName"],
                character_owner_hash=user_info["CharacterOwnerHash"],
                main_character_id=user_info["CharacterID"],
                access_token=token_response["access_token"],
                access_token_expires=expires_at,
                refresh_token=token_response["refresh_token"],
            )

            db.session.add(new_user)
            db.session.commit()

            session["user_id"] = new_user.character_id
            login_user(new_user)

        except Exception as e:
            logout_user()
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

        return redirect(url_for("user.user"))

    def logout(self):
        """Log the user out and clear the session"""
        session.pop("user_id", None)
        logout_user()
        return redirect(url_for("index"))
