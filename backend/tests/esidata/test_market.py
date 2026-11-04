"""Jita sell orders from a mocked ESI."""

import httpx
import pytest
from django.core.cache import cache

from apps.esi.client import EsiClient
from apps.esidata import market

JITA, AMARR = market.JITA_4_4, 60008494


def order(price, units, location=JITA):
    return {"price": price, "volume_remain": units, "location_id": location, "is_buy_order": False}


@pytest.fixture
def esi(monkeypatch):
    cache.clear()
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url)
        type_id = int(request.url.params["type_id"])
        page = int(request.url.params.get("page", 1))
        if type_id == 666:
            return httpx.Response(500, json={})
        if type_id == 34:
            pages = {1: [order(5.0, 10), order(4.0, 20, AMARR)], 2: [order(4.5, 30)]}
            return httpx.Response(200, json=pages[page], headers={"X-Pages": "2"})
        return httpx.Response(200, json=[])

    client = EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(market, "get_client", lambda: client)
    return calls


def test_jita_orders_cheapest_first_across_pages(esi):
    books, failed = market.jita_sell_books([34, 35, 666])
    assert books[34] == ((4.5, 30), (5.0, 10))  # the Amarr order is left out
    assert books[35] == ()  # nothing on sale
    assert failed == {666}
    calls = len(esi)
    books, _ = market.jita_sell_books([34, 35])
    assert books[34] == ((4.5, 30), (5.0, 10))
    assert len(esi) == calls  # served from the cache
    assert market.fetched_at([34, 35]) is not None
    assert market.fetched_at([999]) is None


def test_refresh_asks_esi_again(esi):
    market.jita_sell_books([35])
    calls = len(esi)
    market.jita_sell_books([35], refresh=True)
    assert len(esi) == calls + 1
