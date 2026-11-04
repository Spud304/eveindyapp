import httpx
import pytest
from django.core.cache import cache

from apps.esi import client as client_module
from apps.esi.client import EsiClient, EsiError, EsiRateLimited, EsiUnavailable


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


def test_paged_starts_again_when_pages_come_from_two_snapshots():
    calls = []

    def pages(request):
        page = int(request.url.params.get("page", 1))
        calls.append(page)
        # The cache turns over after the first page: page 2 of the first pass is newer.
        modified = (
            "Tue, 03 Nov 2026 10:00:00 GMT" if len(calls) == 1 else "Tue, 03 Nov 2026 11:00:00 GMT"
        )
        return httpx.Response(200, json=[page], headers={"X-Pages": "2", "Last-Modified": modified})

    client = EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(pages))
    assert client.paged("/corporations/1/assets/", token="t", character_id=1) == [1, 2]
    assert calls == [1, 2, 1, 2]


def test_paged_gives_up_when_the_snapshot_keeps_changing():
    n = iter(range(100))

    def pages(request):
        page = int(request.url.params.get("page", 1))
        stamp = f"Tue, 03 Nov 2026 10:{next(n):02d}:00 GMT"
        return httpx.Response(200, json=[page], headers={"X-Pages": "2", "Last-Modified": stamp})

    client = EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(pages))
    with pytest.raises(EsiError, match="changed between pages"):
        client.paged("/corporations/1/assets/", token="t", character_id=1)


# --- rate limits and the breaker -------------------------------------------------------------


def scripted(*responses):
    """A transport answering with `responses` in order; records each request."""
    calls = []

    def handler(request):
        calls.append(request)
        return responses[len(calls) - 1]

    return EsiClient(base_url="https://esi.test", transport=httpx.MockTransport(handler)), calls


@pytest.fixture
def slept(monkeypatch):
    waits = []
    monkeypatch.setattr(client_module.time, "sleep", waits.append)
    return waits


def test_rate_limited_once_waits_and_retries(slept):
    client, calls = scripted(
        httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json={"ok": 1})
    )
    assert client.request("GET", "/x/") == {"ok": 1}
    assert slept == [1] and len(calls) == 2


def test_rate_limited_twice_raises(slept):
    client, _ = scripted(
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(429, headers={"Retry-After": "1"}),
    )
    with pytest.raises(EsiRateLimited):
        client.request("GET", "/x/")


def test_error_limited_waits_for_the_error_limit_reset(slept):
    client, _ = scripted(
        httpx.Response(420, headers={"X-Esi-Error-Limit-Reset": "7"}),
        httpx.Response(200, json=[]),
    )
    assert client.request("GET", "/x/") == []
    assert slept == [7]


def test_retry_after_as_a_date_waits_five_seconds(slept):
    date = "Wed, 04 Nov 2026 05:00:00 GMT"
    client, _ = scripted(
        httpx.Response(429, headers={"Retry-After": date}), httpx.Response(200, json=[])
    )
    assert client.request("GET", "/x/") == []
    assert slept == [5]


def test_three_server_errors_open_the_breaker_and_a_success_resets_the_count():
    client, calls = scripted(*[httpx.Response(503)] * 3)
    for _ in range(3):
        with pytest.raises(EsiUnavailable):
            client.request("GET", "/x/")
    with pytest.raises(EsiUnavailable, match="breaker"):
        client.request("GET", "/x/")
    assert len(calls) == 3  # the fourth call never reached ESI

    cache.clear()  # the breaker expired
    client, _ = scripted(httpx.Response(503), httpx.Response(200, json=[]), httpx.Response(503))
    with pytest.raises(EsiUnavailable):
        client.request("GET", "/x/")
    assert client.request("GET", "/x/") == []
    assert cache.get("esi:5xx") is None
    with pytest.raises(EsiUnavailable):
        client.request("GET", "/x/")
    assert not cache.get(client_module.BREAKER_KEY)
