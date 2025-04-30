from typing import Optional

from sqlalchemy import BigInteger, Boolean, CHAR, Column, DECIMAL, Float, Index, Integer, String, Table, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import decimal

class Base(DeclarativeBase):
    pass


class AgtAgentTypes(Base):
    __bind_key__ = "static"
    __tablename__ = 'agtAgentTypes'

    agentTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    agentType: Mapped[Optional[str]] = mapped_column(String(50))


class AgtAgents(Base):
    __bind_key__ = "static"
    __tablename__ = 'agtAgents'
    __table_args__ = (
        Index('ix_agtAgents_corporationID', 'corporationID'),
        Index('ix_agtAgents_locationID', 'locationID')
    )

    agentID: Mapped[int] = mapped_column(Integer, primary_key=True)
    divisionID: Mapped[Optional[int]] = mapped_column(Integer)
    corporationID: Mapped[Optional[int]] = mapped_column(Integer)
    locationID: Mapped[Optional[int]] = mapped_column(Integer)
    level: Mapped[Optional[int]] = mapped_column(Integer)
    quality: Mapped[Optional[int]] = mapped_column(Integer)
    agentTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    isLocator: Mapped[Optional[bool]] = mapped_column(Boolean)


class AgtAgentsInSpace(Base):
    __bind_key__ = "static"
    __tablename__ = 'agtAgentsInSpace'
    __table_args__ = (
        Index('ix_agtAgentsInSpace_solarSystemID', 'solarSystemID'),
    )

    agentID: Mapped[int] = mapped_column(Integer, primary_key=True)
    dungeonID: Mapped[Optional[int]] = mapped_column(Integer)
    solarSystemID: Mapped[Optional[int]] = mapped_column(Integer)
    spawnPointID: Mapped[Optional[int]] = mapped_column(Integer)
    typeID: Mapped[Optional[int]] = mapped_column(Integer)


class AgtResearchAgents(Base):
    __bind_key__ = "static"
    __tablename__ = 'agtResearchAgents'
    __table_args__ = (
        Index('ix_agtResearchAgents_typeID', 'typeID'),
    )

    agentID: Mapped[int] = mapped_column(Integer, primary_key=True)
    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)


class CertCerts(Base):
    __bind_key__ = "static"
    __tablename__ = 'certCerts'

    certID: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    groupID: Mapped[Optional[int]] = mapped_column(Integer)
    name: Mapped[Optional[str]] = mapped_column(String(255))


t_certMasteries = Table(
    'certMasteries', Base.metadata,
    Column('typeID', Integer),
    Column('masteryLevel', Integer),
    Column('certID', Integer)
)


t_certSkills = Table(
    'certSkills', Base.metadata,
    Column('certID', Integer),
    Column('skillID', Integer),
    Column('certLevelInt', Integer),
    Column('skillLevel', Integer),
    Column('certLevelText', String(8)),
    Index('ix_certSkills_skillID', 'skillID')
)


class ChrAncestries(Base):
    __bind_key__ = "static"
    __tablename__ = 'chrAncestries'

    ancestryID: Mapped[int] = mapped_column(Integer, primary_key=True)
    ancestryName: Mapped[Optional[str]] = mapped_column(String(100))
    bloodlineID: Mapped[Optional[int]] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    perception: Mapped[Optional[int]] = mapped_column(Integer)
    willpower: Mapped[Optional[int]] = mapped_column(Integer)
    charisma: Mapped[Optional[int]] = mapped_column(Integer)
    memory: Mapped[Optional[int]] = mapped_column(Integer)
    intelligence: Mapped[Optional[int]] = mapped_column(Integer)
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    shortDescription: Mapped[Optional[str]] = mapped_column(String(500))


class ChrAttributes(Base):
    __bind_key__ = "static"
    __tablename__ = 'chrAttributes'

    attributeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    attributeName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    shortDescription: Mapped[Optional[str]] = mapped_column(String(500))
    notes: Mapped[Optional[str]] = mapped_column(String(500))


class ChrBloodlines(Base):
    __bind_key__ = "static"
    __tablename__ = 'chrBloodlines'

    bloodlineID: Mapped[int] = mapped_column(Integer, primary_key=True)
    bloodlineName: Mapped[Optional[str]] = mapped_column(String(100))
    raceID: Mapped[Optional[int]] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    maleDescription: Mapped[Optional[str]] = mapped_column(String(1000))
    femaleDescription: Mapped[Optional[str]] = mapped_column(String(1000))
    shipTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    corporationID: Mapped[Optional[int]] = mapped_column(Integer)
    perception: Mapped[Optional[int]] = mapped_column(Integer)
    willpower: Mapped[Optional[int]] = mapped_column(Integer)
    charisma: Mapped[Optional[int]] = mapped_column(Integer)
    memory: Mapped[Optional[int]] = mapped_column(Integer)
    intelligence: Mapped[Optional[int]] = mapped_column(Integer)
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    shortDescription: Mapped[Optional[str]] = mapped_column(String(500))
    shortMaleDescription: Mapped[Optional[str]] = mapped_column(String(500))
    shortFemaleDescription: Mapped[Optional[str]] = mapped_column(String(500))


class ChrFactions(Base):
    __bind_key__ = "static"
    __tablename__ = 'chrFactions'

    factionID: Mapped[int] = mapped_column(Integer, primary_key=True)
    factionName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(2000))
    raceIDs: Mapped[Optional[int]] = mapped_column(Integer)
    solarSystemID: Mapped[Optional[int]] = mapped_column(Integer)
    corporationID: Mapped[Optional[int]] = mapped_column(Integer)
    sizeFactor: Mapped[Optional[float]] = mapped_column(Float)
    stationCount: Mapped[Optional[int]] = mapped_column(Integer)
    stationSystemCount: Mapped[Optional[int]] = mapped_column(Integer)
    militiaCorporationID: Mapped[Optional[int]] = mapped_column(Integer)
    iconID: Mapped[Optional[int]] = mapped_column(Integer)


