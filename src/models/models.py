import flask_sqlalchemy
from datetime import datetime, timezone, timedelta
from flask_login import UserMixin


db = flask_sqlalchemy.SQLAlchemy()

class User(db.Model, UserMixin):
    character_id = db.Column(db.BigInteger, primary_key=True, autoincrement=False)
    character_name = db.Column(db.String(255), nullable=False)
    character_owner_hash = db.Column(db.String(255), nullable=False)

    # SSO
    access_token = db.Column(db.String(4096), nullable=False)
    access_token_expires = db.Column(db.DateTime, nullable=False)
    refresh_token = db.Column(db.String(4096), nullable=False)

    def get_id(self):
        return self.character_id
    
    def get_sso_data(self):
        return {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'expires_in': (
            self.access_token_expires.astimezone(timezone.utc) - datetime.now(timezone.utc)
            ).total_seconds()
        }
    
    def update_token(self, token_response):
        self.access_token = token_response['access_token']
        self.refresh_token = token_response['refresh_token']
        self.access_token_expires = datetime.now(timezone.utc) + \
            timedelta(seconds=token_response['expires_in'])
        
        db.session.commit()