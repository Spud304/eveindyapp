"""Integration tests: page loads, navigation, and auth redirects."""
import pytest

pytestmark = pytest.mark.integration


class TestPublicPages:
    def test_index_loads(self, page, base_url):
        page.goto(base_url + "/")
        assert page.title() == "EVE Industry"
        assert page.locator("text=Login with EVE SSO").is_visible()

    def test_health_endpoint(self, page, base_url):
        page.goto(base_url + "/health")
        assert "OK" in page.content()

    def test_unauthenticated_industry_redirects(self, page, base_url):
        page.goto(base_url + "/industry")
        # Should redirect to login page
        page.wait_for_url("**/login**")


class TestAuthenticatedNav:
    def test_nav_bar_links(self, auth_page, base_url):
        auth_page.goto(base_url + "/")
        nav = auth_page.locator(".navbar-menu")
        # Authenticated users see these nav items
        for label in ["Home", "Profile", "Industry", "Blueprints",
                      "Calculator", "Config", "Jobs", "Logout"]:
            assert nav.locator(f"text={label}").is_visible()
        # Should NOT see Login
        assert nav.locator("text=Login").count() == 0

    def test_index_shows_enter_industry(self, auth_page, base_url):
        auth_page.goto(base_url + "/")
        assert auth_page.locator("text=Enter Industry").is_visible()
        assert auth_page.locator("text=Login with EVE SSO").count() == 0