class ChrRaces(Base):
    __bind_key__ = "static"
    __tablename__ = 'chrRaces'

    raceID: Mapped[int] = mapped_column(Integer, primary_key=True)
    raceName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    shortDescription: Mapped[Optional[str]] = mapped_column(String(500))


class CrpActivities(Base):
    __bind_key__ = "static"
    __tablename__ = 'crpActivities'

    activityID: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))


class CrpNPCCorporationDivisions(Base):
    __bind_key__ = "static"
    __tablename__ = 'crpNPCCorporationDivisions'

    corporationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    divisionID: Mapped[int] = mapped_column(Integer, primary_key=True)
    size: Mapped[Optional[int]] = mapped_column(Integer)


class CrpNPCCorporationResearchFields(Base):
    __bind_key__ = "static"
    __tablename__ = 'crpNPCCorporationResearchFields'

    skillID: Mapped[int] = mapped_column(Integer, primary_key=True)
    corporationID: Mapped[int] = mapped_column(Integer, primary_key=True)


class CrpNPCCorporationTrades(Base):
    __bind_key__ = "static"
    __tablename__ = 'crpNPCCorporationTrades'

    corporationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)


class CrpNPCCorporations(Base):
    __bind_key__ = "static"
    __tablename__ = 'crpNPCCorporations'

    corporationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    size: Mapped[Optional[str]] = mapped_column(CHAR(1))
    extent: Mapped[Optional[str]] = mapped_column(CHAR(1))
    solarSystemID: Mapped[Optional[int]] = mapped_column(Integer)
    investorID1: Mapped[Optional[int]] = mapped_column(Integer)
    investorShares1: Mapped[Optional[int]] = mapped_column(Integer)
    investorID2: Mapped[Optional[int]] = mapped_column(Integer)
    investorShares2: Mapped[Optional[int]] = mapped_column(Integer)
    investorID3: Mapped[Optional[int]] = mapped_column(Integer)
    investorShares3: Mapped[Optional[int]] = mapped_column(Integer)
    investorID4: Mapped[Optional[int]] = mapped_column(Integer)
    investorShares4: Mapped[Optional[int]] = mapped_column(Integer)
    friendID: Mapped[Optional[int]] = mapped_column(Integer)
    enemyID: Mapped[Optional[int]] = mapped_column(Integer)
    publicShares: Mapped[Optional[int]] = mapped_column(Integer)
    initialPrice: Mapped[Optional[int]] = mapped_column(Integer)
    minSecurity: Mapped[Optional[float]] = mapped_column(Float)
    scattered: Mapped[Optional[bool]] = mapped_column(Boolean)
    fringe: Mapped[Optional[int]] = mapped_column(Integer)
    corridor: Mapped[Optional[int]] = mapped_column(Integer)
    hub: Mapped[Optional[int]] = mapped_column(Integer)
    border: Mapped[Optional[int]] = mapped_column(Integer)
    factionID: Mapped[Optional[int]] = mapped_column(Integer)
    sizeFactor: Mapped[Optional[float]] = mapped_column(Float)
    stationCount: Mapped[Optional[int]] = mapped_column(Integer)
    stationSystemCount: Mapped[Optional[int]] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(String(4000))
    iconID: Mapped[Optional[int]] = mapped_column(Integer)


class CrpNPCDivisions(Base):
    __bind_key__ = "static"
    __tablename__ = 'crpNPCDivisions'

    divisionID: Mapped[int] = mapped_column(Integer, primary_key=True)
    divisionName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    leaderType: Mapped[Optional[str]] = mapped_column(String(100))


class DgmAttributeCategories(Base):
    __bind_key__ = "static"
    __tablename__ = 'dgmAttributeCategories'

    categoryID: Mapped[int] = mapped_column(Integer, primary_key=True)
    categoryName: Mapped[Optional[str]] = mapped_column(String(50))
    categoryDescription: Mapped[Optional[str]] = mapped_column(String(200))


class DgmAttributeTypes(Base):
    __bind_key__ = "static"
    __tablename__ = 'dgmAttributeTypes'

    attributeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    attributeName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    defaultValue: Mapped[Optional[float]] = mapped_column(Float)
    published: Mapped[Optional[bool]] = mapped_column(Boolean)
    displayName: Mapped[Optional[str]] = mapped_column(String(150))
    unitID: Mapped[Optional[int]] = mapped_column(Integer)
    stackable: Mapped[Optional[bool]] = mapped_column(Boolean)
    highIsGood: Mapped[Optional[bool]] = mapped_column(Boolean)
    categoryID: Mapped[Optional[int]] = mapped_column(Integer)


