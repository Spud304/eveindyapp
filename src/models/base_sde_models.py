from typing import Optional

from sqlalchemy import Float, Index, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ── Core type/group/category tables ──────────────────────────────────
class EveType(Base):
    """Items, blueprints, etc."""

    __bind_key__ = "static"
    __tablename__ = "EveType"

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    groupID: Mapped[Optional[int]] = mapped_column(Integer)
    marketGroupID: Mapped[Optional[int]] = mapped_column(Integer)
    published: Mapped[Optional[int]] = mapped_column(Integer)
    portionSize: Mapped[Optional[int]] = mapped_column(Integer)
    basePrice: Mapped[Optional[int]] = mapped_column(Integer)
    capacity: Mapped[Optional[int]] = mapped_column(Integer)
    mass: Mapped[Optional[int]] = mapped_column(Integer)
    volume: Mapped[Optional[int]] = mapped_column(Integer)
    raceID: Mapped[Optional[int]] = mapped_column(Integer)
    metaGroupID: Mapped[Optional[int]] = mapped_column(Integer)
    soundID: Mapped[Optional[int]] = mapped_column(Integer)
    graphicID: Mapped[Optional[int]] = mapped_column(Integer)
    factionID: Mapped[Optional[int]] = mapped_column(Integer)
    radius: Mapped[Optional[int]] = mapped_column(Integer)
    sofFactionName: Mapped[Optional[str]] = mapped_column(Text)


class EveTypeName(Base):
    """Localized names for types. Use parentTypeId=typeID, parentTypeCategory=''."""

    __bind_key__ = "static"
    __tablename__ = "EveTypeName"

    parentTypeId: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeId2: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeCategory: Mapped[str] = mapped_column(Text, primary_key=True)
    en: Mapped[Optional[str]] = mapped_column(Text)
    de: Mapped[Optional[str]] = mapped_column(Text)
    fr: Mapped[Optional[str]] = mapped_column(Text)
    es: Mapped[Optional[str]] = mapped_column(Text)
    ja: Mapped[Optional[str]] = mapped_column(Text)
    ko: Mapped[Optional[str]] = mapped_column(Text)
    ru: Mapped[Optional[str]] = mapped_column(Text)
    zh: Mapped[Optional[str]] = mapped_column(Text)


class EveGroup(Base):
    """Item groups (ships, modules, etc.)."""

    __bind_key__ = "static"
    __tablename__ = "EveGroup"

    groupID: Mapped[int] = mapped_column(Integer, primary_key=True)
    categoryID: Mapped[Optional[int]] = mapped_column(Integer)
    anchorable: Mapped[Optional[int]] = mapped_column(Integer)
    anchored: Mapped[Optional[int]] = mapped_column(Integer)
    fittableNonSingleton: Mapped[Optional[int]] = mapped_column(Integer)
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    published: Mapped[Optional[int]] = mapped_column(Integer)
    useBasePrice: Mapped[Optional[int]] = mapped_column(Integer)


class GroupName(Base):
    """Localized names for groups."""

    __bind_key__ = "static"
    __tablename__ = "GroupName"

    parentTypeId: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeId2: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeCategory: Mapped[str] = mapped_column(Text, primary_key=True)
    en: Mapped[Optional[str]] = mapped_column(Text)


class Category(Base):
    """Item categories."""

    __bind_key__ = "static"
    __tablename__ = "Category"

    categoryID: Mapped[int] = mapped_column(Integer, primary_key=True)
    published: Mapped[Optional[int]] = mapped_column(Integer)


class MarketGroup(Base):
    """Market groups."""

    __bind_key__ = "static"
    __tablename__ = "MarketGroup"

    marketGroupId: Mapped[int] = mapped_column(Integer, primary_key=True)
    hasTypes: Mapped[Optional[int]] = mapped_column(Integer)
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    parentGroupID: Mapped[Optional[int]] = mapped_column(Integer)


# ── Blueprint / industry tables ──────────────────────────────────────
class Blueprints(Base):
    """Blueprint metadata (max production limit)."""

    __bind_key__ = "static"
    __tablename__ = "Blueprints"

    blueprintTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    maxProductionLimit: Mapped[Optional[int]] = mapped_column(Integer)


class BlueprintActivityType(Base):
    """Activity times per blueprint (manufacturing, copying, invention, etc.)."""

    __bind_key__ = "static"
    __tablename__ = "BlueprintActivityType"

    blueprintTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityName: Mapped[str] = mapped_column(Text, primary_key=True)
    time: Mapped[Optional[int]] = mapped_column(Integer)


class BlueprintActivityMaterial(Base):
    """Materials required for a blueprint activity."""

    __bind_key__ = "static"
    __tablename__ = "BlueprintActivityMaterial"

    blueprintTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityName: Mapped[str] = mapped_column(Text, primary_key=True)
    typeId: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)


class BlueprintProduct(Base):
    """Products produced by a blueprint activity. Includes invention probability."""

    __bind_key__ = "static"
    __tablename__ = "BlueprintProduct"

    blueprintTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityName: Mapped[str] = mapped_column(Text, primary_key=True)
    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)
    probability: Mapped[Optional[float]] = mapped_column(Float)


class BlueprintSkill(Base):
    """Skills required for a blueprint activity."""

    __bind_key__ = "static"
    __tablename__ = "BlueprintSkill"

    parentTypeId: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityName: Mapped[str] = mapped_column(Text, primary_key=True)
    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[Optional[int]] = mapped_column(Integer)


# ── Material / dogma tables ──────────────────────────────────────────
class TypeMaterial(Base):
    """Base reprocessing materials for a type."""

    __bind_key__ = "static"
    __tablename__ = "TypeMaterial"

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    materialTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)


class TypeDogmaAttribute(Base):
    """Dogma attributes for types (single value column, stores ints and floats)."""

    __bind_key__ = "static"
    __tablename__ = "TypeDogmaAttribute"
    __table_args__ = (Index("ix_TypeDogmaAttribute_attributeID", "attributeID"),)

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    attributeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[Optional[float]] = mapped_column(Float)


# ── Map tables ───────────────────────────────────────────────────────
class MapSolarSystem(Base):
    """Solar systems."""

    __bind_key__ = "static"
    __tablename__ = "mapSolarSystem"

    solarSystemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    regionID: Mapped[Optional[int]] = mapped_column(Integer)
    constellationID: Mapped[Optional[int]] = mapped_column(Integer)
    factionID: Mapped[Optional[int]] = mapped_column(Integer)
    security: Mapped[Optional[int]] = mapped_column(Integer)
    securityStatus: Mapped[Optional[float]] = mapped_column(Float)
    securityClass: Mapped[Optional[str]] = mapped_column(Text)
    sunTypeID: Mapped[Optional[int]] = mapped_column(Integer)


class SolarSystemName(Base):
    """Localized names for solar systems."""

    __bind_key__ = "static"
    __tablename__ = "SolarSystemName"

    parentTypeId: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeId2: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeCategory: Mapped[str] = mapped_column(Text, primary_key=True)
    en: Mapped[Optional[str]] = mapped_column(Text)
