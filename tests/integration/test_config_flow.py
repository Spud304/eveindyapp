"""Integration tests: station add/delete and blacklist management."""
import pytest

pytestmark = pytest.mark.integration


class TestStationManagement:
    def test_add_station(self, auth_page, base_url):
        auth_page.goto(base_url + "/config")
        # Click "Add Station" button
        auth_page.locator("#addStationBtn").click()
        # Modal should appear
        modal = auth_page.locator(".nc-modal-overlay.nc-show")
        modal.wait_for(state="visible", timeout=2000)
        assert auth_page.locator("#modalTitle").text_content() == "Add Station"
        # Fill in station name
        auth_page.locator("#modalName").fill("Test Raitaru")
        # Save
        auth_page.locator("#modalSaveBtn").click()
        # Wait for modal to close
        auth_page.locator(".nc-modal-overlay.nc-show").wait_for(state="hidden", timeout=2000)
        # Station should appear in the list
        assert auth_page.locator(".nc-station-name:text('Test Raitaru')").is_visible()

    def test_delete_station(self, auth_page, base_url):
        auth_page.goto(base_url + "/config")
        # First add a station
        auth_page.locator("#addStationBtn").click()
        auth_page.locator(".nc-modal-overlay.nc-show").wait_for(state="visible", timeout=2000)
        auth_page.locator("#modalName").fill("Delete Me")
        auth_page.locator("#modalSaveBtn").click()
        auth_page.locator(".nc-modal-overlay.nc-show").wait_for(state="hidden", timeout=2000)
        # Now delete it
        card = auth_page.locator(".nc-station-card", has_text="Delete Me")
        card.locator(".nc-station-delete").click()
        # Station should be removed
        auth_page.locator(".nc-station-name:text('Delete Me')").wait_for(state="hidden", timeout=2000)


class TestBlacklistManagement:
    def test_config_page_loads(self, auth_page, base_url):
        auth_page.goto(base_url + "/config")
        assert auth_page.locator("text=Configuration").first.is_visible()
        assert auth_page.get_by_text("Stations", exact=True).is_visible()
        assert auth_page.get_by_text("Production Blacklist", exact=True).is_visible()
