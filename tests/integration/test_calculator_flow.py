"""Integration tests: calculator search and calculation flow."""
import pytest

pytestmark = pytest.mark.integration


class TestCalculatorSearch:
    def test_search_autocomplete(self, auth_page, base_url):
        auth_page.goto(base_url + "/industry/calculator")
        search_input = auth_page.locator("#itemSearch")
        search_input.fill("Rift")
        # Wait for dropdown to appear (debounce is 250ms)
        dropdown = auth_page.locator("#searchDropdown")
        dropdown.wait_for(state="visible", timeout=3000)
        # Should show Rifter in results
        assert dropdown.locator(".nc-search-item").count() > 0
        assert dropdown.locator("text=Rifter").is_visible()

    def test_search_no_results(self, auth_page, base_url):
        auth_page.goto(base_url + "/industry/calculator")
        search_input = auth_page.locator("#itemSearch")
        search_input.fill("XYZNONEXISTENT")
        dropdown = auth_page.locator("#searchDropdown")
        dropdown.wait_for(state="visible", timeout=3000)
        assert dropdown.locator(".nc-search-empty").is_visible()

    def test_full_calculation_flow(self, auth_page, base_url):
        auth_page.goto(base_url + "/industry/calculator")
        search_input = auth_page.locator("#itemSearch")
        search_input.fill("Rift")
        dropdown = auth_page.locator("#searchDropdown")
        dropdown.wait_for(state="visible", timeout=3000)
        # Click on Rifter
        dropdown.locator("text=Rifter").click()
        # Verify hidden field was set
        assert auth_page.locator("#productTypeId").input_value() == "587"
        # Submit the form
        auth_page.locator("button:text('Calculate')").click()
        # Wait for results page to load
        auth_page.wait_for_load_state("networkidle")
        # Should show build summary with Rifter
        assert auth_page.locator("text=Rifter").first.is_visible()
        # Should have materials table (inside a collapsible panel)
        assert auth_page.locator("text=Materials Required").is_visible()
