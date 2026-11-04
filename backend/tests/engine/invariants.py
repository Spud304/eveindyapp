"""Checks every plan result must pass, whatever the plan. Engine tests call
`checked_plan` instead of `engine.plan`, so a regression that breaks the balance
between items, jobs, the shopping list and the schedule fails every test that
reaches it, not only a test that happens to assert the broken value."""

from collections import Counter, defaultdict

from engine import formulas as f
from engine import plan
from engine.schedule import _SLOT_KIND
from engine.types import Activity, ItemDecision, PlanInput, PlanResult

PRODUCING = (Activity.MANUFACTURING, Activity.REACTION)


def checked_plan(inp: PlanInput) -> PlanResult:
    result = plan(inp)
    assert_consistent(result, inp)
    return result


def assert_consistent(r: PlanResult, inp: PlanInput) -> None:
    consumed: Counter[int] = Counter()
    produced: Counter[int] = Counter()
    for j in r.jobs:
        for m in j.materials:
            consumed[m.type_id] += m.quantity
        if j.activity in PRODUCING and j.product_type_id is not None:
            produced[j.product_type_id] += j.product_quantity

    for i in r.items:
        supply = i.on_hand_used + i.started + i.produced - i.surplus + i.to_buy
        assert i.line_quantity + i.input_quantity == supply, f"balance of {i.name}: {i}"
        assert i.input_quantity == consumed[i.type_id], f"inputs of {i.name}"
        assert i.produced == produced[i.type_id], f"output of {i.name}"
        if i.decision == ItemDecision.BUY:
            assert i.produced == 0, f"{i.name} is bought but produced"

    to_buy = {i.type_id: i.to_buy for i in r.items if i.to_buy}
    listed = {s.type_id: s.quantity for s in r.shopping_list}
    extra_bpos = {
        bp for bp, c in inp.choices.items() if c.extra_bpos
    }  # bought originals go on the list without an item row
    for type_id, qty in listed.items():
        if type_id in to_buy:
            assert qty == to_buy[type_id], f"shopping list quantity of {type_id}"
        else:
            assert type_id in extra_bpos, f"{type_id} on the shopping list but not to buy"
    assert set(to_buy) <= set(listed), "an item to buy is missing from the shopping list"

    c = r.costs
    total = c.materials + c.invention_inputs + c.blueprints + sum(c.job_fees.values())
    assert abs(c.total - total) < 0.01, "cost total is not the sum of its parts"

    jobs = {j.job_id: j for j in r.jobs}
    for j in r.jobs:
        assert j.schedule.end_seconds >= j.schedule.start_seconds
        for d in j.depends_on:
            assert d in jobs, f"{j.job_id} depends on {d}, which is not planned"
            dep = jobs[d]
            assert j.schedule.start_seconds >= dep.schedule.end_seconds, (
                f"{j.job_id} starts before {d} ends"
            )
    if r.jobs:
        assert r.total_seconds == max(j.schedule.end_seconds for j in r.jobs)

    _assert_slots(r, inp)


def _assert_slots(r: PlanResult, inp: PlanInput) -> None:
    """At no moment does a character run more jobs of one slot kind than it has slots."""
    characters = {ch.character_id: ch for ch in inp.characters}
    events: dict[tuple[int, str], list[tuple[float, int]]] = defaultdict(list)
    limits: dict[tuple[int, str], int] = {}
    for j in r.jobs:
        cid = j.schedule.character_id
        if cid is None or j.schedule.end_seconds == j.schedule.start_seconds:
            continue
        key = (cid, _SLOT_KIND[j.activity])
        limits[key] = f.slots(characters[cid], j.activity)
        events[key] += [(j.schedule.start_seconds, 1), (j.schedule.end_seconds, -1)]
    for key, evs in events.items():
        running = 0
        for _, delta in sorted(evs):  # an end (-1) sorts before a start at the same moment
            running += delta
            assert running <= limits[key], f"character {key[0]} over its {key[1]} slots"