class DgmEffects(Base):
    __bind_key__ = "static"
    __tablename__ = 'dgmEffects'

    effectID: Mapped[int] = mapped_column(Integer, primary_key=True)
    effectName: Mapped[Optional[str]] = mapped_column(String(400))
    effectCategory: Mapped[Optional[int]] = mapped_column(Integer)
    preExpression: Mapped[Optional[int]] = mapped_column(Integer)
    postExpression: Mapped[Optional[int]] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    guid: Mapped[Optional[str]] = mapped_column(String(60))
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    isOffensive: Mapped[Optional[bool]] = mapped_column(Boolean)
    isAssistance: Mapped[Optional[bool]] = mapped_column(Boolean)
    durationAttributeID: Mapped[Optional[int]] = mapped_column(Integer)
    trackingSpeedAttributeID: Mapped[Optional[int]] = mapped_column(Integer)
    dischargeAttributeID: Mapped[Optional[int]] = mapped_column(Integer)
    rangeAttributeID: Mapped[Optional[int]] = mapped_column(Integer)
    falloffAttributeID: Mapped[Optional[int]] = mapped_column(Integer)
    disallowAutoRepeat: Mapped[Optional[bool]] = mapped_column(Boolean)
    published: Mapped[Optional[bool]] = mapped_column(Boolean)
    displayName: Mapped[Optional[str]] = mapped_column(String(100))
    isWarpSafe: Mapped[Optional[bool]] = mapped_column(Boolean)
    rangeChance: Mapped[Optional[bool]] = mapped_column(Boolean)
    electronicChance: Mapped[Optional[bool]] = mapped_column(Boolean)
    propulsionChance: Mapped[Optional[bool]] = mapped_column(Boolean)
    distribution: Mapped[Optional[int]] = mapped_column(Integer)
    sfxName: Mapped[Optional[str]] = mapped_column(String(20))
    npcUsageChanceAttributeID: Mapped[Optional[int]] = mapped_column(Integer)
    npcActivationChanceAttributeID: Mapped[Optional[int]] = mapped_column(Integer)
    fittingUsageChanceAttributeID: Mapped[Optional[int]] = mapped_column(Integer)
    modifierInfo: Mapped[Optional[str]] = mapped_column(Text)


class DgmExpressions(Base):
    __bind_key__ = "static"
    __tablename__ = 'dgmExpressions'

    expressionID: Mapped[int] = mapped_column(Integer, primary_key=True)
    operandID: Mapped[Optional[int]] = mapped_column(Integer)
    arg1: Mapped[Optional[int]] = mapped_column(Integer)
    arg2: Mapped[Optional[int]] = mapped_column(Integer)
    expressionValue: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    expressionName: Mapped[Optional[str]] = mapped_column(String(500))
    expressionTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    expressionGroupID: Mapped[Optional[int]] = mapped_column(Integer)
    expressionAttributeID: Mapped[Optional[int]] = mapped_column(Integer)


class DgmTypeAttributes(Base):
    __bind_key__ = "static"
    __tablename__ = 'dgmTypeAttributes'
    __table_args__ = (
        Index('ix_dgmTypeAttributes_attributeID', 'attributeID'),
    )

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    attributeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    valueInt: Mapped[Optional[int]] = mapped_column(Integer)
    valueFloat: Mapped[Optional[float]] = mapped_column(Float)


class DgmTypeEffects(Base):
    __bind_key__ = "static"
    __tablename__ = 'dgmTypeEffects'

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    effectID: Mapped[int] = mapped_column(Integer, primary_key=True)
    isDefault: Mapped[Optional[bool]] = mapped_column(Boolean)


class EveGraphics(Base):
    __bind_key__ = "static"
    __tablename__ = 'eveGraphics'

    graphicID: Mapped[int] = mapped_column(Integer, primary_key=True)
    sofFactionName: Mapped[Optional[str]] = mapped_column(String(100))
    graphicFile: Mapped[Optional[str]] = mapped_column(String(256))
    sofHullName: Mapped[Optional[str]] = mapped_column(String(100))
    sofRaceName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)


class EveIcons(Base):
    __bind_key__ = "static"
    __tablename__ = 'eveIcons'

    iconID: Mapped[int] = mapped_column(Integer, primary_key=True)
    iconFile: Mapped[Optional[str]] = mapped_column(String(500))
    description: Mapped[Optional[str]] = mapped_column(Text)


class EveUnits(Base):
    __bind_key__ = "static"
    __tablename__ = 'eveUnits'

    unitID: Mapped[int] = mapped_column(Integer, primary_key=True)
    unitName: Mapped[Optional[str]] = mapped_column(String(100))
    displayName: Mapped[Optional[str]] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(String(1000))


class IndustryActivity(Base):
    __bind_key__ = "static"
    __tablename__ = 'industryActivity'
    __table_args__ = (
        Index('ix_industryActivity_activityID', 'activityID'),
    )

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityID: Mapped[int] = mapped_column(Integer, primary_key=True)
    time: Mapped[Optional[int]] = mapped_column(Integer)


t_industryActivityMaterials = Table(
    'industryActivityMaterials', Base.metadata,
    Column('typeID', Integer),
    Column('activityID', Integer),
    Column('materialTypeID', Integer),
    Column('quantity', Integer),
    Index('industryActivityMaterials_idx1', 'typeID', 'activityID'),
    Index('ix_industryActivityMaterials_typeID', 'typeID')
)


t_industryActivityProbabilities = Table(
    'industryActivityProbabilities', Base.metadata,
    Column('typeID', Integer),
    Column('activityID', Integer),
    Column('productTypeID', Integer),
    Column('probability', DECIMAL(3, 2)),
    Index('ix_industryActivityProbabilities_productTypeID', 'productTypeID'),
    Index('ix_industryActivityProbabilities_typeID', 'typeID')
)


t_industryActivityProducts = Table(
    'industryActivityProducts', Base.metadata,
    Column('typeID', Integer),
    Column('activityID', Integer),
    Column('productTypeID', Integer),
    Column('quantity', Integer),
    Index('ix_industryActivityProducts_productTypeID', 'productTypeID'),
    Index('ix_industryActivityProducts_typeID', 'typeID')
)


t_industryActivityRaces = Table(
    'industryActivityRaces', Base.metadata,
    Column('typeID', Integer),
    Column('activityID', Integer),
    Column('productTypeID', Integer),
    Column('raceID', Integer),
    Index('ix_industryActivityRaces_productTypeID', 'productTypeID'),
    Index('ix_industryActivityRaces_typeID', 'typeID')
)


t_industryActivitySkills = Table(
    'industryActivitySkills', Base.metadata,
    Column('typeID', Integer),
    Column('activityID', Integer),
    Column('skillID', Integer),
    Column('level', Integer),
    Index('industryActivitySkills_idx1', 'typeID', 'activityID'),
    Index('ix_industryActivitySkills_skillID', 'skillID'),
    Index('ix_industryActivitySkills_typeID', 'typeID')
)


