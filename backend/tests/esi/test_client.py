import httpx
import pytest
from django.core.cache import cache

from apps.esi.client import EsiClient, EsiError, EsiUnavailable


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_transport_failure_is_an_esi_error():
    def refuse(request):
        raise httpx.ConnectError("no route", request=request)

    client = EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(refuse))
    with pytest.raises(EsiUnavailable):
        client.character_public(1)


def test_non_json_body_is_an_esi_error():
    def html(request):
        return httpx.Response(200, text="<html>maintenance</html>")

    client = EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(html))
    with pytest.raises(EsiError):
        client.character_public(1)


def test_authenticated_cache_is_per_character():
    seen = []

    def etagged(request):
        seen.append(request.headers.get("If-None-Match"))
        return httpx.Response(
            200, json={"who": request.headers["Authorization"]}, headers={"ETag": "e1"}
        )

    client = EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(etagged))
    a = client.request("GET", "/characters/1/assets/", token="ta", character_id=1)
    b = client.request("GET", "/characters/1/assets/", token="tb", character_id=2)
    assert a == {"who": "Bearer ta"} and b == {"who": "Bearer tb"}
    assert seen == [None, None]  # character 2 did not reuse character 1's ETag


def test_token_without_character_id_refused():
    client = EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(lambda r: None))
    with pytest.raises(ValueError):
        client.request("GET", "/x/", token="t")


def test_paged_reads_every_page():
    def pages(request):
        page = int(request.url.params.get("page", 1))
        return httpx.Response(200, json=[page], headers={"X-Pages": "3"})

    client = EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(pages))
    assert client.paged("/corporations/1/assets/", token="t", character_id=1) == [1, 2, 3]


def test_not_modified_returns_cached_body_and_pages():
    calls = []

    def handler(request):
        calls.append(1)
        if request.headers.get("If-None-Match") == "e1":
            return httpx.Response(304)
        return httpx.Response(200, json=[1], headers={"ETag": "e1", "X-Pages": "1"})

    client = EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(handler))
    first = client.request("GET", "/a/", token="t", character_id=1, with_pages=True)
    again = client.request("GET", "/a/", token="t", character_id=1, with_pages=True)
    assert first == again == ([1], 1) and len(calls) == 2
