import requests
import os
import json
import base64

from flask import Flask
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for
from flask import request
from flask import jsonify
from flask import Blueprint
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, current_user
from dotenv import load_dotenv

from src.models.models import db, User
from src.application import Application
from datetime import datetime, timedelta, timezone



class AuthBlueprint(Blueprint):
    def __init__(self, name, import_name, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.callback_url = os.environ.get('CALLBACK_URL')
        super().__init__(name, import_name)
        
        self._add_routes()

    def _add_routes(self):
        self.add_url_rule('/login', 'login', self.login, methods=['GET'])
        self.add_url_rule('/callback', 'callback', self.callback, methods=['GET'])
        self.add_url_rule('/logout', 'logout', self.logout, methods=['GET'])

    def login(self):
        """ Redirect to the SSO login page """
        sso_url = (
            f"https://login.eveonline.com/oauth/authorize?response_type=code&"
            f"redirect_uri={url_for('auth.callback', _external=True)}&"
            f"client_id={self.client_id}&scope=publicData&state=spudtest"
        )
        return redirect(sso_url)
    
    def callback(self):
        """ Handle the SSO callback """
        code = request.args.get('code')
        state = request.args.get('state')

        if state != 'spudtest':
            return "Invalid state", 400

        token_url = "https://login.eveonline.com/oauth/token"
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()}'
        }
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': url_for('auth.callback', _external=True)
        }

        response = requests.post(token_url, headers=headers, data=data)
        token_response = response.json()

        if response.status_code != 200:
            return jsonify(token_response), response.status_code

        # Store the user in the database
        user_info_url = "https://login.eveonline.com/oauth/verify"
        user_info_headers = {
            'Authorization': f"Bearer {token_response['access_token']}"
        }
        
        user_info_response = requests.get(user_info_url, headers=user_info_headers)
        
        if user_info_response.status_code != 200:
            return jsonify(user_info_response.json()), user_info_response.status_code
        
        user_info = user_info_response.json()
        
        # Check if the user already exists
        existing_user = User.query.filter_by(character_id=user_info['CharacterID']).first()
        
        if existing_user:
            existing_user.update_token(token_response)
            db.session.commit()
            session['user_id'] = existing_user.character_id
            return redirect(url_for('index'))
        
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_response['expires_in'])
        
        # Create a new user
        new_user = User(
            character_id=user_info['CharacterID'],
            character_name=user_info['CharacterName'],
            character_owner_hash=user_info['CharacterOwnerHash'],
            access_token=token_response['access_token'],
            access_token_expires=expires_at,
            refresh_token=token_response['refresh_token']
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        session['user_id'] = new_user.character_id
        login_user(new_user)
        
        return redirect(url_for('index'))
    
    def logout(self):
        """ Log the user out and clear the session """
        session.pop('user_id', None)
        logout_user()
        return redirect(url_for('index'))