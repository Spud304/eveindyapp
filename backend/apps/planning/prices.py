"""Shopping list prices from the Jita 4-4 market (engine.pricing does the arithmetic)."""

from apps.esidata import market
from engine.pricing import reprice
from engine.types import PlanResult


def jita_priced(result: PlanResult | None) -> tuple[PlanResult | None, int]:
    """(the result with its shopping list priced through Jita sell orders, number of items
    whose orders could not be fetched and keep CCP's average price)."""
    if result is None or not result.shopping_list:
        return result, 0
    books, failed = market.jita_sell_books([s.type_id for s in result.shopping_list])
    return reprice(result, books), len(failed)
