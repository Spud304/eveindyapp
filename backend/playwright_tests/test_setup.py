from playwright.sync_api import expect

from .conftest import by_test_id, pick, uniq


def test_add_station_by_hand(login):
    s = login()
    page = s.page
    page.goto("/setup")
    by_test_id(page, "setup.add-station").click()
    name = uniq("raitaru")
    by_test_id(page, "setup.add-station.name").fill(name)
    pick(page, "setup.add-station.system", "D-JVG", "D-JVGJ (-0.22)")
    pick(page, "setup.add-station.hull", "Raitaru", "Raitaru")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_test_id("toast").last).to_have_text("Station added")
    station = s.json("/api/stations")[0]
    row = by_test_id(page, f"setup.station.{station['id']}")
    expect(row).to_contain_text(name)
    expect(row).to_contain_text("Raitaru")
    expect(row).to_contain_text("D-JVGJ")


def test_edit_rigs_tax_and_activities(login):
    s = login()
    station = s.add_station()
    page = s.page
    page.goto("/setup")
    row = by_test_id(page, f"setup.station.{station['id']}")

    pick(
        page,
        f"setup.station.{station['id']}.rig",
        "Basic Medium Ship Manufacturing Material",
        "Standup M-Set Basic Medium Ship Manufacturing Material Efficiency I",
    )
    expect(row).to_contain_text(
        "Standup M-Set Basic Medium Ship Manufacturing Material Efficiency I"
    )

    # Wait for each save's own response: the toast an earlier save showed would pass at once.
    def saved_by(action):
        with page.expect_response(
            lambda r: r.request.method == "PATCH" and "/api/stations/" in r.url
        ) as resp:
            action()
        assert resp.value.ok

    tax = row.get_by_title("facility tax")
    tax.fill("2.5")
    saved_by(tax.blur)
    saved_by(row.get_by_label("copying").check)

    saved = s.json("/api/stations")[0]
    assert saved["facility_tax"] == 2.5 and saved["tax_confirmed"]
    assert sorted(saved["activities"]) == ["copying", "manufacturing"]
    assert len(saved["rig_type_ids"]) == 1


def test_build_rules_persist(login):
    s = login()
    page = s.page
    page.goto("/setup")
    by_test_id(page, "setup.rules.fuel_blocks").check()
    expect(page.get_by_test_id("toast").last).to_have_text("Build rules saved")
    page.reload()
    expect(by_test_id(page, "setup.rules.fuel_blocks")).to_be_checked()
    assert s.json("/api/build-rules")["buy_categories"] == ["fuel_blocks"]
