from playwright.sync_api import expect

from .conftest import RIFTER, TRITANIUM, by_test_id, make_bpc, make_job, pick, uniq


def shopping_qty(page, type_id: int) -> int:
    row = by_test_id(page, f"plan.shopping.{type_id}")
    expect(row).to_be_visible()
    return int(row.locator("td").nth(1).inner_text().replace(",", ""))


def test_create_plan_add_line_and_see_the_shopping_list(login):
    s = login()
    s.add_station()
    page = s.page
    page.goto("/plans")
    name = uniq("rifters")
    by_test_id(page, "plans.new-name").fill(name)
    by_test_id(page, "plans.create").click()
    expect(by_test_id(page, "plan.name")).to_have_value(name)
    expect(by_test_id(page, "plan.empty")).to_contain_text("Nothing to plan yet")

    pick(page, "plan.add-line", "Rifter", "Rifter")
    expect(by_test_id(page, f"plan.line.{RIFTER}")).to_be_visible()
    one = shopping_qty(page, TRITANIUM)
    assert one > 0
    expect(by_test_id(page, f"plan.shopping.{TRITANIUM}")).to_contain_text(f"{one * 0.01:,.0f} m³")
    expect(by_test_id(page, "plan.shopping.volume")).to_contain_text("m³")

    qty = by_test_id(page, f"plan.line.{RIFTER}.qty")
    qty.fill("2")
    qty.press("Enter")
    # Materials round per job, so two Rifters need twice as much, give or take one unit.
    expect(by_test_id(page, f"plan.shopping.{TRITANIUM}").locator("td").nth(1)).not_to_have_text(
        f"{one:,}"
    )
    two = shopping_qty(page, TRITANIUM)
    assert 2 * one - 1 <= two <= 2 * one


