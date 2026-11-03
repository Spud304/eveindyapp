"""Game constants the engine needs that are not passed in as data.

Source tags: [SDE] checked against the local SDE (2025-04-29 build);
[official] CCP docs; [community] wiki / third-party; see docs/redesign.md.
"""

from .types import BuildCategory

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
