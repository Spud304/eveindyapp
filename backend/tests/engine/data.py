"""Small synthetic SDE + account fixtures for engine tests.

Item and blueprint IDs are made up; group IDs used by build rules and rig
target filters, skill IDs and structure/rig values are the real SDE ones."""

from engine.types import (
    Activity,
    BlueprintData,
    Character,
    Decryptor,
    GameData,
    ItemType,
    Material,
    ModifierKind,
    OwnedBlueprint,
    PlanInput,
    PlanLine,
    Recipe,
    Rig,
    RigBonus,
    SecurityClass,
    SkillRequirement,
    SolarSystem,
    Station,
    Structure,
    StructureModifier,
    TargetFilter,
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
            copying=Recipe(time_seconds=800),
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


def _complex(type_id, name, te, cost):
    """Engineering complex modifiers as in SDE industryModifierSources (2600/2601/2602)."""
    mods = [StructureModifier(Activity.MANUFACTURING, ModifierKind.MATERIAL, 0.99)]
    for act in (Activity.MANUFACTURING, Activity.COPYING, Activity.INVENTION):
        mods.append(StructureModifier(act, ModifierKind.TIME, te))
        mods.append(StructureModifier(act, ModifierKind.COST, cost))
    return Structure(type_id, name, tuple(mods))


RAITARU = _complex(35825, "Raitaru", 0.85, 0.97)
AZBEL = _complex(35826, "Azbel", 0.80, 0.96)
ATHANOR = Structure(35835, "Athanor")
TATARA = Structure(
    35836, "Tatara", (StructureModifier(Activity.REACTION, ModifierKind.TIME, 0.75),)
)

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

# Filters copied from SDE industryTargetFilters 7, 14, 18.
MEDIUM_T1_SHIPS = TargetFilter(
    7, "Medium T1 Ships", group_ids=frozenset({26, 28, 419, 463, 1201, 4902, 5087})
)
COMPONENTS = TargetFilter(14, "Components", group_ids=frozenset({332, 334, 716, 964}))
COMPOSITE_REACTIONS = TargetFilter(18, "Composite Reactions", group_ids=frozenset({428, 429, 4932}))

MEDIUM_SHIP_ME_RIG = Rig(
    37146,
    "M-Set Basic Medium Ship ME I",
    (RigBonus(Activity.MANUFACTURING, ModifierKind.MATERIAL, 2.0, MEDIUM_T1_SHIPS),),
    SEC_ENGINEERING,
)
ADV_COMPONENT_TE_RIG = Rig(
    37165,
    "M-Set Advanced Component TE I",
    (RigBonus(Activity.MANUFACTURING, ModifierKind.TIME, 20.0, COMPONENTS),),
    SEC_ENGINEERING,
)
COMPOSITE_ME_RIG = Rig(
    46486,
    "M-Set Composite Reactor ME I",
    (RigBonus(Activity.REACTION, ModifierKind.MATERIAL, 2.0, COMPOSITE_REACTIONS),),
    SEC_REACTOR,
)
COPY_TIME_RIG = Rig(
    9001,  # made-up id; the bonus shape matches a copy-time rig
    "M-Set Blueprint Copy Accelerator I",
    (RigBonus(Activity.COPYING, ModifierKind.TIME, 20.0),),
    SEC_ENGINEERING,
)

MFG = frozenset({Activity.MANUFACTURING})


def raitaru(rigs=()):
    return Station(1, "Raitaru HS", HS_SYSTEM, RAITARU, 1.0, MFG, tuple(rigs))


def azbel(rigs=()):
    return Station(2, "Azbel LS", LS_SYSTEM, AZBEL, 1.0, MFG, tuple(rigs))


def athanor(rigs=()):
    return Station(3, "Athanor NS", NS_SYSTEM, ATHANOR, 0.0, frozenset({Activity.REACTION}), rigs)


def tatara(rigs=()):
    return Station(4, "Tatara NS", NS_SYSTEM, TATARA, 0.0, frozenset({Activity.REACTION}), rigs)


def lab(rigs=()):
    """A Raitaru running copying and invention only."""
    acts = frozenset({Activity.COPYING, Activity.INVENTION})
    return Station(5, "Lab HS", HS_SYSTEM, RAITARU, 0.0, acts, tuple(rigs))


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
    kw.setdefault("lines", lines(*line_pairs))
    return PlanInput(**kw)
