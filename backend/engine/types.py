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

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

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
    BUY_BLUEPRINT = "buy_blueprint"
    LINE_NOT_BUILDABLE = "line_not_buildable"
    # ME / TE source
    ME_OVERRIDE = "me_override"
    ME_OWNED_BPO = "me_owned_bpo"
    ME_OWNED_BPC = "me_owned_bpc"
    ME_BOUGHT = "me_bought"
    ME_INVENTED = "me_invented"
    ME_REACTION = "me_reaction"
    ME_MISSING_BLUEPRINT = "me_missing_blueprint"
    # Blueprint source
    SOURCE_BPO = "source_bpo"
    SOURCE_BPC = "source_bpc"
    SOURCE_COPY = "source_copy"
    SOURCE_BOUGHT = "source_bought"
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
    volume: float = 0.0  # m3 per unit as bought: packaged (a Rifter is 2,500, not 27,289)


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
    job_cost_multiplier: float = 1.0  # attr 1954; multiplies the job cost of every activity
    # Unpublished blueprints (CCP test and retired ones) can make the same product as the
    # real one, e.g. "Test Reaction Blueprint" 45732 and the Tungsten Carbide formula 46207.
    published: bool = True


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
    # Skill attr 1982 (percent per level, e.g. -1.0): when a manufacturing recipe requires
    # the skill, its time is multiplied by 1 + value x level / 100. [client][SDE]
    skill_time_bonuses: Mapping[int, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Inputs: account data (stations, characters, blueprints, assets, prices)
# ---------------------------------------------------------------------------


class ModifierKind(StrEnum):
    MATERIAL = "material"
    TIME = "time"
    COST = "cost"


@dataclass(frozen=True, slots=True)
class TargetFilter:
    """Which products a rig bonus applies to (SDE industryTargetFilters): a
    product matches if its category or its group is listed."""

    filter_id: int
    name: str
    category_ids: frozenset[int] = frozenset()
    group_ids: frozenset[int] = frozenset()

    def matches(self, item: ItemType | None) -> bool:
        if item is None:
            return False
        return item.category_id in self.category_ids or item.group_id in self.group_ids


@dataclass(frozen=True, slots=True)
class RigBonus:
    """One entry of a rig's SDE industryModifierSources record. `percent` is
    the rig's bonus made positive: the rig attribute its dogma effect feeds into
    the structure attribute the entry names (usually 2594 material, 2593 time,
    2595 cost; reactor rigs 2714 / 2713; Thukker rigs 2653; Upwell outpost rigs
    their own). `target` None means every product. `security_scaled`: the rig's
    security effect multiplies this attribute by the system's security modifier
    (effects 6842 / 6976; Upwell outpost rigs have none)."""

    activity: Activity
    kind: ModifierKind
    percent: float
    target: TargetFilter | None = None
    security_scaled: bool = True


@dataclass(frozen=True, slots=True)
class StructureModifier:
    """One entry of a structure hull's industryModifierSources record, with
    the multiplier read from its own dogma (e.g. Raitaru 2600 = 0.99)."""

    activity: Activity
    kind: ModifierKind
    multiplier: float


@dataclass(frozen=True, slots=True)
class Rig:
    type_id: TypeId
    name: str
    bonuses: tuple[RigBonus, ...] = ()
    # attrs 2355 / 2356 / 2357; a missing class means 1.0
    security_multipliers: Mapping[SecurityClass, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Structure:
    """A structure hull. No modifiers means no bonus (NPC station, or an
    activity the hull does not bonus)."""

    type_id: TypeId
    name: str
    modifiers: tuple[StructureModifier, ...] = ()


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
    # Open industry job the blueprint is installed in (ESI activity id), and seconds until it
    # ends; 0 or less means finished and waiting to be delivered. A BPC in a job is not used;
    # a BPO's jobs in the plan start when its job ends.
    job_activity_id: int | None = None
    job_ends_in: float = 0.0
    # A copy an open copy job is still making: the job's id and seconds until it ends (0 or
    # less: finished, waiting to be delivered). Usable from then on.
    source_job_id: int | None = None
    available_in: float = 0.0


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
    # Opt-in purchases. Bought BPCs: how many, runs each (None: the blueprint's max
    # production limit), ME / TE, and price per BPC (None: not set; BPCs sell on contracts,
    # so there is no market price). They are used after BPCs picked on a line.
    buy_bpcs: int = 0
    bpc_runs: int | None = None
    bpc_me: int = 10
    bpc_te: int = 20
    bpc_price: float | None = None
    # Extra BPOs bought on the market, unresearched unless set; they share the runs left
    # after BPCs evenly with the owned BPO, which gets the larger share.
    extra_bpos: int = 0
    bpo_me: int = 0
    bpo_te: int = 0


@dataclass(frozen=True, slots=True)
class PlanLine:
    """`blueprint_item_ids`: owned BPCs picked for this line ("run these BPCs"). The caller
    sets `quantity` from their runs; the engine uses them first, in this order, before any
    other source for their blueprint."""

    line_id: str
    type_id: TypeId
    quantity: int
    blueprint_item_ids: tuple[int, ...] = ()


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
    # Progress (step 5). Units of an item that jobs attributed to this plan will produce or
    # have produced; they cover demand before assets do, plan lines included.
    started: Mapping[TypeId, int] = field(default_factory=dict)
    # Invention attempts already running for this plan, by invented (T2) blueprint.
    started_attempts: Mapping[TypeId, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


class ItemDecision(StrEnum):
    BUILD = "build"
    BUY = "buy"


class BlueprintSource(StrEnum):
    BPO = "bpo"
    BPC = "bpc"
    COPY = "copy"  # copied from an owned BPO by this plan, to run jobs in parallel
    BOUGHT = "bought"  # BPCs or extra BPOs you chose to buy (BlueprintChoice)
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
    started: int = 0  # demand covered by jobs already attributed to the plan
    over_plan: int = 0  # attributed output beyond what the plan needs


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
    attempts: int  # still to start
    options: tuple[DecryptorOption, ...]
    attempts_in_progress: int = 0  # already running for this plan


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
    """Install cost split as the game splits it. Each part is rounded to whole ISK.
    `base` is EIV x runs (x 2% for copying and invention); the parts are fractions of it."""

    estimated_item_value: float
    fee: float | None
    reason: Reason
    base: float = 0.0
    job_cost: float = 0.0  # base x cost index x hull/rig/blueprint cost modifiers (+ alpha)
    facility_tax: float = 0.0
    scc_surcharge: float = 0.0
    security_tax: float = 0.0  # safe-sec systems only


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
    # The owned blueprint (OwnedBlueprint.item_id) the job is installed with; None for one the
    # plan has not got yet (a copy it makes, a bought BPC, an invented T2 copy, a missing one).
    blueprint_item_id: int | None = None


@dataclass(frozen=True, slots=True)
class ShoppingItem:
    type_id: TypeId
    name: str
    quantity: int
    unit_price: float | None
    total_price: float | None
    reason: Reason
    volume: float = 0.0  # m3 for the whole quantity, packaged
    # "average" (CCP's average price) or "jita" (priced through Jita 4-4 sell orders)
    price_source: str = "average"
    on_sale: int | None = None  # units on sale at Jita 4-4, when looked up


@dataclass(frozen=True, slots=True)
class CostSummary:
    materials: float  # shopping list total, excluding invention inputs
    invention_inputs: float  # datacores + decryptors
    job_fees: Mapping[Activity, float]
    blueprints: float  # bought BPCs (with a price set) and extra BPOs
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
