"""Game constants the engine needs that are not passed in as data.

Source tags: [SDE] checked against the local SDE (2025-04-29 build);
[official] CCP docs; [community] wiki / third-party; see docs/redesign.md.
"""

from .types import Activity, BuildCategory

# --- Job fees ---------------------------------------------------------------

# SCC surcharge on manufacturing and reaction jobs, since Feb 2024. [community]
SCC_SURCHARGE = 0.04
# Alpha clone tax on job installation. [community]
ALPHA_CLONE_TAX = 0.0025

# --- Invention --------------------------------------------------------------

# Invented T2 BPC base ME / TE before decryptor modifiers. [community]
T2_BASE_ME = 2
T2_BASE_TE = 4

ENCRYPTION_SKILL_IDS = frozenset(
    {
        3408,  # Sleeper Encryption Methods
        21790,  # Caldari Encryption Methods
        21791,  # Minmatar Encryption Methods
        23087,  # Amarr Encryption Methods
        23121,  # Gallente Encryption Methods
        52308,  # Triglavian Encryption Methods
        55025,  # Upwell Encryption Methods
    }
)

# --- Skills [SDE: dogma attribute named in comment] -------------------------

SKILL_INDUSTRY = 3380  # attr 440 Manufacturing Time Bonus -4%/level
SKILL_ADV_INDUSTRY = 3388  # attr 1961 Industry Job Length Bonus -3%/level
SKILL_SCIENCE = 3402  # attr 452 Copy Speed Bonus -5%/level
SKILL_REACTIONS = 45746  # attr 2660 Reaction Time Bonus -4%/level
SKILL_MASS_PRODUCTION = 3387  # attr 450 +1 manufacturing slot/level
SKILL_ADV_MASS_PRODUCTION = 24625  # attr 450
SKILL_LAB_OPERATION = 3406  # attr 471 +1 science slot/level
SKILL_ADV_LAB_OPERATION = 24624  # attr 471
SKILL_MASS_REACTIONS = 45748  # attr 2661 +1 reaction slot/level
SKILL_ADV_MASS_REACTIONS = 45749  # attr 2661

INDUSTRY_TIME_BONUS = 0.04
ADV_INDUSTRY_TIME_BONUS = 0.03
SCIENCE_COPY_BONUS = 0.05
REACTIONS_TIME_BONUS = 0.04

# --- Build-rule categories by group [SDE group names] -----------------------

GROUP_BUILD_CATEGORY = {
    334: BuildCategory.ADVANCED_COMPONENTS,  # Construction Components
    873: BuildCategory.CAPITAL_COMPONENTS,  # Capital Construction Components
    913: BuildCategory.ADVANCED_CAPITAL_COMPONENTS,  # Advanced Capital Construction Components
    1136: BuildCategory.FUEL_BLOCKS,  # Fuel Block
}

# Reaction formula groups [SDE]
GROUP_COMPOSITE_FORMULAS = 1888  # holds both intermediate and composite reactions
GROUP_POLYMER_FORMULAS = 1889
GROUP_BIOCHEMICAL_FORMULAS = 1890
GROUP_MOLECULAR_FORGED_FORMULAS = 4097

# --- Rig classification -----------------------------------------------------

# Product -> rig category. Ship groups by hull class.
BASIC_SMALL_SHIP_GROUPS = frozenset({25, 420, 31, 237, 1283, 1527})
BASIC_MEDIUM_SHIP_GROUPS = frozenset({26, 419, 1201, 28, 463, 941, 1972})
BASIC_LARGE_SHIP_GROUPS = frozenset({27, 381})
ADV_SMALL_SHIP_GROUPS = frozenset({324, 830, 831, 893, 834, 1534, 541, 1305})
ADV_MEDIUM_SHIP_GROUPS = frozenset({358, 832, 906, 833, 894, 963, 540, 380, 1202, 543})
ADV_LARGE_SHIP_GROUPS = frozenset({900, 898})
CAPITAL_SHIP_GROUPS = frozenset({30, 485, 513, 547, 659, 883, 902, 1538, 4594})