def test_quick_line_edits_build_on_each_other(login):
    """A second edit made while the first is saving starts from the first, not from the
    lines the server last sent."""
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("quick"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    qty = by_test_id(page, f"plan.line.{RIFTER}.qty")
    expect(qty).to_have_value("1")
    qty.fill("3")
    qty.press("Enter")
    pick(page, "plan.add-line", "Rifter", "Rifter")  # raises the Rifter line by one
    expect(qty).to_have_value("4")
    page.reload()
    expect(by_test_id(page, f"plan.line.{RIFTER}.qty")).to_have_value("4")


def test_copy_waits_for_the_recompute(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("copy"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    copy = by_test_id(page, "plan.shopping.copy")
    expect(copy).to_be_enabled()
    expect(by_test_id(page, "plan.data-age")).to_be_visible()
    qty = by_test_id(page, f"plan.line.{RIFTER}.qty")
    qty.fill("2")
    qty.press("Enter")
    # Disabled while the old list is on screen, enabled again with the new one.
    expect(by_test_id(page, "plan.main")).to_have_attribute("data-stale", "false")
    expect(copy).to_be_enabled()


PACKRAT, TRACTOR_BEAM = 33700, 24348  # 'Packrat' Mobile Tractor Unit uses a Small Tractor Beam I


def test_items_tab_flips_one_item_for_this_plan(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("items"), [(PACKRAT, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.tabs.items").click()
    beam = by_test_id(page, f"plan.item.{TRACTOR_BEAM}")
    expect(beam).to_contain_text("build")
    expect(by_test_id(page, f"plan.item.{PACKRAT}")).to_contain_text("plan line")

    by_test_id(page, f"plan.item.{TRACTOR_BEAM}.buy").click()
    expect(beam).to_contain_text("buy")
    expect(by_test_id(page, f"plan.item.{TRACTOR_BEAM}.default")).to_have_text("Undo buy")
    by_test_id(page, "plan.tabs.shopping").click()
    expect(by_test_id(page, f"plan.shopping.{TRACTOR_BEAM}")).to_be_visible()

    by_test_id(page, "plan.tabs.items").click()
    by_test_id(page, f"plan.item.{TRACTOR_BEAM}.default").click()
    expect(beam).to_contain_text("build")


def test_blueprint_me_override(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("me"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.tabs.blueprints").click()
    row = by_test_id(page, f"plan.blueprint.{RIFTER_BP}")
    expect(row).to_contain_text("0 / 0")
    by_test_id(page, f"plan.blueprint.{RIFTER_BP}.adjust").click()
    by_test_id(page, f"plan.blueprint.{RIFTER_BP}.me").fill("10")
    by_test_id(page, f"plan.blueprint.{RIFTER_BP}.te").fill("20")
    by_test_id(page, f"plan.blueprint.{RIFTER_BP}.save-me").click()
    expect(row).to_contain_text("10 / 20")


def test_tabs_show_reasons(login):
    s = login()
    s.add_station(name="PW Azbel")
    plan = s.add_plan(uniq("tabs"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")

    expect(by_test_id(page, f"plan.shopping.{TRITANIUM}")).to_contain_text(
        "No blueprint or reaction."
    )

    by_test_id(page, "plan.tabs.blueprints").click()
    bp = by_test_id(page, "plan.blueprints")
    expect(bp).to_contain_text("Rifter Blueprint")
    expect(bp).to_contain_text("missing")  # the test account owns no blueprints
    expect(bp).to_contain_text("PW Azbel")
    expect(bp).to_contain_text("Lowest materials, then time")

    by_test_id(page, "plan.tabs.schedule").click()
    expect(by_test_id(page, "plan.schedule")).to_contain_text(
        "nobody"
    )  # no character skills synced

    by_test_id(page, "plan.tabs.cost").click()
    expect(by_test_id(page, "plan.cost.summary")).to_contain_text("Total")

    expect(by_test_id(page, "plan.warnings")).to_contain_text("no owned blueprint")


def test_plan_without_station_warns(login):
    s = login()
    plan = s.add_plan(uniq("nostation"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    expect(by_test_id(page, "plan.warnings")).to_contain_text("No station offers manufacturing")


def test_activate_switches_the_active_plan(login):
    s = login()
    a = s.add_plan(uniq("a"), [(RIFTER, 1)])
    b = s.add_plan(uniq("b"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{a['id']}")
    by_test_id(page, "plan.activate").click()
    expect(by_test_id(page, "plan.deactivate")).to_be_visible()
    page.goto(f"/plans/{b['id']}")
    by_test_id(page, "plan.activate").click()
    expect(by_test_id(page, "plan.deactivate")).to_be_visible()
    page.goto("/plans")
    expect(by_test_id(page, f"plans.row.{b['id']}")).to_contain_text("active")
    expect(by_test_id(page, f"plans.row.{a['id']}")).not_to_contain_text("active")


def test_rule_override_buys_the_line_inputs(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("rules"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.rule.t2_items").select_option("buy")
    expect(page.get_by_test_id("toast").last).to_have_text("Plan saved")
    saved = s.json(f"/api/plans/{plan['id']}")
    assert saved["category_overrides"] == {"t2_items": "buy"}


def test_delete_plan_asks_first(login):
    s = login()
    plan = s.add_plan(uniq("delete"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    messages = []

    def answer(dialog):
        messages.append(dialog.message)
        dialog.accept()

    page.on("dialog", answer)
    by_test_id(page, "plan.delete").click()
    expect(by_test_id(page, "page.title")).to_have_text("Plans")
    assert messages and "Its lines and settings go with it" in messages[0]
    assert s.json("/api/plans") == []


def test_plan_settings_toggles_save(login):
    s = login()
    first = s.add_station(name="PW one")
    s.add_station(name="PW two")
    plan = s.add_plan(uniq("settings"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")

    def saved(action):
        """Run `action` and wait for the plan PATCH it sends: the toast from an earlier save
        already says "Plan saved", so it cannot tell this save apart."""
        with page.expect_response(
            lambda r: r.request.method == "PATCH" and f"/api/plans/{plan['id']}" in r.url
        ):
            action()

    saved(lambda: by_test_id(page, "plan.reserve").check())
    saved(lambda: by_test_id(page, "plan.stations.all").uncheck())  # lists every station, ticked
    expect(by_test_id(page, f"plan.stations.{first['id']}")).to_be_checked()
    saved(lambda: by_test_id(page, f"plan.stations.{first['id']}").uncheck())

    page.reload()
    expect(by_test_id(page, "plan.reserve")).to_be_checked()
    expect(by_test_id(page, f"plan.stations.{first['id']}")).not_to_be_checked()
    saved = s.json(f"/api/plans/{plan['id']}")
    assert saved["reserve_assets"] and first["id"] not in saved["station_ids"]
    assert len(saved["station_ids"]) == 1


RIFTER_BP = 691


def test_pick_bpcs_for_a_line(login):
    s = login()
    s.add_station()
    a, b = make_bpc(s.character_id, RIFTER_BP, 9), make_bpc(s.character_id, RIFTER_BP, 9)
    spare = make_bpc(s.character_id, RIFTER_BP, 4)
    plan = s.add_plan(uniq("picked"), [])
    page = s.page
    page.goto(f"/plans/{plan['id']}")

    by_test_id(page, "plan.pick-bpcs").click()
    by_test_id(page, "plan.bpc-search").fill("Rifter")
    by_test_id(page, f"plan.bpc.{a}.tick").check()
    by_test_id(page, f"plan.bpc.{b}.tick").check()
    expect(by_test_id(page, "plan.bpc-add")).to_have_text("Add 2 BPCs (18 runs)")
    by_test_id(page, "plan.bpc-add").click()

    line = by_test_id(page, f"plan.line.{RIFTER}")
    expect(line).to_contain_text("18")
    expect(by_test_id(page, f"plan.line.{RIFTER}.bpcs")).to_have_text("· 2 picked BPCs")
    expect(by_test_id(page, f"plan.line.{RIFTER}.qty")).to_have_count(0)  # set by the BPCs

    by_test_id(page, "plan.tabs.blueprints").click()
    bp = by_test_id(page, f"plan.blueprint.{RIFTER_BP}")
    expect(bp).to_contain_text("2 owned BPC(s) cover 18 runs (2 picked for this plan)")

    # Another plan sees only the BPC nobody picked.
    other = s.add_plan(uniq("other"), [])
    page.goto(f"/plans/{other['id']}")
    by_test_id(page, "plan.pick-bpcs").click()
    by_test_id(page, "plan.bpc-search").fill("Rifter")
    expect(by_test_id(page, f"plan.bpc.{spare}")).to_be_visible()
    expect(by_test_id(page, f"plan.bpc.{a}")).to_have_count(0)
    expect(by_test_id(page, f"plan.bpc.{b}")).to_have_count(0)


def test_blueprint_in_a_job_shows_in_the_library_and_is_not_offered(login):
    s = login()
    s.add_station()
    busy, free = make_bpc(s.character_id, RIFTER_BP, 9), make_bpc(s.character_id, RIFTER_BP, 9)
    make_job(s.character_id, RIFTER_BP, RIFTER, runs=9, blueprint_item=busy)
    page = s.page
    page.goto("/library")
    expect(by_test_id(page, f"library.row.{busy}.job")).to_contain_text("in manufacturing job")
    expect(by_test_id(page, f"library.row.{free}.job")).to_have_count(0)

    plan = s.add_plan(uniq("busy"), [])
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.pick-bpcs").click()
    by_test_id(page, "plan.bpc-search").fill("Rifter")
    expect(by_test_id(page, f"plan.bpc.{free}")).to_be_visible()
    expect(by_test_id(page, f"plan.bpc.{busy}")).to_have_count(0)


def test_buy_options_apply_and_remove(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("buy"), [(RIFTER, 4)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.tabs.blueprints").click()
    by_test_id(page, f"plan.blueprint.{RIFTER_BP}.buy").click()
    bpcs = by_test_id(page, f"plan.blueprint.{RIFTER_BP}.option.bpcs")
    expect(bpcs).to_contain_text("price not set")
    expect(by_test_id(page, f"plan.blueprint.{RIFTER_BP}.option.bpo")).to_contain_text(
        "Buy 1 extra BPO"
    )

    by_test_id(page, f"plan.blueprint.{RIFTER_BP}.bpc-price").fill("1500000")
    by_test_id(page, f"plan.blueprint.{RIFTER_BP}.apply.bpcs").click()
    row = by_test_id(page, f"plan.blueprint.{RIFTER_BP}")
    expect(row).to_contain_text("bought")
    expect(by_test_id(page, f"plan.blueprint.{RIFTER_BP}.options")).to_contain_text("Buying 1 BPC")

    by_test_id(page, "plan.tabs.cost").click()
    expect(by_test_id(page, "plan.cost.summary")).to_contain_text("Blueprints bought")
    expect(by_test_id(page, "plan.cost.summary")).to_contain_text("1.5")

    by_test_id(page, "plan.tabs.blueprints").click()
    by_test_id(page, f"plan.blueprint.{RIFTER_BP}.buy").click()
    by_test_id(page, f"plan.blueprint.{RIFTER_BP}.unbuy").click()
    expect(row).not_to_contain_text("bought")


def test_minerals_as_compressed_ore(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("ore"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.ore.toggle").click()
    expect(by_test_id(page, "plan.ore.summary")).to_contain_text("vs minerals")
    trit = by_test_id(page, f"plan.ore.mineral.{TRITANIUM}")
    expect(trit).to_contain_text("Tritanium")

    def cell(n):
        return int(trit.locator("td").nth(n).inner_text().replace(",", ""))

    assert cell(2) >= cell(1) > 0  # made covers what is needed
    expect(page.locator('[data-testid^="plan.ore.line."]').first).to_be_visible()
    expect(by_test_id(page, "plan.ore.copy-all")).to_be_enabled()
    # Tritanium is 0.01 m3 a unit; compressed ore is far smaller per mineral.
    expect(by_test_id(page, "plan.ore.volume")).to_contain_text("m³")
    expect(by_test_id(page, "plan.ore.mineral-volume")).to_contain_text("m³")
    expect(by_test_id(page, "plan.ore.all-volume")).to_contain_text("m³")
    # Changing the amount built works the mix out again.
    before = cell(1)
    qty = by_test_id(page, f"plan.line.{RIFTER}.qty")
    qty.fill("2")
    qty.press("Enter")
    expect(trit.locator("td").nth(1)).not_to_have_text(f"{before:,}")
    assert cell(1) > before
    # Refresh prices asks Jita again and keeps the mix shown until it answers.
    if by_test_id(page, "plan.ore.refresh").count():
        by_test_id(page, "plan.ore.refresh").click()
        expect(by_test_id(page, "plan.ore.refresh")).to_have_text("Refresh prices")
        expect(by_test_id(page, "plan.ore.priced-at")).to_contain_text("priced")
    # Jita 4-4 sell orders by default (the CCP average if ESI cannot be reached); switchable.
    expect(by_test_id(page, "plan.ore.price-note")).to_contain_text("Prices:")
    by_test_id(page, "plan.ore.prices").select_option("average")
    expect(by_test_id(page, "plan.ore.price-note")).to_contain_text("CCP average price")
    # Adding moon ore to the choice recomputes; Tritanium is still covered.
    by_test_id(page, "plan.ore.class.moon").check()
    expect(by_test_id(page, "plan.ore.class.moon")).to_be_checked()
    expect(trit).to_contain_text("Tritanium")


def test_prices_switch_between_jita_and_average(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("prices"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    expect(by_test_id(page, "plan.prices")).to_have_value("jita")
    by_test_id(page, "plan.tabs.cost").click()
    expect(by_test_id(page, "plan.cost.prices")).to_contain_text("Prices:")
    by_test_id(page, "plan.prices").select_option("average")
    expect(by_test_id(page, "plan.cost.prices")).to_contain_text("CCP average prices")
    page.reload()  # remembered in this browser
    expect(by_test_id(page, "plan.prices")).to_have_value("average")
