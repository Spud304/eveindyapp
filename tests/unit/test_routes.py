"""Tests for route handlers across all blueprints."""

import responses
from datetime import datetime, timezone, timedelta
from sqlalchemy import delete

from src.models.models import db, User, CachedToonInfo


# --- SSO mock helpers ---

SSO_TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
SSO_VERIFY_URL = "https://login.eveonline.com/oauth/verify"
ESI_BASE = "https://esi.evetech.net/latest"


def _mock_sso(character_id, character_name, owner_hash="hash123"):
    """Register mocked SSO token exchange and verify responses."""
    responses.add(
        responses.POST,
        SSO_TOKEN_URL,
        json={
            "access_token": f"token-{character_id}",
            "refresh_token": f"refresh-{character_id}",
            "expires_in": 1200,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        SSO_VERIFY_URL,
        json={
            "CharacterID": character_id,
            "CharacterName": character_name,
            "CharacterOwnerHash": owner_hash,
        },
        status=200,
    )


# --- Application routes ---


class TestAppRoutes:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.data == b"OK"

    def test_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200


# --- Auth routes ---


class TestAuthRoutes:
    def test_login_redirects_to_sso(self, client):
        resp = client.get("/login")
        assert resp.status_code == 302
        assert "login.eveonline.com" in resp.headers["Location"]

    def test_callback_invalid_state(self, client):
        with client.session_transaction() as sess:
            sess["state"] = "correct"
        resp = client.get("/callback?code=abc&state=wrong")
        assert resp.status_code == 400

    def test_logout_redirects(self, auth_client):
        resp = auth_client.get("/logout")
        assert resp.status_code == 302

    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/industry")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# --- Industry routes ---


class TestIndustryRoutes:
    def test_industry_hub(self, auth_client):
        resp = auth_client.get("/industry")
        assert resp.status_code == 200

    @responses.activate
    def test_blueprints_page(self, auth_client, app, test_user):
        # Mock ESI blueprints endpoint
        responses.add(
            responses.GET,
            f"https://esi.evetech.net/latest/characters/{test_user.character_id}/blueprints",
            json=[
                {
                    "item_id": 1,
                    "type_id": 688,
                    "location_id": 60003760,
                    "location_flag": "Hangar",
                    "quantity": -1,
                    "runs": -1,
                    "material_efficiency": 10,
                    "time_efficiency": 20,
                }
            ],
            status=200,
        )
        # Mock station name resolution
        responses.add(
            responses.GET,
            "https://esi.evetech.net/latest/universe/stations/60003760/",
            json={"name": "Jita IV - Moon 4 - Caldari Navy Assembly Plant"},
            status=200,
        )
        resp = auth_client.get("/industry/blueprints")
        assert resp.status_code == 200

    @responses.activate
    def test_refresh_blueprints(self, auth_client, test_user):
        responses.add(
            responses.GET,
            f"https://esi.evetech.net/latest/characters/{test_user.character_id}/blueprints",
            json=[],
            status=200,
        )
        resp = auth_client.post("/industry/blueprints/refresh")
        assert resp.status_code == 302

    @responses.activate
    def test_refresh_blueprints_esi_failure(self, auth_client, test_user):
        responses.add(
            responses.GET,
            f"https://esi.evetech.net/latest/characters/{test_user.character_id}/blueprints",
            json={"error": "forbidden"},
            status=403,
        )
        resp = auth_client.post("/industry/blueprints/refresh")
        assert resp.status_code == 500

    @responses.activate
    def test_jobs_page(self, auth_client, test_user):
        responses.add(
            responses.GET,
            f"https://esi.evetech.net/latest/characters/{test_user.character_id}/industry/jobs",
            json=[],
            status=200,
        )
        resp = auth_client.get("/industry/jobs")
        assert resp.status_code == 200

    def test_calculator_search(self, auth_client):
        resp = auth_client.get("/industry/calculator/search?q=Rif")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        # "Rifter" is in our seeded data but it's a product, not a material
        # search_items in industry.py joins with BlueprintProduct
        # so this should find items that are products of manufacturing

    def test_calculator_search_short_query(self, auth_client):
        resp = auth_client.get("/industry/calculator/search?q=R")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == []

    def test_system_search(self, auth_client):
        resp = auth_client.get("/industry/calculator/search_systems?q=Jit")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1
        assert data[0]["name"] == "Jita"


# --- Config routes ---


class TestConfigRoutes:
    def test_config_page(self, auth_client):
        resp = auth_client.get("/config")
        assert resp.status_code == 200

    def test_station_add(self, auth_client):
        resp = auth_client.post(
            "/config/stations/add",
            json={
                "name": "My Raitaru",
                "system_id": 30000142,
                "system_name": "Jita",
                "structure_type": "raitaru",
                "facility_tax": 5.0,
                "rigs": [None, None, None],
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        added = data["stations"][-1]
        assert added["name"] == "My Raitaru"
        assert added["structure_type"] == "raitaru"

    def test_station_add_missing_name(self, auth_client):
        resp = auth_client.post(
            "/config/stations/add", json={}, content_type="application/json"
        )
        assert resp.status_code == 400

    def test_station_update(self, auth_client):
        # Add first
        add_resp = auth_client.post(
            "/config/stations/add",
            json={"name": "Original"},
            content_type="application/json",
        )
        station_id = add_resp.get_json()["stations"][-1]["id"]
        # Update
        resp = auth_client.post(
            "/config/stations/update",
            json={"id": station_id, "name": "Updated"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        updated = [s for s in resp.get_json()["stations"] if s["id"] == station_id]
        assert updated[0]["name"] == "Updated"

    def test_station_update_not_found(self, auth_client):
        resp = auth_client.post(
            "/config/stations/update",
            json={"id": 999, "name": "X"},
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_station_remove(self, auth_client):
        add_resp = auth_client.post(
            "/config/stations/add",
            json={"name": "ToDelete"},
            content_type="application/json",
        )
        stations_before = add_resp.get_json()["stations"]
        station_id = stations_before[-1]["id"]
        count_before = len(stations_before)
        resp = auth_client.post(
            "/config/stations/remove",
            json={"id": station_id},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert len(resp.get_json()["stations"]) == count_before - 1

    def test_blacklist_add_and_remove(self, auth_client):
        r1 = auth_client.post(
            "/config/blacklist/add",
            json={"type_id": 34},
            content_type="application/json",
        )
        assert r1.status_code == 200
        assert len(r1.get_json()["blacklist"]) == 1

        r2 = auth_client.post(
            "/config/blacklist/remove",
            json={"type_id": 34},
            content_type="application/json",
        )
        assert r2.status_code == 200
        assert len(r2.get_json()["blacklist"]) == 0

    def test_blacklist_add_duplicate(self, auth_client):
        auth_client.post(
            "/config/blacklist/add",
            json={"type_id": 34},
            content_type="application/json",
        )
        r2 = auth_client.post(
            "/config/blacklist/add",
            json={"type_id": 34},
            content_type="application/json",
        )
        assert len(r2.get_json()["blacklist"]) == 1

    def test_config_search_systems(self, auth_client):
        resp = auth_client.get("/config/search_systems?q=Jit")
        assert resp.status_code == 200
        data = resp.get_json()
        assert any(s["name"] == "Jita" for s in data)

    def test_config_search_systems_short(self, auth_client):
        resp = auth_client.get("/config/search_systems?q=J")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_config_search_items(self, auth_client):
        resp = auth_client.get("/config/search_items?q=Tri")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


# --- Auth callback routes ---


class TestAuthCallbackRoutes:
    def _callback_with_state(self, client):
        """Set session state and return the callback URL."""
        with client.session_transaction() as sess:
            sess["state"] = "teststate"
        return "/callback?code=authcode&state=teststate"

    @responses.activate
    def test_callback_new_user_unauthenticated(self, client, app):
        """Fresh login creates a User with main_character_id = character_id."""
        _mock_sso(99001, "NewPilot")
        url = self._callback_with_state(client)
        resp = client.get(url)
        assert resp.status_code == 302

        with app.app_context():
            user = db.session.get(User, 99001)
            assert user is not None
            assert user.character_name == "NewPilot"
            assert user.main_character_id == 99001
            # cleanup
            db.session.delete(user)
            db.session.commit()

    @responses.activate
    def test_callback_existing_user_unauthenticated(self, client, app, test_user):
        """Existing user logs in — token updated, no new record."""
        _mock_sso(test_user.character_id, "TestPilot")
        url = self._callback_with_state(client)
        resp = client.get(url)
        assert resp.status_code == 302

        with app.app_context():
            user = db.session.get(User, test_user.character_id)
            assert user.access_token == f"token-{test_user.character_id}"

    @responses.activate
    def test_callback_link_new_character(self, auth_client, app, test_user):
        """Authenticated user links a new character — creates alt with correct main_character_id."""
        _mock_sso(99002, "AltPilot")
        url = self._callback_with_state(auth_client)
        resp = auth_client.get(url)
        assert resp.status_code == 302

        with app.app_context():
            alt = db.session.get(User, 99002)
            assert alt is not None
            assert alt.character_name == "AltPilot"
            assert alt.main_character_id == test_user.character_id
            # cleanup
            db.session.delete(alt)
            db.session.commit()

    @responses.activate
    def test_callback_link_existing_reassigns_main(self, auth_client, app, test_user):
        """Linking a character already linked to another main reassigns main_character_id."""
        with app.app_context():
            # Create an "other main" and an alt linked to it
            other_main = User(
                character_id=88001,
                character_name="OtherMain",
                character_owner_hash="oh1",
                main_character_id=88001,
                access_token="old",
                access_token_expires=datetime.now(timezone.utc) + timedelta(hours=1),
                refresh_token="old",
            )
            other_alt = User(
                character_id=88002,
                character_name="OtherAlt",
                character_owner_hash="oh2",
                main_character_id=88001,
                access_token="old",
                access_token_expires=datetime.now(timezone.utc) + timedelta(hours=1),
                refresh_token="old",
            )
            db.session.add_all([other_main, other_alt])
            db.session.commit()

        # Link OtherAlt (88002) to test_user's group
        _mock_sso(88002, "OtherAlt")
        url = self._callback_with_state(auth_client)
        resp = auth_client.get(url)
        assert resp.status_code == 302

        with app.app_context():
            alt = db.session.get(User, 88002)
            assert alt.main_character_id == test_user.character_id
            # OtherMain should still be its own main (only chars with old_main_id are moved)
            # Since 88002 had main_character_id=88001, all chars with main=88001 get moved
            other = db.session.get(User, 88001)
            assert other.main_character_id == test_user.character_id
            # cleanup
            db.session.delete(alt)
            db.session.delete(other)
            db.session.commit()

    @responses.activate
    def test_callback_link_main_with_alts_cascades(self, auth_client, app, test_user):
        """Linking a character that was a main cascades to all its alts."""
        with app.app_context():
            foreign_main = User(
                character_id=77001,
                character_name="ForeignMain",
                character_owner_hash="fh1",
                main_character_id=77001,
                access_token="old",
                access_token_expires=datetime.now(timezone.utc) + timedelta(hours=1),
                refresh_token="old",
            )
            foreign_alt1 = User(
                character_id=77002,
                character_name="ForeignAlt1",
                character_owner_hash="fh2",
                main_character_id=77001,
                access_token="old",
                access_token_expires=datetime.now(timezone.utc) + timedelta(hours=1),
                refresh_token="old",
            )
            foreign_alt2 = User(
                character_id=77003,
                character_name="ForeignAlt2",
                character_owner_hash="fh3",
                main_character_id=77001,
                access_token="old",
                access_token_expires=datetime.now(timezone.utc) + timedelta(hours=1),
                refresh_token="old",
            )
            db.session.add_all([foreign_main, foreign_alt1, foreign_alt2])
            db.session.commit()

        # Link ForeignMain (77001) to test_user's group
        _mock_sso(77001, "ForeignMain")
        url = self._callback_with_state(auth_client)
        resp = auth_client.get(url)
        assert resp.status_code == 302

        with app.app_context():
            # All three should now be under test_user's main
            for cid in (77001, 77002, 77003):
                user = db.session.get(User, cid)
                assert user.main_character_id == test_user.character_id, (
                    f"Character {cid} should have main_character_id={test_user.character_id}"
                )
            # cleanup
            for cid in (77001, 77002, 77003):
                db.session.delete(db.session.get(User, cid))
            db.session.commit()

    def test_link_requires_auth(self, client):
        """/link endpoint redirects unauthenticated users to login."""
        resp = client.get("/link")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    @responses.activate
    def test_callback_link_same_group_no_change(self, auth_client, app, test_user):
        """Linking a character already in the same group just updates the token."""
        with app.app_context():
            existing_alt = User(
                character_id=66001,
                character_name="MyAlt",
                character_owner_hash="mh1",
                main_character_id=test_user.character_id,
                access_token="old-token",
                access_token_expires=datetime.now(timezone.utc) + timedelta(hours=1),
                refresh_token="old-refresh",
            )
            db.session.add(existing_alt)
            db.session.commit()

        _mock_sso(66001, "MyAlt")
        url = self._callback_with_state(auth_client)
        resp = auth_client.get(url)
        assert resp.status_code == 302

        with app.app_context():
            alt = db.session.get(User, 66001)
            assert alt.main_character_id == test_user.character_id
            assert alt.access_token == "token-66001"  # token was updated
            # cleanup
            db.session.delete(alt)
            db.session.commit()


# --- User page routes ---


class TestUserRoutes:
    @responses.activate
    def test_user_page_renders(self, auth_client, app, test_user):
        """User page fetches from ESI and renders character info."""
        cid = test_user.character_id
        responses.add(
            responses.GET,
            f"{ESI_BASE}/characters/{cid}",
            json={
                "name": "TestPilot",
                "corporation_id": 98000001,
                "alliance_id": 99000001,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{ESI_BASE}/corporations/98000001",
            json={"name": "Test Corp"},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{ESI_BASE}/alliances/99000001",
            json={"name": "Test Alliance"},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{ESI_BASE}/characters/{cid}/wallet",
            json=1234567.89,
            status=200,
        )

        resp = auth_client.get("/user")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "TestPilot" in html
        assert "Test Corp" in html
        assert "Test Alliance" in html
        assert "1,234,567.89 ISK" in html

        # Verify it was cached
        with app.app_context():
            cached = CachedToonInfo.query.filter_by(character_id=cid).first()
            assert cached is not None
            assert cached.corporation_name == "Test Corp"
            db.session.execute(
                delete(CachedToonInfo).where(CachedToonInfo.character_id == cid)
            )
            db.session.commit()

    def test_user_page_uses_cache(self, auth_client, app, test_user):
        """When CachedToonInfo exists, no ESI calls are made."""
        with app.app_context():
            entry = CachedToonInfo(
                character_id=test_user.character_id,
                character_name="TestPilot",
                corporation_id=98000001,
                corporation_name="Cached Corp",
                alliance_id=None,
                alliance_name=None,
                wallet_balance=42.0,
                cached_at=datetime.now(timezone.utc),
            )
            db.session.merge(entry)
            db.session.commit()

        # No responses mocked — if ESI were called it would fail
        resp = auth_client.get("/user")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Cached Corp" in html
        assert "42.00 ISK" in html

        with app.app_context():
            db.session.execute(
                delete(CachedToonInfo).where(
                    CachedToonInfo.character_id == test_user.character_id
                )
            )
            db.session.commit()

    def test_user_page_shows_linked_characters(self, auth_client, app, test_user):
        """Linked characters appear in the user page."""
        with app.app_context():
            # Create linked alt and cache entries
            alt = User(
                character_id=55001,
                character_name="LinkedAlt",
                character_owner_hash="lh1",
                main_character_id=test_user.character_id,
                access_token="alt-token",
                access_token_expires=datetime.now(timezone.utc) + timedelta(hours=1),
                refresh_token="alt-refresh",
            )
            db.session.merge(alt)
            db.session.commit()
            db.session.merge(
                CachedToonInfo(
                    character_id=test_user.character_id,
                    character_name="TestPilot",
                    corporation_id=1,
                    corporation_name="Main Corp",
                    wallet_balance=100.0,
                    cached_at=datetime.now(timezone.utc),
                )
            )
            db.session.merge(
                CachedToonInfo(
                    character_id=55001,
                    character_name="LinkedAlt",
                    corporation_id=2,
                    corporation_name="Alt Corp",
                    wallet_balance=200.0,
                    cached_at=datetime.now(timezone.utc),
                )
            )
            db.session.commit()

        resp = auth_client.get("/user")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "LinkedAlt" in html
        assert "Alt Corp" in html
        assert "Linked Characters" in html

        with app.app_context():
            db.session.execute(
                delete(CachedToonInfo).where(
                    CachedToonInfo.character_id.in_([55001, test_user.character_id])
                )
            )
            db.session.commit()
            db.session.execute(delete(User).where(User.character_id == 55001))
            db.session.commit()

    def test_user_page_no_linked_section_for_solo(self, auth_client, app, test_user):
        """Single user with no alts doesn't see linked characters section."""
        with app.app_context():
            # Clean up any leftover linked users from prior tests
            db.session.execute(
                delete(User).where(
                    User.character_id != test_user.character_id,
                    User.main_character_id == test_user.character_id,
                )
            )
            db.session.commit()
            db.session.merge(
                CachedToonInfo(
                    character_id=test_user.character_id,
                    character_name="TestPilot",
                    corporation_id=1,
                    corporation_name="Solo Corp",
                    wallet_balance=50.0,
                    cached_at=datetime.now(timezone.utc),
                )
            )
            db.session.commit()

        resp = auth_client.get("/user")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Linked Characters" not in html

        with app.app_context():
            db.session.execute(
                delete(CachedToonInfo).where(
                    CachedToonInfo.character_id == test_user.character_id
                )
            )
            db.session.commit()
