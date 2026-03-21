from typing import Optional

import flask_sqlalchemy
from datetime import datetime, timezone, timedelta
from flask_login import UserMixin
from sqlalchemy import String, BigInteger, Integer, Text, Float, Boolean
from sqlalchemy import DateTime, select as sa_select
from sqlalchemy.orm import Mapped, mapped_column, column_property


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
    token_refresh_failed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )

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
    cached_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

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


class EveTypeName(db.Model):
    __bind_key__ = "static"
    __tablename__ = "EveTypeName"

    parentTypeId: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeId2: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeCategory: Mapped[str] = mapped_column(Text, primary_key=True)
    en: Mapped[Optional[str]] = mapped_column(Text)


class EveType(db.Model):
    __bind_key__ = "static"
    __tablename__ = "EveType"

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    groupID: Mapped[Optional[int]] = mapped_column(Integer)
    published: Mapped[Optional[int]] = mapped_column(Integer)
    marketGroupID: Mapped[Optional[int]] = mapped_column(Integer)
    portionSize: Mapped[Optional[int]] = mapped_column(Integer)
    basePrice: Mapped[Optional[int]] = mapped_column(Integer)
    volume: Mapped[Optional[int]] = mapped_column(Integer)
    mass: Mapped[Optional[int]] = mapped_column(Integer)
    capacity: Mapped[Optional[int]] = mapped_column(Integer)
    raceID: Mapped[Optional[int]] = mapped_column(Integer)
    soundID: Mapped[Optional[int]] = mapped_column(Integer)
    graphicID: Mapped[Optional[int]] = mapped_column(Integer)


# typeName via correlated subquery to EveTypeName (set up after both classes exist)
EveType.typeName = column_property(
    sa_select(EveTypeName.en)
    .where(EveTypeName.parentTypeId == EveType.typeID)
    .where(EveTypeName.parentTypeCategory == "")
    .correlate(EveType)
    .scalar_subquery()
)


class TypeMaterial(db.Model):
    __bind_key__ = "static"
    __tablename__ = "TypeMaterial"

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    materialTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)


class BlueprintActivityMaterial(db.Model):
    __bind_key__ = "static"
    __tablename__ = "BlueprintActivityMaterial"

    typeID: Mapped[int] = mapped_column("blueprintTypeID", Integer, primary_key=True)
    activityID: Mapped[str] = mapped_column("activityName", Text, primary_key=True)
    materialTypeID: Mapped[int] = mapped_column("typeId", Integer, primary_key=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)


class BlueprintProduct(db.Model):
    __bind_key__ = "static"
    __tablename__ = "BlueprintProduct"

    typeID: Mapped[int] = mapped_column("blueprintTypeID", Integer, primary_key=True)
    activityID: Mapped[str] = mapped_column("activityName", Text, primary_key=True)
    productTypeID: Mapped[int] = mapped_column("typeID", Integer, primary_key=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)
    probability: Mapped[Optional[float]] = mapped_column(Float)


class Blueprints(db.Model):
    __bind_key__ = "static"
    __tablename__ = "Blueprints"

    typeID: Mapped[int] = mapped_column("blueprintTypeID", Integer, primary_key=True)
    maxProductionLimit: Mapped[Optional[int]] = mapped_column(Integer)


class SolarSystemName(db.Model):
    __bind_key__ = "static"
    __tablename__ = "SolarSystemName"

    parentTypeId: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeId2: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeCategory: Mapped[str] = mapped_column(Text, primary_key=True)
    en: Mapped[Optional[str]] = mapped_column(Text)


class MapSolarSystem(db.Model):
    __bind_key__ = "static"
    __tablename__ = "mapSolarSystem"

    solarSystemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    security: Mapped[Optional[float]] = mapped_column("securityStatus", Float)


# solarSystemName via correlated subquery to SolarSystemName
MapSolarSystem.solarSystemName = column_property(
    sa_select(SolarSystemName.en)
    .where(SolarSystemName.parentTypeId == MapSolarSystem.solarSystemID)
    .where(SolarSystemName.parentTypeCategory == "")
    .correlate(MapSolarSystem)
    .scalar_subquery()
)


class EveGroup(db.Model):
    __bind_key__ = "static"
    __tablename__ = "EveGroup"

    groupID: Mapped[int] = mapped_column(Integer, primary_key=True)
    categoryID: Mapped[Optional[int]] = mapped_column(Integer)


class UserConfig(db.Model):
    __bind_key__ = "base"
    __tablename__ = "user_config"

    character_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