class IndustryBlueprints(Base):
    __bind_key__ = "static"
    __tablename__ = 'industryBlueprints'

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    maxProductionLimit: Mapped[Optional[int]] = mapped_column(Integer)


class InvCategories(Base):
    __bind_key__ = "static"
    __tablename__ = 'invCategories'

    categoryID: Mapped[int] = mapped_column(Integer, primary_key=True)
    categoryName: Mapped[Optional[str]] = mapped_column(String(100))
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    published: Mapped[Optional[bool]] = mapped_column(Boolean)


class InvContrabandTypes(Base):
    __bind_key__ = "static"
    __tablename__ = 'invContrabandTypes'
    __table_args__ = (
        Index('ix_invContrabandTypes_typeID', 'typeID'),
    )

    factionID: Mapped[int] = mapped_column(Integer, primary_key=True)
    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    standingLoss: Mapped[Optional[float]] = mapped_column(Float)
    confiscateMinSec: Mapped[Optional[float]] = mapped_column(Float)
    fineByValue: Mapped[Optional[float]] = mapped_column(Float)
    attackMinSec: Mapped[Optional[float]] = mapped_column(Float)


class InvControlTowerResourcePurposes(Base):
    __bind_key__ = "static"
    __tablename__ = 'invControlTowerResourcePurposes'

    purpose: Mapped[int] = mapped_column(Integer, primary_key=True)
    purposeText: Mapped[Optional[str]] = mapped_column(String(100))


class InvControlTowerResources(Base):
    __bind_key__ = "static"
    __tablename__ = 'invControlTowerResources'

    controlTowerTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    resourceTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    purpose: Mapped[Optional[int]] = mapped_column(Integer)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)
    minSecurityLevel: Mapped[Optional[float]] = mapped_column(Float)
    factionID: Mapped[Optional[int]] = mapped_column(Integer)


class InvFlags(Base):
    __bind_key__ = "static"
    __tablename__ = 'invFlags'

    flagID: Mapped[int] = mapped_column(Integer, primary_key=True)
    flagName: Mapped[Optional[str]] = mapped_column(String(200))
    flagText: Mapped[Optional[str]] = mapped_column(String(100))
    orderID: Mapped[Optional[int]] = mapped_column(Integer)


class InvGroups(Base):
    __bind_key__ = "static"
    __tablename__ = 'invGroups'
    __table_args__ = (
        Index('ix_invGroups_categoryID', 'categoryID'),
    )

    groupID: Mapped[int] = mapped_column(Integer, primary_key=True)
    categoryID: Mapped[Optional[int]] = mapped_column(Integer)
    groupName: Mapped[Optional[str]] = mapped_column(String(100))
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    useBasePrice: Mapped[Optional[bool]] = mapped_column(Boolean)
    anchored: Mapped[Optional[bool]] = mapped_column(Boolean)
    anchorable: Mapped[Optional[bool]] = mapped_column(Boolean)
    fittableNonSingleton: Mapped[Optional[bool]] = mapped_column(Boolean)
    published: Mapped[Optional[bool]] = mapped_column(Boolean)


class InvItems(Base):
    __bind_key__ = "static"
    __tablename__ = 'invItems'
    __table_args__ = (
        Index('items_IX_OwnerLocation', 'ownerID', 'locationID'),
        Index('ix_invItems_locationID', 'locationID')
    )

    itemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    typeID: Mapped[int] = mapped_column(Integer)
    ownerID: Mapped[int] = mapped_column(Integer)
    locationID: Mapped[int] = mapped_column(Integer)
    flagID: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)


class InvMarketGroups(Base):
    __bind_key__ = "static"
    __tablename__ = 'invMarketGroups'

    marketGroupID: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentGroupID: Mapped[Optional[int]] = mapped_column(Integer)
    marketGroupName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(3000))
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    hasTypes: Mapped[Optional[bool]] = mapped_column(Boolean)


class InvMetaGroups(Base):
    __bind_key__ = "static"
    __tablename__ = 'invMetaGroups'

    metaGroupID: Mapped[int] = mapped_column(Integer, primary_key=True)
    metaGroupName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    iconID: Mapped[Optional[int]] = mapped_column(Integer)


class InvMetaTypes(Base):
    __bind_key__ = "static"
    __tablename__ = 'invMetaTypes'

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    parentTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    metaGroupID: Mapped[Optional[int]] = mapped_column(Integer)


class InvNames(Base):
    __bind_key__ = "static"
    __tablename__ = 'invNames'

    itemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    itemName: Mapped[str] = mapped_column(String(200))


class InvPositions(Base):
    __bind_key__ = "static"
    __tablename__ = 'invPositions'

    itemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)
    yaw: Mapped[Optional[float]] = mapped_column(Float)
    pitch: Mapped[Optional[float]] = mapped_column(Float)
    roll: Mapped[Optional[float]] = mapped_column(Float)


class InvTraits(Base):
    __bind_key__ = "static"
    __tablename__ = 'invTraits'

    traitID: Mapped[int] = mapped_column(Integer, primary_key=True)
    typeID: Mapped[Optional[int]] = mapped_column(Integer)
    skillID: Mapped[Optional[int]] = mapped_column(Integer)
    bonus: Mapped[Optional[float]] = mapped_column(Float)
    bonusText: Mapped[Optional[str]] = mapped_column(Text)
    unitID: Mapped[Optional[int]] = mapped_column(Integer)


class InvTypeMaterials(Base):
    __bind_key__ = "static"
    __tablename__ = 'invTypeMaterials'

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    materialTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)


class InvTypeReactions(Base):
    __bind_key__ = "static"
    __tablename__ = 'invTypeReactions'

    reactionTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    input: Mapped[bool] = mapped_column(Boolean, primary_key=True)
    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)


