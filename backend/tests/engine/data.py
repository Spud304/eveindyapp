"""Small synthetic SDE + account fixtures for engine tests.

IDs are made up except where the engine keys on real ones (group IDs for rig
and build-rule classification, skill IDs)."""

from engine.types import (
    Activity,
    BlueprintData,
    Character,
    Decryptor,
    GameData,
    ItemType,
    Material,
    OwnedBlueprint,
    PlanInput,
    PlanLine,
    Recipe,
    Rig,
    SecurityClass,
    SkillRequirement,
    SolarSystem,
    Station,
    Structure,
)

TRIT, PYE, MEX = 34, 35, 36
COMP_A = 1001  # group 334 advanced component
HULL = 1002  # group 26 cruiser (basic medium ship)
HULL_B = 1003
FUEL = 1004  # group 1136
INTERMEDIATE = 1010
COMPOSITE = 1011
MOON_GOO = 1020
T2_MOD = 1030
T1_MOD = 1031
DATACORE = 1040
DECRYPTOR = 1050

BP_COMP_A, BP_HULL, BP_HULL_B, BP_FUEL = 2001, 2002, 2003, 2004
F_INTERMEDIATE, F_COMPOSITE = 2010, 2011
BP_T2_MOD, BP_T1_MOD = 2030, 2031

ENCRYPTION, SCIENCE_1, SCIENCE_2 = 21790, 11433, 11442

ALL_ACTIVITIES = frozenset(Activity)


def _t(type_id, name, group, cat):
    return ItemType(type_id, name, group, cat)


TYPES = {
    t.type_id: t
    for t in [
        _t(TRIT, "Tritanium", 18, 4),
        _t(PYE, "Pyerite", 18, 4),
        _t(MEX, "Mexallon", 18, 4),
        _t(COMP_A, "Comp A", 334, 17),
        _t(HULL, "Hull", 26, 6),
        _t(HULL_B, "Hull B", 26, 6),
        _t(FUEL, "Fuel Block", 1136, 4),
        _t(INTERMEDIATE, "Intermediate", 428, 4),
        _t(COMPOSITE, "Composite", 429, 4),
        _t(MOON_GOO, "Moon Goo", 427, 4),
        _t(T2_MOD, "T2 Module", 60, 7),
        _t(T1_MOD, "T1 Module", 60, 7),
        _t(DATACORE, "Datacore", 333, 17),
        _t(DECRYPTOR, "Accelerant Decryptor", 1304, 35),
        _t(BP_COMP_A, "Comp A Blueprint", 400, 9),
        _t(BP_HULL, "Hull Blueprint", 400, 9),
        _t(BP_HULL_B, "Hull B Blueprint", 400, 9),
        _t(BP_FUEL, "Fuel Block Blueprint", 400, 9),
        _t(F_INTERMEDIATE, "Intermediate Formula", 1888, 24),
        _t(F_COMPOSITE, "Composite Formula", 1888, 24),
        _t(BP_T2_MOD, "T2 Module Blueprint", 400, 9),
        _t(BP_T1_MOD, "T1 Module Blueprint", 400, 9),
    ]
}


def _mfg(product, qty, mats, time=100, skills=()):
    return Recipe(
        time_seconds=time,
        materials=tuple(Material(t, q) for t, q in mats),
        skills=tuple(SkillRequirement(s, lv) for s, lv in skills),
        product_type_id=product,
        product_quantity=qty,
    )


