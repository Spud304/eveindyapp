"""Market pricing: buying through sell orders, and repricing a plan result from them.

The planner prices with `Price.unit_price`; its only price-driven choice is the automatic
decryptor, and some reasons quote ISK. Market pricing is two steps: `market_prices` turns order
books into unit prices for a second planning pass, so those choices and texts use market prices
too; `reprice` then prices the final shopping list through the books at its exact quantities
and recomputes the cost summary. Job fees do not change: they come from CCP's adjusted price,
as in the game.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from .types import (
    CostSummary,
    PlanResult,
    PlanWarning,
    Price,
    ReasonCode,
    ShoppingItem,
    TypeId,
)

Book = tuple[tuple[float, int], ...]  # sell orders as (price, units), cheapest first


def unpriced_warning(count: int) -> PlanWarning:
    """The warning for shopping items left out of the totals. One function for the planner and
    `reprice`, so repricing can replace the planner's warning with an up-to-date one."""
    return PlanWarning(
        ReasonCode.PRICE_MISSING,
        f"{count} shopping item(s) have no price and are left out of totals.",
    )


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


def market_prices(
    prices: Mapping[TypeId, Price], books: Mapping[TypeId, Book], quantities: Mapping[TypeId, int]
) -> dict[TypeId, Price]:
    """`prices` with each booked type's unit price replaced by what buying `quantities` of it
    through its book costs per unit (one unit for types not on the list yet, e.g. decryptors
    the planner may pick). Empty books keep the old price; adjusted prices never change, since
    job fees use them. Planning again with these makes the price-driven choices (the automatic
    decryptor) and the ISK in reasons agree with the repriced shopping list."""
    out = dict(prices)
    for type_id, book in books.items():
        if not book:
            continue
        units = max(1, quantities.get(type_id, 0))
        old = prices.get(type_id)
        cost, top, short = book_cost(book, units)
        if short:
            cost += short * max(top or 0.0, (old.unit_price if old else None) or 0.0)
        out[type_id] = Price(cost / units, old.adjusted_price if old else None)
    return out


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
    # The planner's count of unpriced items is out of date once order books price some.
    before = result.costs.unpriced_type_ids
    warnings = [w for w in result.warnings if not (before and w == unpriced_warning(len(before)))]
    if unpriced:
        warnings.append(unpriced_warning(len(unpriced)))
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
