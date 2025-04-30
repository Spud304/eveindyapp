import requests
import os
import base64

from flask import redirect
from flask import request
from flask import session
from flask import url_for
from flask import request
from flask import jsonify
from flask import render_template
from flask import Blueprint
from flask_login import login_user, logout_user, current_user

from src.models.models import db, User, InvTypes
from src.utils import generate_token
from src.constants import ESI_BASE_URL

from datetime import datetime, timedelta, timezone

class IndustryBlueprint(Blueprint):
    def __init__(self, name, import_name):
        super().__init__(name, import_name)
        self._add_routes()
        
    def _add_routes(self):
        self.add_url_rule('/industry', 'industry', self.get_industry, methods=['GET'])
        self.add_url_rule('/industry/blueprints', 'blueprints', self.get_blueprints, methods=['GET'])
        self.add_url_rule('/industry/jobs', 'jobs', self.get_jobs, methods=['GET'])


    def get_industry(self):
        user = User.query.filter_by(character_id=session.get('user_id')).first()
        token = user.get_sso_data()['access_token'] if user else None
        if token is None:
            return jsonify({"error": "User not logged in"}), 401
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        character_id = session.get('user_id')
        
        if character_id is None:
            return jsonify({"error": "User not logged in"}), 401
        
        response = requests.get(f"{ESI_BASE_URL}/characters/{character_id}/industry", headers=headers)
        
        if response.status_code == 200:
            return render_template('industry.html', industry_info=response.json())
        
        return jsonify({"error": "Failed to fetch industry info"}), response.status_code
    
    def get_blueprints(self):
        user = User.query.filter_by(character_id=session.get('user_id')).first()
        token = user.get_sso_data()['access_token'] if user else None
        if token is None:
            return jsonify({"error": "User not logged in"}), 401
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        character_id = session.get('user_id')
        
        if character_id is None:
            return jsonify({"error": "User not logged in"}), 401
        
        response = requests.get(f"{ESI_BASE_URL}/characters/{character_id}/blueprints", headers=headers)

        j = response.json()

        for i in j:
            if i['type_id'] == 0:
                i['type_id'] = None
            else:
                blueprint = InvTypes.query.filter_by(typeID=i['type_id']).first()
                if blueprint is not None:
                    i['type_name'] = blueprint.typeName
                else:
                    i['type_name'] = None
        
        if response.status_code == 200:
            return render_template('blueprints.html', blueprints=j)
        
        return jsonify({"error": "Failed to fetch blueprints info"}), response.status_code
    
    def get_jobs(self):
        user = User.query.filter_by(character_id=session.get('user_id')).first()
        token = user.get_sso_data()['access_token'] if user else None
        if token is None:
            return jsonify({"error": "User not logged in"}), 401
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        character_id = session.get('user_id')
        
        if character_id is None:
            return jsonify({"error": "User not logged in"}), 401
        
        response = requests.get(f"{ESI_BASE_URL}/characters/{character_id}/industry/jobs", headers=headers)
        
        if response.status_code == 200:
            return render_template('jobs.html', jobs_info=response.json())
        
        return jsonify({"error": "Failed to fetch jobs info"}), response.status_code
    
    def _get_blueprint_info(self, blueprint_id):
        blueprint = InvTypes.query.filter_by(type_id=blueprint_id).first()

        if blueprint:
            return {
                "type_id": blueprint.typeID,
                "type_name": blueprint.typeName,
                "description": blueprint.description,
                "icon_id": blueprint.iconID,
            }
        
        return None
    
    def _get_item_info(self, type_id):
        items = InvTypes.query.filter_by(typeID=type_id).all()
        item_info = []
        for item in items:
            item_info.append({
                "type_id": item.typeID,
                "activity_id": item.activityID,
                "material_type_id": item.materialTypeID,
                "quantity": item.quantity,
            })

        return item_info