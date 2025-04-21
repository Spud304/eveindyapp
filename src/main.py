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
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv

from src.models.models import db, User
from src.application import Application
from src.auth import AuthBlueprint

load_dotenv()

CLIENT_ID = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
CALLBACK_URL = os.environ.get('CALLBACK_URL')
DB_NAME = os.environ.get('DB_NAME')

if CLIENT_ID is None or CLIENT_SECRET is None or CALLBACK_URL is None:
    raise ValueError("CLIENT_ID, CLIENT_SECRET, and CALLBACK_URL must be set in the environment variables.")

if DB_NAME is None:
    raise ValueError("DB_NAME must be set in the environment variables.")

print(f"DB_NAME: {DB_NAME}")
print(f"CLIENT_ID: {CLIENT_ID}")
print(f"CLIENT_SECRET: {CLIENT_SECRET}")
print(f"CALLBACK_URL: {CALLBACK_URL}")

app = Application(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_NAME}.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True
app.config['SECRET_KEY'] = os.urandom(24)

db.init_app(app)


login_manager = LoginManager()
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    """ Load the user from the database """
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

auth_blueprint = AuthBlueprint('auth', __name__, CLIENT_ID, CLIENT_SECRET)
app.register_blueprint(auth_blueprint)


if __name__ == '__main__':
    app.run(debug=True)