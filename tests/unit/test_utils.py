"""Tests for src/utils.py — ESI helpers, batch queries, token generation."""

import requests as req_lib
import responses
from datetime import datetime

from src.utils import (
    esi_get,
    esi_post,
    generate_token,
    batch_type_names,
    batch_market_info,
)
from src.models.models import db, CachedMarketData


# --- esi_get ---


class TestEsiGet:
    @responses.activate
    def test_success(self):
        responses.add(
            responses.GET,
            "https://esi.evetech.net/latest/test",
            json={"ok": True},
            status=200,
        )
        status, data = esi_get(
            "https://esi.evetech.net/latest/test", headers={"Authorization": "Bearer x"}
        )
        assert status == 200
        assert data == {"ok": True}

    @responses.activate
    def test_404(self):
        responses.add(
            responses.GET,
            "https://esi.evetech.net/latest/test",
            json={"error": "not found"},
            status=404,
        )
        status, data = esi_get(
            "https://esi.evetech.net/latest/test", headers={"Authorization": "Bearer x"}
        )
        assert status == 404
        assert data["error"] == "not found"

    @responses.activate
    def test_connection_error(self):
        responses.add(
            responses.GET,
            "https://esi.evetech.net/latest/test",
            body=req_lib.ConnectionError("timeout"),
        )
        status, data = esi_get(
            "https://esi.evetech.net/latest/test", headers={"Authorization": "Bearer x"}
        )
        assert status == 0
        assert data is None

    @responses.activate
    def test_empty_body(self):
        responses.add(
            responses.GET, "https://esi.evetech.net/latest/test", body="", status=200
        )
        status, data = esi_get(
            "https://esi.evetech.net/latest/test", headers={"Authorization": "Bearer x"}
        )
        assert status == 200
        assert data is None


# --- esi_post ---


class TestEsiPost:
    @responses.activate
    def test_success(self):
        responses.add(
            responses.POST,
            "https://esi.evetech.net/latest/test",
            json={"created": True},
            status=201,
        )
        status, data = esi_post(
            "https://esi.evetech.net/latest/test", headers={"Authorization": "Bearer x"}
        )
        assert status == 201
        assert data["created"] is True

    @responses.activate
    def test_connection_error(self):
        responses.add(
            responses.POST,
            "https://esi.evetech.net/latest/test",
            body=req_lib.ConnectionError("timeout"),
        )
        status, data = esi_post(
            "https://esi.evetech.net/latest/test", headers={"Authorization": "Bearer x"}
        )
        assert status == 0
        assert data is None


# --- generate_token ---


class TestGenerateToken:
    def test_returns_hex_string(self, app):
        with app.app_context():
            token = generate_token()
            assert isinstance(token, str)
            assert len(token) == 64  # SHA256 hex digest

    def test_different_calls_differ(self, app):
        with app.app_context():
            t1 = generate_token()
            t2 = generate_token()
            assert t1 != t2


# --- batch_type_names ---


class TestBatchTypeNames:
    def test_empty_set(self, app):
        with app.app_context():
            assert batch_type_names(set()) == {}

    def test_known_types(self, app):
        with app.app_context():
            result = batch_type_names({34, 35})
            assert result[34] == "Tritanium"
            assert result[35] == "Pyerite"

    def test_unknown_type(self, app):
        with app.app_context():
            result = batch_type_names({99999})
            assert 99999 not in result


# --- batch_market_info ---


class TestBatchMarketInfo:
    def test_empty_set(self, app):
        with app.app_context():
            avg, adj = batch_market_info(set())
            assert avg == {}
            assert adj == {}

    @responses.activate
    def test_cache_miss_fetches_esi(self, app):
        responses.add(
            responses.GET,
            "https://esi.evetech.net/latest/markets/prices/?datasource=tranquility",
            json=[
                {"type_id": 34, "average_price": 5.0, "adjusted_price": 4.5},
                {"type_id": 35, "average_price": 10.0, "adjusted_price": 9.0},
            ],
            status=200,
        )
        with app.app_context():
            avg, adj = batch_market_info({34, 35})
            assert avg[34] == 5.0
            assert adj[35] == 9.0

    @responses.activate
    def test_cache_hit_skips_esi(self, app):
        with app.app_context():
            # Pre-populate cache
            db.session.merge(
                CachedMarketData(
                    type_id=34,
                    price=5.0,
                    adjusted_price=4.5,
                    cached_at=datetime.now(),
                )
            )
            db.session.commit()

            # No ESI mock — if it tries to call ESI, responses will raise
            avg, adj = batch_market_info({34})
            assert avg[34] == 5.0
