"""Tests for route handlers across all blueprints."""
import responses


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
            json=[{
                "item_id": 1, "type_id": 688, "location_id": 60003760,
                "location_flag": "Hangar", "quantity": -1, "runs": -1,
                "material_efficiency": 10, "time_efficiency": 20,
            }],
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
        # search_items in industry.py joins with IndustryActivityProducts
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
        resp = auth_client.post("/config/stations/add",
            json={"name": "My Raitaru", "system_id": 30000142,
                  "system_name": "Jita", "structure_type": "raitaru",
                  "facility_tax": 5.0, "rigs": [None, None, None]},
            content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        added = data["stations"][-1]
        assert added["name"] == "My Raitaru"
        assert added["structure_type"] == "raitaru"

    def test_station_add_missing_name(self, auth_client):
        resp = auth_client.post("/config/stations/add",
            json={},
            content_type="application/json")
        assert resp.status_code == 400

    def test_station_update(self, auth_client):
        # Add first
        add_resp = auth_client.post("/config/stations/add",
            json={"name": "Original"},
            content_type="application/json")
        station_id = add_resp.get_json()["stations"][-1]["id"]
        # Update
        resp = auth_client.post("/config/stations/update",
            json={"id": station_id, "name": "Updated"},
            content_type="application/json")
        assert resp.status_code == 200
        updated = [s for s in resp.get_json()["stations"] if s["id"] == station_id]
        assert updated[0]["name"] == "Updated"

    def test_station_update_not_found(self, auth_client):
        resp = auth_client.post("/config/stations/update",
            json={"id": 999, "name": "X"},
            content_type="application/json")
        assert resp.status_code == 404

    def test_station_remove(self, auth_client):
        add_resp = auth_client.post("/config/stations/add",
            json={"name": "ToDelete"},
            content_type="application/json")
        stations_before = add_resp.get_json()["stations"]
        station_id = stations_before[-1]["id"]
        count_before = len(stations_before)
        resp = auth_client.post("/config/stations/remove",
            json={"id": station_id},
            content_type="application/json")
        assert resp.status_code == 200
        assert len(resp.get_json()["stations"]) == count_before - 1

    def test_blacklist_add_and_remove(self, auth_client):
        r1 = auth_client.post("/config/blacklist/add",
            json={"type_id": 34},
            content_type="application/json")
        assert r1.status_code == 200
        assert len(r1.get_json()["blacklist"]) == 1

        r2 = auth_client.post("/config/blacklist/remove",
            json={"type_id": 34},
            content_type="application/json")
        assert r2.status_code == 200
        assert len(r2.get_json()["blacklist"]) == 0

    def test_blacklist_add_duplicate(self, auth_client):
        auth_client.post("/config/blacklist/add",
            json={"type_id": 34},
            content_type="application/json")
        r2 = auth_client.post("/config/blacklist/add",
            json={"type_id": 34},
            content_type="application/json")
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
