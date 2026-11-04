"""Plans priced from the Jita 4-4 market (engine.pricing does the arithmetic)."""

import dataclasses
from dataclasses import dataclass

from apps.esidata import market
from engine import plan
from engine.pricing import market_prices, reprice
from engine.types import PlanInput, PlanResult


@dataclass
class JitaPlan:
    input: PlanInput  # with Jita unit prices, for anything else run on this plan (buy options)
    result: PlanResult
    failed: int  # shopping items whose orders could not be fetched; they keep CCP's average


def jita_plan(inp: PlanInput, first: PlanResult, also: tuple[int, ...] = ()) -> JitaPlan:
    """Plan again with Jita prices, then price the shopping list through the order books.

    `first` is the plan at CCP average prices; its shopping list says what to look up. The
    decryptors on offer and the datacores of invented blueprints are looked up too, so the
    automatic decryptor is chosen on the prices the shopping list will show. `also`: more types
    to price (a blueprint whose purchase is being weighed)."""
    invention_inputs = {
        m.type_id
        for b in first.blueprints
        if b.invention
        for bp in [inp.game.blueprints.get(b.invention.t1_blueprint_type_id)]
        if bp
        for r in bp.invention
        for m in r.materials
    }
    wanted = (
        {s.type_id for s in first.shopping_list}
        | invention_inputs
        | ({d.type_id for d in inp.game.decryptors} if invention_inputs else set())
        | set(also)
    )
    if not wanted:
        return JitaPlan(inp, first, 0)
    books, failed = market.jita_sell_books(sorted(wanted))
    quantities = {s.type_id: s.quantity for s in first.shopping_list}
    priced = dataclasses.replace(inp, prices=market_prices(inp.prices, books, quantities))
    result = reprice(plan(priced), books)
    on_list = {s.type_id for s in result.shopping_list}
    return JitaPlan(priced, result, len(set(failed) & on_list))