BLUEPRINTS = {
    b.type_id: b
    for b in [
        BlueprintData(BP_COMP_A, 300, manufacturing=_mfg(COMP_A, 1, [(TRIT, 3), (PYE, 10)])),
        BlueprintData(
            BP_HULL,
            10,
            manufacturing=_mfg(HULL, 1, [(COMP_A, 7), (TRIT, 100)], time=1000),
        ),
        BlueprintData(BP_HULL_B, 10, manufacturing=_mfg(HULL_B, 1, [(COMP_A, 5), (MEX, 50)])),
        BlueprintData(BP_FUEL, 100, manufacturing=_mfg(FUEL, 40, [(TRIT, 10)])),
        BlueprintData(F_INTERMEDIATE, 1, reaction=_mfg(INTERMEDIATE, 200, [(MOON_GOO, 100)])),
        BlueprintData(F_COMPOSITE, 1, reaction=_mfg(COMPOSITE, 200, [(INTERMEDIATE, 100)])),
        BlueprintData(BP_T2_MOD, 10, manufacturing=_mfg(T2_MOD, 1, [(TRIT, 10), (COMP_A, 2)])),
        BlueprintData(
            BP_T1_MOD,
            300,
            manufacturing=_mfg(T1_MOD, 1, [(TRIT, 5)]),
            copying=Recipe(time_seconds=600),
            invention=(
                Recipe(
                    time_seconds=3600,
                    materials=(Material(DATACORE, 2),),
                    skills=(
                        SkillRequirement(ENCRYPTION, 1),
                        SkillRequirement(SCIENCE_1, 1),
                        SkillRequirement(SCIENCE_2, 1),
                    ),
                    product_type_id=BP_T2_MOD,
                    product_quantity=10,
                    probability=0.34,
                ),
            ),
        ),
    ]
}

ACCELERANT = Decryptor(DECRYPTOR, "Accelerant Decryptor", 1.2, 2, 10, 1)


def game(decryptors=()):
    return GameData(types=TYPES, blueprints=BLUEPRINTS, decryptors=tuple(decryptors))


RAITARU = Structure(35825, "Raitaru", 0.99, 0.85, 0.97)
AZBEL = Structure(35826, "Azbel", 0.99, 0.80, 0.96)
ATHANOR = Structure(35835, "Athanor")

HS_SYSTEM, LS_SYSTEM, NS_SYSTEM = 30000001, 30000002, 30000003
SYSTEMS = {
    HS_SYSTEM: SolarSystem(HS_SYSTEM, "High", 0.9, {Activity.MANUFACTURING: 0.02}),
    LS_SYSTEM: SolarSystem(LS_SYSTEM, "Low", 0.3, {Activity.MANUFACTURING: 0.05}),
    NS_SYSTEM: SolarSystem(NS_SYSTEM, "Null", -0.4, {Activity.REACTION: 0.03}),
}

SEC_ENGINEERING = {
    SecurityClass.HIGH: 1.0,
    SecurityClass.LOW: 1.9,
    SecurityClass.NULL: 2.1,
}
SEC_REACTOR = {SecurityClass.LOW: 1.0, SecurityClass.NULL: 1.1}

MEDIUM_SHIP_ME_RIG = Rig(37150, 1826, me_bonus=2.0, security_multipliers=SEC_ENGINEERING)
ADV_COMPONENT_TE_RIG = Rig(37160, 1837, te_bonus=20.0, security_multipliers=SEC_ENGINEERING)
COMPOSITE_ME_RIG = Rig(46486, 1934, me_bonus=2.0, security_multipliers=SEC_REACTOR)

MFG = frozenset({Activity.MANUFACTURING})


def raitaru(rigs=()):
    return Station(1, "Raitaru HS", HS_SYSTEM, RAITARU, 1.0, MFG, tuple(rigs))


def azbel(rigs=()):
    return Station(2, "Azbel LS", LS_SYSTEM, AZBEL, 1.0, MFG, tuple(rigs))


def athanor(rigs=()):
    return Station(3, "Athanor NS", NS_SYSTEM, ATHANOR, 0.0, frozenset({Activity.REACTION}), rigs)


def bpo(type_id, me=0, te=0, item_id=None):
    return OwnedBlueprint(item_id or type_id * 10, type_id, False, -1, me, te, 99)


def bpc(type_id, runs, me=0, te=0, item_id=None):
    return OwnedBlueprint(item_id or type_id * 10 + runs, type_id, True, runs, me, te, 99)


def character(cid=1, name="Builder", skills=None, activities=ALL_ACTIVITIES, alpha=False):
    return Character(cid, name, skills or {}, activities, alpha)


def lines(*pairs):
    return tuple(PlanLine(f"l{i}", t, q) for i, (t, q) in enumerate(pairs))


def make_input(line_pairs, **kw):
    kw.setdefault("game", game())
    kw.setdefault("systems", SYSTEMS)
    return PlanInput(lines=lines(*line_pairs), **kw)