class InvTypes(Base):
    __bind_key__ = "static"
    __tablename__ = 'invTypes'
    __table_args__ = (
        Index('ix_invTypes_groupID', 'groupID'),
    )

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    groupID: Mapped[Optional[int]] = mapped_column(Integer)
    typeName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    mass: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    capacity: Mapped[Optional[float]] = mapped_column(Float)
    portionSize: Mapped[Optional[int]] = mapped_column(Integer)
    raceID: Mapped[Optional[int]] = mapped_column(Integer)
    basePrice: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(19, 4))
    published: Mapped[Optional[bool]] = mapped_column(Boolean)
    marketGroupID: Mapped[Optional[int]] = mapped_column(Integer)
    iconID: Mapped[Optional[int]] = mapped_column(Integer)
    soundID: Mapped[Optional[int]] = mapped_column(Integer)
    graphicID: Mapped[Optional[int]] = mapped_column(Integer)


class InvUniqueNames(Base):
    __bind_key__ = "static"
    __tablename__ = 'invUniqueNames'
    __table_args__ = (
        Index('invUniqueNames_IX_GroupName', 'groupID', 'itemName'),
        Index('ix_invUniqueNames_itemName', 'itemName', unique=True)
    )

    itemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    itemName: Mapped[str] = mapped_column(String(200))
    groupID: Mapped[Optional[int]] = mapped_column(Integer)


class InvVolumes(Base):
    __bind_key__ = "static"
    __tablename__ = 'invVolumes'

    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    volume: Mapped[Optional[int]] = mapped_column(Integer)


