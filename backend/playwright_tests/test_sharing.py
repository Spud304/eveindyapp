from playwright.sync_api import Browser, expect

from .conftest import BASE_URL, RIFTER, TRITANIUM, by_test_id, uniq

TEST_CORP = 98_999_001  # made up; only test characters are in it


def test_link_view_needs_no_login_and_hides_names(login, browser: Browser):
    s = login()
    s.add_station(name="PW Hidden Keep")
    plan = s.add_plan(uniq("linked"), [(RIFTER, 2)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.visibility").select_option("link")
    url = by_test_id(page, "plan.share-url")
    expect(url).to_be_visible()
    link = url.input_value()
    assert "/shared/" in link

    stranger = browser.new_context(base_url=BASE_URL)
    try:
        view = stranger.new_page()
        view.goto(link.replace(BASE_URL, ""))
        expect(by_test_id(view, "shared.name")).to_have_text(plan["name"])
        expect(by_test_id(view, "shared.anonymized")).to_be_visible()
        expect(by_test_id(view, f"plan.shopping.{TRITANIUM}")).to_be_visible()
        by_test_id(view, "shared.tabs.schedule").click()
        expect(by_test_id(view, "plan.schedule")).to_contain_text("Station 1")
        body = view.locator("body").inner_text()
        assert "PW Hidden Keep" not in body and s.name not in body

        # A new link turns the old one off.
        page.once("dialog", lambda d: d.accept())
        by_test_id(page, "plan.share-renew").click()
        expect(url).not_to_have_value(link)
        view.reload()
        expect(by_test_id(view, "shared.missing")).to_be_visible()
    finally:
        stranger.close()


def test_corp_members_find_and_view_the_plan(login):
    owner = login(corp=TEST_CORP)
    owner.add_station(name="PW Corp Keep")
    plan = owner.add_plan(uniq("corp"), [(RIFTER, 1)])
    owner.page.goto(f"/plans/{plan['id']}")
    by_test_id(owner.page, "plan.visibility").select_option("corp")
    expect(by_test_id(owner.page, "plan.share-corp")).to_be_visible()

    mate = login(corp=TEST_CORP)
    mate.page.goto("/plans")
    row = by_test_id(mate.page, f"plans.shared.{plan['id']}")
    expect(row).to_contain_text(owner.name)
    row.get_by_role("link").click()
    expect(by_test_id(mate.page, "shared.name")).to_have_text(plan["name"])
    expect(by_test_id(mate.page, "shared.anonymized")).to_have_count(0)
    by_test_id(mate.page, "shared.tabs.schedule").click()
    expect(by_test_id(mate.page, "plan.schedule")).to_contain_text("PW Corp Keep")

    outsider = login(corp=TEST_CORP + 1)
    outsider.page.goto(f"/plans/{plan['id']}/view")
    expect(by_test_id(outsider.page, "shared.missing")).to_be_visible()
