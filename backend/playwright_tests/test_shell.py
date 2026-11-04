from playwright.sync_api import Browser, expect

from .conftest import BASE_URL, by_test_id


def test_signed_out_shows_login(browser: Browser):
    context = browser.new_context(base_url=BASE_URL)
    page = context.new_page()
    page.goto("/")
    expect(by_test_id(page, "shell.signed-out")).to_be_visible()
    expect(by_test_id(page, "shell.login")).to_have_attribute("href", "/auth/login?next=%2F")
    expect(by_test_id(page, "nav.plans")).to_have_count(0)
    context.close()


def test_nav_reaches_every_page_with_its_title(login):
    s = login()
    page = s.page
    page.goto("/")
    expect(by_test_id(page, "shell.user")).to_have_text(s.name)
    for nav, title in [
        ("plans", "Plans"),
        ("library", "Library"),
        ("setup", "Setup"),
        ("dashboard", "Dashboard"),
    ]:
        by_test_id(page, f"nav.{nav}").click()
        expect(by_test_id(page, "page.title")).to_have_text(title)
        expect(page).to_have_title(f"{title} · EVE Indy")


def test_theme_choice_survives_reload(login):
    page = login().page
    page.goto("/")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")  # default
    by_test_id(page, "shell.theme").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


def test_new_account_without_esi_is_flagged(login):
    page = login().page
    page.goto("/")
    expect(by_test_id(page, "shell.no-esi")).to_be_visible()
    expect(by_test_id(page, "dashboard.problems")).to_contain_text("has not granted ESI access")
