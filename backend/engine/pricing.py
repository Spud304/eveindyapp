"""Market pricing: buying through sell orders, and repricing a plan result from them.

The planner prices with CCP's average price (`Price.unit_price`); its only price-driven choice is
the automatic decryptor. `reprice` takes a finished result and prices its shopping list from
order books instead, then recomputes the cost summary. Job fees do not change: they come from
CCP's adjusted price, as in the game.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from .types import CostSummary, PlanResult, PlanWarning, ReasonCode, ShoppingItem, TypeId

Book = tuple[tuple[float, int], ...]  # sell orders as (price, units), cheapest first


def book_cost(book: Book, units: int) -> tuple[float, float | None, int]:
    """(ISK for `units` bought cheapest first, dearest price paid, units short)."""
    cost, top, left = 0.0, None, units
    for price, available in book:
        if left <= 0:
            break
        take = min(available, left)
        cost += take * price
        top = price
        left -= take
    return cost, top, max(0, left)


def price_item(item: ShoppingItem, book: Book | None) -> ShoppingItem:
    """An item priced through its order book. No book (not fetched): unchanged. An empty book
    (nothing on sale): keeps the average price, marked as such. Not enough on sale: what is
    on sale, plus the rest at the dearest order (or the average if dearer)."""
    if book is None:
        return item
    on_sale = sum(units for _, units in book)
    if not book:
        return dataclasses.replace(item, price_source="average", on_sale=0)
    cost, top, short = book_cost(book, item.quantity)
    if short:
        rest = max(top or 0.0, item.unit_price or 0.0)
        cost += short * rest
    return dataclasses.replace(
        item,
        unit_price=cost / item.quantity,
        total_price=cost,
        price_source="jita",
        on_sale=on_sale,
    )


def reprice(result: PlanResult, books: Mapping[TypeId, Book]) -> PlanResult:
    """The result with its shopping list priced through `books` and its costs recomputed."""
    shopping = tuple(price_item(s, books.get(s.type_id)) for s in result.shopping_list)
    old = {s.type_id: s for s in result.shopping_list}
    materials = invention = 0.0
    bpo_change = 0.0
    unpriced = []
    for s in shopping:
        if s.total_price is None:
            unpriced.append(s.type_id)
        elif s.reason.code == ReasonCode.BUY_INVENTION_INPUT:
            invention += s.total_price
        elif s.reason.code == ReasonCode.BUY_BLUEPRINT:
            bpo_change += s.total_price - (old[s.type_id].total_price or 0.0)
        else:
            materials += s.total_price
    blueprints = result.costs.blueprints + bpo_change
    fees = sum(result.costs.job_fees.values())
    costs = CostSummary(
        materials=materials,
        invention_inputs=invention,
        job_fees=result.costs.job_fees,
        blueprints=blueprints,
        total=materials + invention + blueprints + fees,
        unpriced_type_ids=tuple(sorted(unpriced)),
    )
    warnings = list(result.warnings)
    short = [s for s in shopping if s.on_sale is not None and 0 < s.on_sale < s.quantity]
    if short:
        warnings.append(
            PlanWarning(
                ReasonCode.PRICE_MISSING,
                f"{len(short)} item(s) have less on sale at Jita than the plan needs; the rest "
                "is priced at the dearest order.",
            )
        )
    return dataclasses.replace(
        result, shopping_list=shopping, costs=costs, warnings=tuple(warnings)
    )
