import pytest

from apps.accounts import services
from apps.accounts.sso import SsoIdentity
from apps.sde.jsonl import ZipSource
from apps.sde.loader import import_source

from .conftest import BUILD, make_sde_zip, tiny_records

pytestmark = pytest.mark.django_db


@pytest.fixture
def api(client, tmp_path, sde_dir):
    path = tmp_path / f"eve-online-static-data-{BUILD}-jsonl.zip"
    path.write_bytes(make_sde_zip(tiny_records()))
    with ZipSource(path) as source:
        import_source(source, build=BUILD)
    user = services.ensure_user(services.upsert_character(SsoIdentity(1, "A", "o", ()), {}))
    client.force_login(user)
    return client


def test_buildable_search_returns_products_only(api):
    names = [
        t["name"] for t in api.get("/api/types/search", {"q": "rif", "kind": "buildable"}).json()
    ]
    assert names == ["Rifter"]  # the blueprint (Rifter Blueprint) is not a product
    assert api.get("/api/types/search", {"q": "trit", "kind": "buildable"}).json() == []


def test_search_ranks_exact_then_prefix(api):
    rows = api.get("/api/types/search", {"q": "rifter", "kind": "any"}).json()
    assert [t["name"] for t in rows] == ["Rifter", "Rifter Blueprint"]


def test_short_query_returns_nothing(api):
    assert api.get("/api/types/search", {"q": "r"}).json() == []


def test_unknown_kind_rejected(api):
    assert api.get("/api/types/search", {"q": "rif", "kind": "ships"}).status_code == 422


def test_type_names_and_systems(api):
    rows = api.get("/api/types", {"ids": "587,34,x"}).json()
    assert sorted(t["name"] for t in rows) == ["Rifter", "Tritanium"]
    assert api.get("/api/systems/search", {"q": "jit"}).json() == [
        {"id": 30000142, "name": "Jita", "security": pytest.approx(0.945913)}
    ]


def test_lookups_require_login(client):
    assert client.get("/api/types/search", {"q": "rif"}).status_code == 401
