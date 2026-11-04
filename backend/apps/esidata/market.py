"""Jita sell orders: what is on sale at Jita 4-4, and at what price.

`GET /markets/{region_id}/orders?order_type=sell&type_id=` is public (no token), cached by ESI
for 300 s, and costs 2 tokens of the `market-order` group's 12,000 per 15 minutes [official:
live OpenAPI spec]. One request per item; they run in parallel and each item's orders are kept
for CACHE_SECONDS, so only the first look in five minutes waits on ESI.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

from apps.esi.client import EsiError, get_client

log = logging.getLogger(__name__)

THE_FORGE = 10000002
JITA_4_4 = 60003760  # Jita IV - Moon 4 - Caldari Navy Assembly Plant [official: ESI]
CACHE_SECONDS = 300
WORKERS = 8

Book = tuple[tuple[float, int], ...]  # (price, units) at Jita 4-4, cheapest first


def _key(type_id: int) -> str:
    return f"market:jita:sell:{type_id}"


def _at_key(type_id: int) -> str:
    return f"market:jita:at:{type_id}"


def _fetch(type_id: int) -> Book:
    client = get_client()
    params = {"order_type": "sell", "type_id": type_id}
    first, pages = client.request(
        "GET", f"/markets/{THE_FORGE}/orders", params=params, with_pages=True
    )
    orders = list(first)
    for page in range(2, pages + 1):
        orders.extend(
            client.request("GET", f"/markets/{THE_FORGE}/orders", params={**params, "page": page})
        )
    book = sorted(
        (float(o["price"]), int(o["volume_remain"]))
        for o in orders
        if o.get("location_id") == JITA_4_4 and not o.get("is_buy_order")
    )
    return tuple(book)


def jita_sell_books(type_ids, refresh: bool = False) -> tuple[dict[int, Book], set[int]]:
    """({type id: Jita 4-4 sell orders, cheapest first}, type ids whose orders could not be
    fetched). An item with no orders at Jita has an empty book. `refresh` skips this cache and
    asks ESI again (ESI's own cache still holds its data for up to 300 s)."""
    ids = sorted(set(type_ids))
    keys = {t: _key(t) for t in ids}
    found = {} if refresh else cache.get_many(list(keys.values()))
    books = {t: tuple(tuple(x) for x in found[k]) for t, k in keys.items() if k in found}
    missing = [t for t in ids if t not in books]
    failed: set[int] = set()
    if missing:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for t, result in zip(missing, pool.map(_safe_fetch, missing), strict=True):
                if result is None:
                    failed.add(t)
                else:
                    books[t] = result
        now = timezone.now()
        cache.set_many({keys[t]: books[t] for t in missing if t in books}, CACHE_SECONDS)
        cache.set_many({_at_key(t): now for t in missing if t in books}, CACHE_SECONDS)
    return books, failed


def fetched_at(type_ids) -> datetime | None:
    """When the oldest of these items' cached orders were fetched; None if none are cached."""
    times = cache.get_many([_at_key(t) for t in set(type_ids)]).values()
    return min(times, default=None)


def _safe_fetch(type_id: int) -> Book | None:
    try:
        return _fetch(type_id)
    except EsiError as exc:
        log.warning("Jita orders for %s: %s", type_id, exc)
        return None
