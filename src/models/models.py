from typing import Optional

import flask_sqlalchemy
from datetime import datetime, timezone, timedelta
from flask_login import UserMixin
from sqlalchemy import String, BigInteger, Integer, Text, Float, Boolean
from sqlalchemy import DECIMAL, DateTime
from sqlalchemy.orm import Mapped, mapped_column


db = flask_sqlalchemy.SQLAlchemy()


class User(db.Model, UserMixin):
    character_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    character_name: Mapped[str] = mapped_column(String(255), nullable=False)
    character_owner_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    main_character_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # SSO
    access_token: Mapped[str] = mapped_column(String(4096), nullable=False)
    access_token_expires: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    refresh_token: Mapped[str] = mapped_column(String(4096), nullable=False)
    token_refresh_failed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    def get_id(self):
        return self.character_id

    def get_sso_data(self):
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": (
                self.access_token_expires.astimezone(timezone.utc)
                - datetime.now(timezone.utc)
            ).total_seconds(),
        }

    def update_token(self, token_response):
        self.access_token = token_response["access_token"]
        self.refresh_token = token_response["refresh_token"]
        self.access_token_expires = datetime.now(timezone.utc) + timedelta(
            seconds=token_response["expires_in"]
        )

        db.session.commit()


class CachedLocations(db.Model):
    __bind_key__ = "base"
    __tablename__ = "CachedLocations"

    location_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_cost_index: Mapped[float] = mapped_column(Float, nullable=True)
    location_cost_index_last_updated: Mapped[datetime] = mapped_column(
        DateTime, nullable=True
    )

    def __repr__(self):
        return f"CachedLocations('{self.location_id}', '{self.location_name}')"


class CachedToonInfo(db.Model):
    __bind_key__ = "base"
    __tablename__ = "CachedToonInfo"

    character_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    character_name: Mapped[str] = mapped_column(String(255), nullable=False)
    corporation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    corporation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    alliance_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    alliance_name: Mapped[Optional[str]] = mapped_column(String(255))
    wallet_balance: Mapped[float] = mapped_column(Float, nullable=True)

    def __repr__(self):
        return f"CachedToonInfo('{self.character_id}', '{self.character_name}', '{self.corporation_id}', '{self.corporation_name}', '{self.alliance_id}', '{self.alliance_name}', '{self.wallet_balance}')"


class CachedMarketData(db.Model):
    __bind_key__ = "base"
    __tablename__ = "cached_market_data"

    type_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    adjusted_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cached_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CachedBlueprint(db.Model):
    __bind_key__ = "base"
    __tablename__ = "cached_blueprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    location_flag: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    runs: Mapped[int] = mapped_column(Integer, nullable=False)
    material_efficiency: Mapped[int] = mapped_column(Integer, nullable=False)
    time_efficiency: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CachedSkill(db.Model):
    __bind_key__ = "base"
    __tablename__ = "cached_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    skill_id: Mapped[int] = mapped_column(Integer, nullable=False)
    trained_skill_level: Mapped[int] = mapped_column(Integer, nullable=False)
    active_skill_level: Mapped[int] = mapped_column(Integer, nullable=False)
    skillpoints_in_skill: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InvTypes(db.Model):
    __bind_key__ = "static"
    __tablename__ = "InvTypes"

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    groupID: Mapped[Optional[int]] = mapped_column(Integer)
    typeName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    mass: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    capacity: Mapped[Optional[float]] = mapped_column(Float)
    portionSize: Mapped[Optional[int]] = mapped_column(Integer)
    raceID: Mapped[Optional[int]] = mapped_column(Integer)
    basePrice: Mapped[Optional[float]] = mapped_column(DECIMAL(19, 4))
    published: Mapped[Optional[bool]] = mapped_column(Boolean)
    marketGroupID: Mapped[Optional[int]] = mapped_column(Integer)
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    soundID: Mapped[Optional[int]] = mapped_column(Integer)
    graphicID: Mapped[Optional[int]] = mapped_column(Integer)

    def __repr__(self):
        return f"InvTypes('{self.typeID}', '{self.groupID}', '{self.typeName}', '{self.description}')"


class InvTypeMaterials(db.Model):
    __bind_key__ = "static"
    __tablename__ = "InvTypeMaterials"

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    materialTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, primary_key=True)

    def __repr__(self):
        return f"InvTypeMaterials('{self.typeID}', '{self.materialTypeID}', '{self.quantity}')"


class IndustryActivityMaterials(db.Model):
    __bind_key__ = "static"
    __tablename__ = "industryActivityMaterials"

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityID: Mapped[int] = mapped_column(Integer, primary_key=True)
    materialTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)


class IndustryActivityProducts(db.Model):
    __bind_key__ = "static"
    __tablename__ = "industryActivityProducts"

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityID: Mapped[int] = mapped_column(Integer, primary_key=True)
    productTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)


class IndustryBlueprints(db.Model):
    __bind_key__ = "static"
    __tablename__ = "industryBlueprints"

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    maxProductionLimit: Mapped[Optional[int]] = mapped_column(Integer)


class MapSolarSystems(db.Model):
    __bind_key__ = "static"
    __tablename__ = "mapSolarSystems"

    solarSystemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    solarSystemName: Mapped[Optional[str]] = mapped_column(String(100))
    security: Mapped[Optional[float]] = mapped_column(Float)


class InvGroups(db.Model):
    __bind_key__ = "static"
    __tablename__ = "invGroups"

    groupID: Mapped[int] = mapped_column(Integer, primary_key=True)
    categoryID: Mapped[Optional[int]] = mapped_column(Integer)
    groupName: Mapped[Optional[str]] = mapped_column(String(100))


class UserConfig(db.Model):
    __bind_key__ = "base"
    __tablename__ = "user_config"

    character_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
