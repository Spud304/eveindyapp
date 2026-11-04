from playwright.sync_api import expect

from .conftest import RIFTER, by_test_id, make_job, uniq

RIFTER_BP = 691


def test_active_plan_links_new_jobs_and_shows_progress(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("progress"), [(RIFTER, 3)])
    s.call("POST", f"/api/plans/{plan['id']}/activate")
    job_id = make_job(s.character_id, RIFTER_BP, RIFTER, runs=1)  # started after activation
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.tabs.progress").click()

    row = by_test_id(page, f"plan.progress.row.{RIFTER_BP}.manufacturing")
    expect(row.locator("td").nth(3)).to_have_text("2")  # to start
    expect(row.locator("td").nth(4)).to_have_text("1")  # running
    expect(by_test_id(page, f"plan.progress.job.{job_id}")).to_contain_text("Rifter")

    # The shopping list only covers the two Rifters still to build.
    by_test_id(page, "plan.tabs.blueprints").click()
    expect(by_test_id(page, f"plan.blueprint.{RIFTER_BP}").locator("td").nth(1)).to_have_text("2")


def test_unlink_then_link_by_hand(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("relink"), [(RIFTER, 3)])
    s.call("POST", f"/api/plans/{plan['id']}/activate")
    job_id = make_job(s.character_id, RIFTER_BP, RIFTER, runs=1)
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.tabs.progress").click()

    by_test_id(page, f"plan.progress.unlink.{job_id}").click()
    expect(page.get_by_test_id("toast").last).to_have_text("Job unlinked")
    expect(by_test_id(page, f"plan.progress.candidate.{job_id}")).to_be_visible()
    expect(
        by_test_id(page, f"plan.progress.row.{RIFTER_BP}.manufacturing").locator("td").nth(3)
    ).to_have_text("3")

    page.reload()  # an unlinked job is not matched again
    by_test_id(page, "plan.tabs.progress").click()
    expect(by_test_id(page, f"plan.progress.candidate.{job_id}")).to_be_visible()

    by_test_id(page, f"plan.progress.link.{job_id}").click()
    linked = by_test_id(page, f"plan.progress.job.{job_id}")
    expect(linked).to_contain_text("manual")
    expect(
        by_test_id(page, f"plan.progress.row.{RIFTER_BP}.manufacturing").locator("td").nth(3)
    ).to_have_text("2")


def test_jobs_before_activation_wait_for_a_manual_link(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("early"), [(RIFTER, 1)])
    job_id = make_job(s.character_id, RIFTER_BP, RIFTER, runs=1, minutes_ago=30)
    s.call("POST", f"/api/plans/{plan['id']}/activate")
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.tabs.progress").click()
    expect(by_test_id(page, "plan.progress.jobs")).to_contain_text("No jobs linked yet")
    expect(by_test_id(page, f"plan.progress.candidate.{job_id}")).to_be_visible()


def test_inactive_plan_says_so(login):
    s = login()
    plan = s.add_plan(uniq("inactive"), [(RIFTER, 1)])
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.tabs.progress").click()
    expect(by_test_id(page, "plan.progress.inactive")).to_be_visible()


def test_over_plan_runs_are_flagged(login):
    s = login()
    s.add_station()
    plan = s.add_plan(uniq("over"), [(RIFTER, 2)])
    s.call("POST", f"/api/plans/{plan['id']}/activate")
    make_job(s.character_id, RIFTER_BP, RIFTER, runs=5)
    page = s.page
    page.goto(f"/plans/{plan['id']}")
    by_test_id(page, "plan.tabs.progress").click()
    row = by_test_id(page, f"plan.progress.row.{RIFTER_BP}.manufacturing")
    expect(row.locator("td").nth(7)).to_have_text("3")  # over plan
    expect(row).to_contain_text("all started")