class MapCelestialGraphics(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapCelestialGraphics'

    celestialID: Mapped[int] = mapped_column(Integer, primary_key=True)
    heightMap1: Mapped[Optional[int]] = mapped_column(Integer)
    heightMap2: Mapped[Optional[int]] = mapped_column(Integer)
    shaderPreset: Mapped[Optional[int]] = mapped_column(Integer)
    population: Mapped[Optional[bool]] = mapped_column(Boolean)


class MapCelestialStatistics(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapCelestialStatistics'

    celestialID: Mapped[int] = mapped_column(Integer, primary_key=True)
    temperature: Mapped[Optional[float]] = mapped_column(Float)
    spectralClass: Mapped[Optional[str]] = mapped_column(String(10))
    luminosity: Mapped[Optional[float]] = mapped_column(Float)
    age: Mapped[Optional[float]] = mapped_column(Float)
    life: Mapped[Optional[float]] = mapped_column(Float)
    orbitRadius: Mapped[Optional[float]] = mapped_column(Float)
    eccentricity: Mapped[Optional[float]] = mapped_column(Float)
    massDust: Mapped[Optional[float]] = mapped_column(Float)
    massGas: Mapped[Optional[float]] = mapped_column(Float)
    fragmented: Mapped[Optional[bool]] = mapped_column(Boolean)
    density: Mapped[Optional[float]] = mapped_column(Float)
    surfaceGravity: Mapped[Optional[float]] = mapped_column(Float)
    escapeVelocity: Mapped[Optional[float]] = mapped_column(Float)
    orbitPeriod: Mapped[Optional[float]] = mapped_column(Float)
    rotationRate: Mapped[Optional[float]] = mapped_column(Float)
    locked: Mapped[Optional[bool]] = mapped_column(Boolean)
    pressure: Mapped[Optional[float]] = mapped_column(Float)
    radius: Mapped[Optional[float]] = mapped_column(Float)
    mass: Mapped[Optional[int]] = mapped_column(Integer)


class MapConstellationJumps(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapConstellationJumps'

    fromConstellationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    toConstellationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    fromRegionID: Mapped[Optional[int]] = mapped_column(Integer)
    toRegionID: Mapped[Optional[int]] = mapped_column(Integer)


class MapConstellations(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapConstellations'

    constellationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    regionID: Mapped[Optional[int]] = mapped_column(Integer)
    constellationName: Mapped[Optional[str]] = mapped_column(String(100))
    x: Mapped[Optional[float]] = mapped_column(Float)
    y: Mapped[Optional[float]] = mapped_column(Float)
    z: Mapped[Optional[float]] = mapped_column(Float)
    xMin: Mapped[Optional[float]] = mapped_column(Float)
    xMax: Mapped[Optional[float]] = mapped_column(Float)
    yMin: Mapped[Optional[float]] = mapped_column(Float)
    yMax: Mapped[Optional[float]] = mapped_column(Float)
    zMin: Mapped[Optional[float]] = mapped_column(Float)
    zMax: Mapped[Optional[float]] = mapped_column(Float)
    factionID: Mapped[Optional[int]] = mapped_column(Integer)
    radius: Mapped[Optional[float]] = mapped_column(Float)


class MapDenormalize(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapDenormalize'
    __table_args__ = (
        Index('ix_mapDenormalize_constellationID', 'constellationID'),
        Index('ix_mapDenormalize_orbitID', 'orbitID'),
        Index('ix_mapDenormalize_regionID', 'regionID'),
        Index('ix_mapDenormalize_solarSystemID', 'solarSystemID'),
        Index('ix_mapDenormalize_typeID', 'typeID'),
        Index('mapDenormalize_IX_groupConstellation', 'groupID', 'constellationID'),
        Index('mapDenormalize_IX_groupRegion', 'groupID', 'regionID'),
        Index('mapDenormalize_IX_groupSystem', 'groupID', 'solarSystemID')
    )

    itemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    typeID: Mapped[Optional[int]] = mapped_column(Integer)
    groupID: Mapped[Optional[int]] = mapped_column(Integer)
    solarSystemID: Mapped[Optional[int]] = mapped_column(Integer)
    constellationID: Mapped[Optional[int]] = mapped_column(Integer)
    regionID: Mapped[Optional[int]] = mapped_column(Integer)
    orbitID: Mapped[Optional[int]] = mapped_column(Integer)
    x: Mapped[Optional[float]] = mapped_column(Float)
    y: Mapped[Optional[float]] = mapped_column(Float)
    z: Mapped[Optional[float]] = mapped_column(Float)
    radius: Mapped[Optional[float]] = mapped_column(Float)
    itemName: Mapped[Optional[str]] = mapped_column(String(100))
    security: Mapped[Optional[float]] = mapped_column(Float)
    celestialIndex: Mapped[Optional[int]] = mapped_column(Integer)
    orbitIndex: Mapped[Optional[int]] = mapped_column(Integer)


class MapJumps(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapJumps'

    stargateID: Mapped[int] = mapped_column(Integer, primary_key=True)
    destinationID: Mapped[Optional[int]] = mapped_column(Integer)


class MapLandmarks(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapLandmarks'

    landmarkID: Mapped[int] = mapped_column(Integer, primary_key=True)
    landmarkName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    locationID: Mapped[Optional[int]] = mapped_column(Integer)
    x: Mapped[Optional[float]] = mapped_column(Float)
    y: Mapped[Optional[float]] = mapped_column(Float)
    z: Mapped[Optional[float]] = mapped_column(Float)
    iconID: Mapped[Optional[int]] = mapped_column(Integer)


class MapLocationScenes(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapLocationScenes'

    locationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    graphicID: Mapped[Optional[int]] = mapped_column(Integer)


class MapLocationWormholeClasses(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapLocationWormholeClasses'

    locationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    wormholeClassID: Mapped[Optional[int]] = mapped_column(Integer)


class MapRegionJumps(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapRegionJumps'

    fromRegionID: Mapped[int] = mapped_column(Integer, primary_key=True)
    toRegionID: Mapped[int] = mapped_column(Integer, primary_key=True)


class MapRegions(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapRegions'

    regionID: Mapped[int] = mapped_column(Integer, primary_key=True)
    regionName: Mapped[Optional[str]] = mapped_column(String(100))
    x: Mapped[Optional[float]] = mapped_column(Float)
    y: Mapped[Optional[float]] = mapped_column(Float)
    z: Mapped[Optional[float]] = mapped_column(Float)
    xMin: Mapped[Optional[float]] = mapped_column(Float)
    xMax: Mapped[Optional[float]] = mapped_column(Float)
    yMin: Mapped[Optional[float]] = mapped_column(Float)
    yMax: Mapped[Optional[float]] = mapped_column(Float)
    zMin: Mapped[Optional[float]] = mapped_column(Float)
    zMax: Mapped[Optional[float]] = mapped_column(Float)
    factionID: Mapped[Optional[int]] = mapped_column(Integer)
    nebula: Mapped[Optional[int]] = mapped_column(Integer)
    radius: Mapped[Optional[float]] = mapped_column(Float)


class MapSolarSystemJumps(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapSolarSystemJumps'

    fromSolarSystemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    toSolarSystemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    fromRegionID: Mapped[Optional[int]] = mapped_column(Integer)
    fromConstellationID: Mapped[Optional[int]] = mapped_column(Integer)
    toConstellationID: Mapped[Optional[int]] = mapped_column(Integer)
    toRegionID: Mapped[Optional[int]] = mapped_column(Integer)


class MapSolarSystems(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapSolarSystems'
    __table_args__ = (
        Index('ix_mapSolarSystems_constellationID', 'constellationID'),
        Index('ix_mapSolarSystems_regionID', 'regionID'),
        Index('ix_mapSolarSystems_security', 'security')
    )

    solarSystemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    regionID: Mapped[Optional[int]] = mapped_column(Integer)
    constellationID: Mapped[Optional[int]] = mapped_column(Integer)
    solarSystemName: Mapped[Optional[str]] = mapped_column(String(100))
    x: Mapped[Optional[float]] = mapped_column(Float)
    y: Mapped[Optional[float]] = mapped_column(Float)
    z: Mapped[Optional[float]] = mapped_column(Float)
    xMin: Mapped[Optional[float]] = mapped_column(Float)
    xMax: Mapped[Optional[float]] = mapped_column(Float)
    yMin: Mapped[Optional[float]] = mapped_column(Float)
    yMax: Mapped[Optional[float]] = mapped_column(Float)
    zMin: Mapped[Optional[float]] = mapped_column(Float)
    zMax: Mapped[Optional[float]] = mapped_column(Float)
    luminosity: Mapped[Optional[float]] = mapped_column(Float)
    border: Mapped[Optional[bool]] = mapped_column(Boolean)
    fringe: Mapped[Optional[bool]] = mapped_column(Boolean)
    corridor: Mapped[Optional[bool]] = mapped_column(Boolean)
    hub: Mapped[Optional[bool]] = mapped_column(Boolean)
    international: Mapped[Optional[bool]] = mapped_column(Boolean)
    regional: Mapped[Optional[bool]] = mapped_column(Boolean)
    constellation: Mapped[Optional[bool]] = mapped_column(Boolean)
    security: Mapped[Optional[float]] = mapped_column(Float)
    factionID: Mapped[Optional[int]] = mapped_column(Integer)
    radius: Mapped[Optional[float]] = mapped_column(Float)
    sunTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    securityClass: Mapped[Optional[str]] = mapped_column(String(2))


class MapUniverse(Base):
    __bind_key__ = "static"
    __tablename__ = 'mapUniverse'

    universeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    universeName: Mapped[Optional[str]] = mapped_column(String(100))
    x: Mapped[Optional[float]] = mapped_column(Float)
    y: Mapped[Optional[float]] = mapped_column(Float)
    z: Mapped[Optional[float]] = mapped_column(Float)
    xMin: Mapped[Optional[float]] = mapped_column(Float)
    xMax: Mapped[Optional[float]] = mapped_column(Float)
    yMin: Mapped[Optional[float]] = mapped_column(Float)
    yMax: Mapped[Optional[float]] = mapped_column(Float)
    zMin: Mapped[Optional[float]] = mapped_column(Float)
    zMax: Mapped[Optional[float]] = mapped_column(Float)
    radius: Mapped[Optional[float]] = mapped_column(Float)


class PlanetSchematics(Base):
    __bind_key__ = "static"
    __tablename__ = 'planetSchematics'

    schematicID: Mapped[int] = mapped_column(Integer, primary_key=True)
    schematicName: Mapped[Optional[str]] = mapped_column(String(255))
    cycleTime: Mapped[Optional[int]] = mapped_column(Integer)


class PlanetSchematicsPinMap(Base):
    __bind_key__ = "static"
    __tablename__ = 'planetSchematicsPinMap'

    schematicID: Mapped[int] = mapped_column(Integer, primary_key=True)
    pinTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)


class PlanetSchematicsTypeMap(Base):
    __bind_key__ = "static"
    __tablename__ = 'planetSchematicsTypeMap'

    schematicID: Mapped[int] = mapped_column(Integer, primary_key=True)
    typeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)
    isInput: Mapped[Optional[bool]] = mapped_column(Boolean)


class RamActivities(Base):
    __bind_key__ = "static"
    __tablename__ = 'ramActivities'

    activityID: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityName: Mapped[Optional[str]] = mapped_column(String(100))
    iconNo: Mapped[Optional[str]] = mapped_column(String(5))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    published: Mapped[Optional[bool]] = mapped_column(Boolean)


class RamAssemblyLineStations(Base):
    __bind_key__ = "static"
    __tablename__ = 'ramAssemblyLineStations'
    __table_args__ = (
        Index('ix_ramAssemblyLineStations_ownerID', 'ownerID'),
        Index('ix_ramAssemblyLineStations_regionID', 'regionID'),
        Index('ix_ramAssemblyLineStations_solarSystemID', 'solarSystemID')
    )

    stationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    assemblyLineTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)
    stationTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    ownerID: Mapped[Optional[int]] = mapped_column(Integer)
    solarSystemID: Mapped[Optional[int]] = mapped_column(Integer)
    regionID: Mapped[Optional[int]] = mapped_column(Integer)


class RamAssemblyLineTypeDetailPerCategory(Base):
    __bind_key__ = "static"
    __tablename__ = 'ramAssemblyLineTypeDetailPerCategory'

    assemblyLineTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    categoryID: Mapped[int] = mapped_column(Integer, primary_key=True)
    timeMultiplier: Mapped[Optional[float]] = mapped_column(Float)
    materialMultiplier: Mapped[Optional[float]] = mapped_column(Float)
    costMultiplier: Mapped[Optional[float]] = mapped_column(Float)


class RamAssemblyLineTypeDetailPerGroup(Base):
    __bind_key__ = "static"
    __tablename__ = 'ramAssemblyLineTypeDetailPerGroup'

    assemblyLineTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    groupID: Mapped[int] = mapped_column(Integer, primary_key=True)
    timeMultiplier: Mapped[Optional[float]] = mapped_column(Float)
    materialMultiplier: Mapped[Optional[float]] = mapped_column(Float)
    costMultiplier: Mapped[Optional[float]] = mapped_column(Float)


class RamAssemblyLineTypes(Base):
    __bind_key__ = "static"
    __tablename__ = 'ramAssemblyLineTypes'

    assemblyLineTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    assemblyLineTypeName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    baseTimeMultiplier: Mapped[Optional[float]] = mapped_column(Float)
    baseMaterialMultiplier: Mapped[Optional[float]] = mapped_column(Float)
    baseCostMultiplier: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    activityID: Mapped[Optional[int]] = mapped_column(Integer)
    minCostPerHour: Mapped[Optional[float]] = mapped_column(Float)


class RamInstallationTypeContents(Base):
    __bind_key__ = "static"
    __tablename__ = 'ramInstallationTypeContents'

    installationTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    assemblyLineTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)


class SkinLicense(Base):
    __bind_key__ = "static"
    __tablename__ = 'skinLicense'

    licenseTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer)
    skinID: Mapped[Optional[int]] = mapped_column(Integer)


class SkinMaterials(Base):
    __bind_key__ = "static"
    __tablename__ = 'skinMaterials'

    skinMaterialID: Mapped[int] = mapped_column(Integer, primary_key=True)
    displayNameID: Mapped[Optional[int]] = mapped_column(Integer)
    materialSetID: Mapped[Optional[int]] = mapped_column(Integer)


t_skinShip = Table(
    'skinShip', Base.metadata,
    Column('skinID', Integer),
    Column('typeID', Integer),
    Index('ix_skinShip_skinID', 'skinID'),
    Index('ix_skinShip_typeID', 'typeID')
)


class Skins(Base):
    __bind_key__ = "static"
    __tablename__ = 'skins'

    skinID: Mapped[int] = mapped_column(Integer, primary_key=True)
    internalName: Mapped[Optional[str]] = mapped_column(String(70))
    skinMaterialID: Mapped[Optional[int]] = mapped_column(Integer)


class StaOperationServices(Base):
    __bind_key__ = "static"
    __tablename__ = 'staOperationServices'

    operationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    serviceID: Mapped[int] = mapped_column(Integer, primary_key=True)


class StaOperations(Base):
    __bind_key__ = "static"
    __tablename__ = 'staOperations'

    operationID: Mapped[int] = mapped_column(Integer, primary_key=True)
    activityID: Mapped[Optional[int]] = mapped_column(Integer)
    operationName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    fringe: Mapped[Optional[int]] = mapped_column(Integer)
    corridor: Mapped[Optional[int]] = mapped_column(Integer)
    hub: Mapped[Optional[int]] = mapped_column(Integer)
    border: Mapped[Optional[int]] = mapped_column(Integer)
    ratio: Mapped[Optional[int]] = mapped_column(Integer)
    caldariStationTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    minmatarStationTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    amarrStationTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    gallenteStationTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    joveStationTypeID: Mapped[Optional[int]] = mapped_column(Integer)


class StaServices(Base):
    __bind_key__ = "static"
    __tablename__ = 'staServices'

    serviceID: Mapped[int] = mapped_column(Integer, primary_key=True)
    serviceName: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(1000))


class StaStationTypes(Base):
    __bind_key__ = "static"
    __tablename__ = 'staStationTypes'

    stationTypeID: Mapped[int] = mapped_column(Integer, primary_key=True)
    dockEntryX: Mapped[Optional[float]] = mapped_column(Float)
    dockEntryY: Mapped[Optional[float]] = mapped_column(Float)
    dockEntryZ: Mapped[Optional[float]] = mapped_column(Float)
    dockOrientationX: Mapped[Optional[float]] = mapped_column(Float)
    dockOrientationY: Mapped[Optional[float]] = mapped_column(Float)
    dockOrientationZ: Mapped[Optional[float]] = mapped_column(Float)
    operationID: Mapped[Optional[int]] = mapped_column(Integer)
    officeSlots: Mapped[Optional[int]] = mapped_column(Integer)
    reprocessingEfficiency: Mapped[Optional[float]] = mapped_column(Float)
    conquerable: Mapped[Optional[bool]] = mapped_column(Boolean)


class StaStations(Base):
    __bind_key__ = "static"
    __tablename__ = 'staStations'
    __table_args__ = (
        Index('ix_staStations_constellationID', 'constellationID'),
        Index('ix_staStations_corporationID', 'corporationID'),
        Index('ix_staStations_operationID', 'operationID'),
        Index('ix_staStations_regionID', 'regionID'),
        Index('ix_staStations_solarSystemID', 'solarSystemID'),
        Index('ix_staStations_stationTypeID', 'stationTypeID')
    )

    stationID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security: Mapped[Optional[float]] = mapped_column(Float)
    dockingCostPerVolume: Mapped[Optional[float]] = mapped_column(Float)
    maxShipVolumeDockable: Mapped[Optional[float]] = mapped_column(Float)
    officeRentalCost: Mapped[Optional[int]] = mapped_column(Integer)
    operationID: Mapped[Optional[int]] = mapped_column(Integer)
    stationTypeID: Mapped[Optional[int]] = mapped_column(Integer)
    corporationID: Mapped[Optional[int]] = mapped_column(Integer)
    solarSystemID: Mapped[Optional[int]] = mapped_column(Integer)
    constellationID: Mapped[Optional[int]] = mapped_column(Integer)
    regionID: Mapped[Optional[int]] = mapped_column(Integer)
    stationName: Mapped[Optional[str]] = mapped_column(String(100))
    x: Mapped[Optional[float]] = mapped_column(Float)
    y: Mapped[Optional[float]] = mapped_column(Float)
    z: Mapped[Optional[float]] = mapped_column(Float)
    reprocessingEfficiency: Mapped[Optional[float]] = mapped_column(Float)
    reprocessingStationsTake: Mapped[Optional[float]] = mapped_column(Float)
    reprocessingHangarFlag: Mapped[Optional[int]] = mapped_column(Integer)


class TranslationTables(Base):
    __bind_key__ = "static"
    __tablename__ = 'translationTables'

    sourceTable: Mapped[str] = mapped_column(String(200), primary_key=True)
    translatedKey: Mapped[str] = mapped_column(String(200), primary_key=True)
    destinationTable: Mapped[Optional[str]] = mapped_column(String(200))
    tcGroupID: Mapped[Optional[int]] = mapped_column(Integer)
    tcID: Mapped[Optional[int]] = mapped_column(Integer)


class TrnTranslationColumns(Base):
    __bind_key__ = "static"
    __tablename__ = 'trnTranslationColumns'

    tcID: Mapped[int] = mapped_column(Integer, primary_key=True)
    tableName: Mapped[str] = mapped_column(String(256))
    columnName: Mapped[str] = mapped_column(String(128))
    tcGroupID: Mapped[Optional[int]] = mapped_column(Integer)
    masterID: Mapped[Optional[str]] = mapped_column(String(128))


class TrnTranslationLanguages(Base):
    __bind_key__ = "static"
    __tablename__ = 'trnTranslationLanguages'

    numericLanguageID: Mapped[int] = mapped_column(Integer, primary_key=True)
    languageID: Mapped[Optional[str]] = mapped_column(String(50))
    languageName: Mapped[Optional[str]] = mapped_column(String(200))


class TrnTranslations(Base):
    __bind_key__ = "static"
    __tablename__ = 'trnTranslations'

    tcID: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyID: Mapped[int] = mapped_column(Integer, primary_key=True)
    languageID: Mapped[str] = mapped_column(String(50), primary_key=True)
    text: Mapped[str] = mapped_column(Text)


class WarCombatZoneSystems(Base):
    __bind_key__ = "static"
    __tablename__ = 'warCombatZoneSystems'

    solarSystemID: Mapped[int] = mapped_column(Integer, primary_key=True)
    combatZoneID: Mapped[Optional[int]] = mapped_column(Integer)


class WarCombatZones(Base):
    __bind_key__ = "static"
    __tablename__ = 'warCombatZones'

    combatZoneID: Mapped[int] = mapped_column(Integer, primary_key=True)
    combatZoneName: Mapped[Optional[str]] = mapped_column(String(100))
    factionID: Mapped[Optional[int]] = mapped_column(Integer)
    centerSystemID: Mapped[Optional[int]] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(String(500))
