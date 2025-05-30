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


class InvTypes(db.Model):
    __bind_key__ = "static"
    __tablename__ = 'InvTypes'
    typeID = db.Column(db.Integer, primary_key=True)
    groupID = db.Column(db.Integer)
    typeName = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)
    mass = db.Column(db.Float)
    volume = db.Column(db.Float)
    capacity = db.Column(db.Float)
    portionSize = db.Column(db.Integer)
    raceID = db.Column(db.Integer)
    basePrice = db.Column(db.DECIMAL(19, 4))
    published = db.Column(db.Boolean)
    marketGroupID = db.Column(db.Integer)
    iconID = db.Column(db.Integer)
    soundID = db.Column(db.Integer)
    graphicID = db.Column(db.Integer)

    def __repr__(self):
        return f"InvTypes('{self.typeID}', '{self.groupID}', '{self.typeName}', '{self.description}')"


class InvTypeMaterials(db.Model):
    __bind_key__ = "static"
    __tablename__ = 'InvTypeMaterials'
    typeID = db.Column(db.Integer, primary_key=True)
    materialTypeID = db.Column(db.Integer, primary_key=True)
    quantity = db.Column(db.Integer, primary_key=True)

    def __repr__(self):
        return f"InvTypeMaterials('{self.typeID}', '{self.materialTypeID}', '{self.quantity}')"