"""Input and output types for the planning engine.

The engine is pure: callers build a `PlanInput` from the SDE, ESI caches and
account config, call `engine.plan()`, and get back a `PlanResult`. Every view
(shopping list, blueprints, schedule, progress, cost) reads from that one
result, so tabs cannot disagree.

Every derived decision in the result carries a `Reason` so the UI can show
why a value is what it is (ME source, station chosen, bought vs built and
which rule, blueprint source, decryptor, character assignment).

Units: percentages are on a 0-100 scale (`me=10` means 10%), multipliers are
factors (`0.97` means 3% off), times are seconds, ISK is float.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Mapping

TypeId = int


class Activity(StrEnum):
    MANUFACTURING = "manufacturing"
    REACTION = "reaction"
    COPYING = "copying"
    INVENTION = "invention"


class SecurityClass(StrEnum):
    HIGH = "high"
    LOW = "low"
    NULL = "null"


class BuildCategory(StrEnum):
    """Tier/category switches for build rules. A category in
    `BuildRules.buy_categories` means items in it are bought, not built."""

    T2_ITEMS = "t2_items"  # products of invented (T2) blueprints
    ADVANCED_COMPONENTS = "advanced_components"  # group 334
    CAPITAL_COMPONENTS = "capital_components"  # group 873
    ADVANCED_CAPITAL_COMPONENTS = "advanced_capital_components"  # group 913
    FUEL_BLOCKS = "fuel_blocks"  # group 1136
    REACTION_INTERMEDIATE = "reaction_intermediate"
    REACTION_COMPOSITE = "reaction_composite"
    REACTION_HYBRID = "reaction_hybrid"
    REACTION_BIOCHEMICAL = "reaction_biochemical"
    REACTION_MOLECULAR_FORGED = "reaction_molecular_forged"


# ---------------------------------------------------------------------------
# Reasons
# ---------------------------------------------------------------------------


class ReasonCode(StrEnum):
    # Item build/buy decision
    PLAN_LINE = "plan_line"
    BUILD_COMPONENT = "build_component"
    BUY_NO_BLUEPRINT = "buy_no_blueprint"
    BUY_BLACKLIST = "buy_blacklist"
    BUY_RULE = "buy_rule"
    BUY_INVENTION_INPUT = "buy_invention_input"
    LINE_NOT_BUILDABLE = "line_not_buildable"
    # ME / TE source
    ME_OVERRIDE = "me_override"
    ME_OWNED_BPO = "me_owned_bpo"
    ME_OWNED_BPC = "me_owned_bpc"
    ME_INVENTED = "me_invented"
    ME_REACTION = "me_reaction"
    ME_MISSING_BLUEPRINT = "me_missing_blueprint"
    # Blueprint source
    SOURCE_BPO = "source_bpo"
    SOURCE_BPC = "source_bpc"
    SOURCE_INVENTION = "source_invention"
    SOURCE_MISSING = "source_missing"
    # Station
    STATION_BEST = "station_best"
    STATION_NONE = "station_none"
    # Invention
    DECRYPTOR_CHOSEN = "decryptor_chosen"
    DECRYPTOR_AUTO = "decryptor_auto"
    # Schedule
    SCHEDULED = "scheduled"
    UNSCHEDULED_NO_CHARACTER = "unscheduled_no_character"
    # Cost
    FEE_COMPUTED = "fee_computed"
    FEE_NOT_MODELLED = "fee_not_modelled"
    PRICE_MISSING = "price_missing"


@dataclass(frozen=True, slots=True)
class Reason:
    """Why a derived value is what it is. `code` is stable for code and
    tests; `text` is the human-readable sentence the UI shows."""

    code: ReasonCode
    text: str


# ---------------------------------------------------------------------------
# Inputs: static game data (from the SDE)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ItemType:
    type_id: TypeId
    name: str
    group_id: int
    category_id: int


@dataclass(frozen=True, slots=True)
class Material:
    type_id: TypeId
    quantity: int


@dataclass(frozen=True, slots=True)
class SkillRequirement:
    skill_id: int
    level: int


@dataclass(frozen=True, slots=True)
class Recipe:
    """One blueprint activity. For invention, `product_type_id` is the T2
    blueprint, `product_quantity` its base runs and `probability` the base
    chance. Copying has no product."""

    time_seconds: int
    materials: tuple[Material, ...] = ()
    skills: tuple[SkillRequirement, ...] = ()
    product_type_id: TypeId | None = None
    product_quantity: int = 0
    probability: float | None = None


@dataclass(frozen=True, slots=True)
class BlueprintData:
    type_id: TypeId
    max_production_limit: int
    manufacturing: Recipe | None = None
    reaction: Recipe | None = None
    copying: Recipe | None = None
    invention: tuple[Recipe, ...] = ()


@dataclass(frozen=True, slots=True)
class Decryptor:
    type_id: TypeId
    name: str
    probability_multiplier: float  # attr 1112
    me_modifier: int  # attr 1113
    te_modifier: int  # attr 1114
    run_modifier: int  # attr 1124


@dataclass(frozen=True, slots=True)
class GameData:
    types: Mapping[TypeId, ItemType]
    blueprints: Mapping[TypeId, BlueprintData]
    decryptors: tuple[Decryptor, ...] = ()


# ---------------------------------------------------------------------------
# Inputs: account data (stations, characters, blueprints, assets, prices)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rig:
    """A fitted rig. Bonuses are the SDE values made positive: engineering
    rigs use attrs 2594 (ME) / 2593 (TE); reactor rigs 2714 / 2713."""

    type_id: TypeId
    group_id: int
    me_bonus: float = 0.0
    te_bonus: float = 0.0
    security_multipliers: Mapping[SecurityClass, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Structure:
    """Structure hull bonuses from the SDE. Defaults mean no bonus (NPC
    station, refinery for manufacturing attributes)."""

    type_id: TypeId
    name: str
    me_multiplier: float = 1.0  # attr 2600
    te_multiplier: float = 1.0  # attr 2602
    cost_multiplier: float = 1.0  # attr 2601
    reaction_te_multiplier: float = 1.0  # attr 2721


@dataclass(frozen=True, slots=True)
class Station:
    station_id: int
    name: str
    system_id: int
    structure: Structure
    facility_tax: float  # percent
    activities: frozenset[Activity]  # services online
    rigs: tuple[Rig, ...] = ()


@dataclass(frozen=True, slots=True)
class SolarSystem:
    system_id: int
    name: str
    security: float  # raw SDE value
    cost_indices: Mapping[Activity, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Character:
    character_id: int
    name: str
    skills: Mapping[int, int]  # skill_id -> active level
    activities: frozenset[Activity]  # what this character is allowed to run
    is_alpha: bool = False


@dataclass(frozen=True, slots=True)
class OwnedBlueprint:
    item_id: int
    type_id: TypeId
    is_copy: bool
    runs: int  # remaining runs; ignored for BPOs
    me: int
    te: int
    owner_id: int  # character or corporation id
    location_id: int | None = None


@dataclass(frozen=True, slots=True)
class Price:
    unit_price: float | None  # market price used for buying
    adjusted_price: float | None  # CCP adjusted price, used for EIV


@dataclass(frozen=True, slots=True)
class BuildRules:
    """Effective rules for this plan (account defaults with plan overrides
    already applied by the caller)."""

    item_blacklist: frozenset[TypeId] = frozenset()
    buy_categories: frozenset[BuildCategory] = frozenset()


DecryptorChoice = TypeId | Literal["auto", "none"]


@dataclass(frozen=True, slots=True)
class BlueprintChoice:
    """Per-blueprint user choices. Overrides apply to every job of the
    blueprint. `decryptor` is only used for invented blueprints."""

    me_override: int | None = None
    te_override: int | None = None
    decryptor: DecryptorChoice = "auto"


@dataclass(frozen=True, slots=True)
class PlanLine:
    line_id: str
    type_id: TypeId
    quantity: int


@dataclass(frozen=True, slots=True)
class PlanInput:
    lines: tuple[PlanLine, ...]
    game: GameData
    stations: tuple[Station, ...] = ()
    systems: Mapping[int, SolarSystem] = field(default_factory=dict)
    characters: tuple[Character, ...] = ()
    blueprints: tuple[OwnedBlueprint, ...] = ()
    # Assets available to this plan, after reservation and location filters.
    assets: Mapping[TypeId, int] = field(default_factory=dict)
    prices: Mapping[TypeId, Price] = field(default_factory=dict)
    rules: BuildRules = BuildRules()
    choices: Mapping[TypeId, BlueprintChoice] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


class ItemDecision(StrEnum):
    BUILD = "build"
    BUY = "buy"


class BlueprintSource(StrEnum):
    BPO = "bpo"
    BPC = "bpc"
    INVENTION = "invention"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class ItemPlan:
    """One item anywhere in the merged tree."""

    type_id: TypeId
    name: str
    decision: ItemDecision
    reason: Reason
    line_quantity: int  # quantity requested directly by plan lines
    input_quantity: int  # quantity consumed as an input by planned jobs
    on_hand_used: int  # assets applied (never to line_quantity)
    produced: int  # units output by planned jobs
    surplus: int  # produced beyond what is needed
    to_buy: int
    blueprint_type_id: TypeId | None = None
    build_category: BuildCategory | None = None


@dataclass(frozen=True, slots=True)
class StationChoice:
    station_id: int | None
    me_percent: float  # combined structure + rig material reduction
    time_multiplier: float  # combined structure + rig time factor
    reason: Reason


@dataclass(frozen=True, slots=True)
class DecryptorOption:
    decryptor_type_id: TypeId | None
    name: str
    probability: float
    me: int
    te: int
    runs_per_bpc: int
    bpcs_needed: int
    attempts: int
    invention_input_cost: float  # datacores + decryptors for all attempts
    material_cost: float  # direct inputs of the T2 jobs at this ME
    total_cost: float


@dataclass(frozen=True, slots=True)
class InventionPlan:
    t1_blueprint_type_id: TypeId
    decryptor_type_id: TypeId | None
    reason: Reason
    probability: float
    probability_reason: Reason
    runs_per_bpc: int
    bpcs_needed: int
    attempts: int
    options: tuple[DecryptorOption, ...]


@dataclass(frozen=True, slots=True)
class BlueprintPlan:
    """One blueprint used by the plan, with the decisions behind its jobs."""

    type_id: TypeId
    name: str
    activity: Activity
    product_type_id: TypeId
    runs: int
    sources: tuple[BlueprintSource, ...]
    source_reason: Reason
    station: StationChoice
    job_ids: tuple[str, ...]
    invention: InventionPlan | None = None


@dataclass(frozen=True, slots=True)
class JobCost:
    estimated_item_value: float
    fee: float | None
    reason: Reason


@dataclass(frozen=True, slots=True)
class ScheduledSlot:
    character_id: int | None
    start_seconds: float
    end_seconds: float
    reason: Reason


@dataclass(frozen=True, slots=True)
class PlannedJob:
    job_id: str
    activity: Activity
    blueprint_type_id: TypeId
    runs: int
    me: int
    te: int
    me_reason: Reason
    source: BlueprintSource
    station_id: int | None
    materials: tuple[Material, ...]  # total inputs for the whole job
    product_type_id: TypeId | None
    product_quantity: int
    depends_on: tuple[str, ...]
    cost: JobCost
    schedule: ScheduledSlot
    copies: int = 0  # copying only: number of copies made (each `runs` runs)


@dataclass(frozen=True, slots=True)
class ShoppingItem:
    type_id: TypeId
    name: str
    quantity: int
    unit_price: float | None
    total_price: float | None
    reason: Reason


@dataclass(frozen=True, slots=True)
class CostSummary:
    materials: float  # shopping list total, excluding invention inputs
    invention_inputs: float  # datacores + decryptors
    job_fees: Mapping[Activity, float]
    total: float
    unpriced_type_ids: tuple[TypeId, ...]


@dataclass(frozen=True, slots=True)
class PlanWarning:
    code: ReasonCode
    text: str


@dataclass(frozen=True, slots=True)
class PlanResult:
    items: tuple[ItemPlan, ...]
    blueprints: tuple[BlueprintPlan, ...]
    jobs: tuple[PlannedJob, ...]
    shopping_list: tuple[ShoppingItem, ...]
    costs: CostSummary
    total_seconds: float  # wall-clock until the last scheduled job ends
    warnings: tuple[PlanWarning, ...]