_ALL_SHIPS = {
    "basic_small_ship",
    "basic_medium_ship",
    "basic_large_ship",
    "adv_small_ship",
    "adv_medium_ship",
    "adv_large_ship",
    "capital_ship",
}

# Engineering rig group -> product rig categories it covers. [SDE group names]
# M-set rigs are split into ME and TE groups; L and XL rigs carry both.
MANUFACTURING_RIG_CATEGORIES: dict[int, frozenset[str]] = {
    # M-set ME / TE
    1816: frozenset({"equipment"}),
    1819: frozenset({"equipment"}),
    1820: frozenset({"ammunition"}),
    1821: frozenset({"ammunition"}),
    1822: frozenset({"drone_fighter"}),
    1823: frozenset({"drone_fighter"}),
    1824: frozenset({"basic_small_ship"}),
    1825: frozenset({"basic_small_ship"}),
    1826: frozenset({"basic_medium_ship"}),
    1827: frozenset({"basic_medium_ship"}),
    1828: frozenset({"basic_large_ship"}),
    1829: frozenset({"basic_large_ship"}),
    1830: frozenset({"adv_small_ship"}),
    1831: frozenset({"adv_small_ship"}),
    1832: frozenset({"adv_medium_ship"}),
    1833: frozenset({"adv_medium_ship"}),
    1834: frozenset({"adv_large_ship"}),
    1835: frozenset({"adv_large_ship"}),
    1836: frozenset({"adv_component"}),
    1837: frozenset({"adv_component"}),
    1838: frozenset({"basic_capital_component"}),  # TE (group order is swapped)
    1839: frozenset({"basic_capital_component"}),  # ME
    1840: frozenset({"structure"}),
    1841: frozenset({"structure"}),
    # L-set
    1850: frozenset({"equipment"}),
    1851: frozenset({"ammunition"}),
    1852: frozenset({"drone_fighter"}),
    1853: frozenset({"basic_small_ship"}),
    1854: frozenset({"basic_medium_ship"}),
    1855: frozenset({"basic_large_ship"}),
    1856: frozenset({"adv_small_ship"}),
    1857: frozenset({"adv_medium_ship"}),
    1858: frozenset({"adv_large_ship"}),
    1859: frozenset({"capital_ship"}),
    1860: frozenset({"adv_component"}),
    1861: frozenset({"basic_capital_component"}),
    1862: frozenset({"structure"}),
    # XL-set
    1867: frozenset({"equipment", "ammunition"}),
    1868: frozenset(_ALL_SHIPS),
    1869: frozenset({"structure", "adv_component", "basic_capital_component"}),
}

# Reactor rig group -> reaction rig categories. [SDE group names; 1939's
# description covers "composite, hybrid, and biochemical reactions"]
REACTION_RIG_CATEGORIES: dict[int, frozenset[str]] = {
    1933: frozenset({"composite_reaction"}),
    1934: frozenset({"composite_reaction"}),
    1935: frozenset({"hybrid_reaction"}),
    1936: frozenset({"hybrid_reaction"}),
    1937: frozenset({"biochemical_reaction"}),
    1938: frozenset({"biochemical_reaction"}),
    1939: frozenset({"composite_reaction", "hybrid_reaction", "biochemical_reaction"}),
}

REACTION_FORMULA_RIG_CATEGORY = {
    GROUP_COMPOSITE_FORMULAS: "composite_reaction",
    GROUP_POLYMER_FORMULAS: "hybrid_reaction",
    GROUP_BIOCHEMICAL_FORMULAS: "biochemical_reaction",
    GROUP_MOLECULAR_FORGED_FORMULAS: "biochemical_reaction",
}

RIG_CATEGORIES_BY_ACTIVITY = {
    Activity.MANUFACTURING: MANUFACTURING_RIG_CATEGORIES,
    Activity.REACTION: REACTION_RIG_CATEGORIES,
}
