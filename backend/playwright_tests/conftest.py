"""Browser tests against the running dev servers (Django on :8000, Vite on :5050).

Run: `uv run pytest playwright_tests --browser chromium` from backend/.

Each test logs in through /auth/dev-login as a character from the reserved range
900000001-900000099 (`manage.py playwright_cleanup` deletes everything those accounts own
before the run). Never point dev-login at a real character: a changed owner hash counts as a
transfer and deletes that character's ESI token.

The dev database must hold an imported SDE (Rifter, Azbel, D-JVGJ, rigs are looked up by name).
"""

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from playwright.sync_api import (
    APIRequestContext,
    APIResponse,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

BASE_URL = os.environ.get("PLAYWRIGHT_BASE_URL", "http://localhost:5050")
BACKEND_DIR = Path(__file__).resolve().parent.parent
FIRST_ID = 900_000_001

# Real SDE ids the specs rely on (checked by the session fixture).
RIFTER = 587
TRITANIUM = 34
AZBEL = 35826
D_JVGJ = 30001761

_next_id = FIRST_ID


@dataclass
class Session:
    page: Page
    context: BrowserContext
    api: APIRequestContext
    character_id: int
    name: str

    def call(self, method: str, url: str, data=None) -> APIResponse:
        """Unsafe methods need the CSRF cookie echoed as a header."""
        token = next((c["value"] for c in self.context.cookies() if c["name"] == "csrftoken"), "")
        resp = self.api.fetch(url, method=method, data=data, headers={"X-CSRFToken": token})
        assert resp.ok, f"{method} {url}: {resp.status} {resp.text()[:300]}"
        return resp

    def json(self, url: str):
        return self.call("GET", url).json()

    def add_station(self, name: str = "PW Azbel", **body) -> dict:
        payload = {
            "name": name,
            "system_id": D_JVGJ,
            "structure_type_id": AZBEL,
            "rig_type_ids": [],
            "activities": ["manufacturing"],
            "facility_tax": 1.0,
            **body,
        }
        return self.call("POST", "/api/stations", payload).json()

    def add_plan(self, name: str, lines: list[tuple[int, int]], **body) -> dict:
        payload = {"name": name, "lines": [{"type_id": t, "quantity": q} for t, q in lines], **body}
        return self.call("POST", "/api/plans", payload).json()


def uniq(prefix: str) -> str:
    return f"pw {prefix} {int(time.time() * 1000) % 10_000_000:x}"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "base_url": BASE_URL,
        "viewport": {"width": 1600, "height": 1000},
    }


@pytest.fixture(scope="session", autouse=True)
def clean_and_check(playwright: Playwright):
    """Wipe test accounts, then confirm the servers and the SDE are what the specs assume."""
    subprocess.run(
        ["uv", "run", "python", "manage.py", "playwright_cleanup"], cwd=BACKEND_DIR, check=True
    )
    api = playwright.request.new_context(base_url=BASE_URL)
    try:
        health = api.get("/api/health")
        assert health.ok, f"no backend behind {BASE_URL}: start Django on :8000 and `npm run dev`"
        assert health.json()["sde_build"], "no SDE imported in the dev database"
        login = api.get(
            "/auth/dev-login",
            params={"character_id": FIRST_ID, "name": "PW check"},
            max_redirects=0,
        )
        assert login.status == 302, f"dev-login failed ({login.status}); is Django on dev settings?"
        names = {
            t["id"]: t["name"]
            for t in api.get("/api/types", params={"ids": f"{RIFTER},{TRITANIUM},{AZBEL}"}).json()
        }
        assert names == {RIFTER: "Rifter", TRITANIUM: "Tritanium", AZBEL: "Azbel"}, names
    finally:
        api.dispose()


@pytest.fixture
def login(browser: Browser):
    """`login()` opens a fresh context logged in as a new test character; closed at teardown."""
    opened: list[Session] = []

    def _open() -> Session:
        global _next_id
        _next_id += 1
        cid = _next_id
        name = f"PW Pilot {cid - FIRST_ID}"
        context = browser.new_context(base_url=BASE_URL, viewport={"width": 1600, "height": 1000})
        resp = context.request.get(
            "/auth/dev-login", params={"character_id": cid, "name": name}, max_redirects=0
        )
        assert resp.status == 302, f"dev-login failed: {resp.status} {resp.text()[:200]}"
        session = Session(context.new_page(), context, context.request, cid, name)
        opened.append(session)
        return session

    yield _open
    for s in opened:
        s.context.close()


def by_test_id(page: Page, test_id: str):
    return page.locator(f'[data-testid="{test_id}"]')


def pick(page: Page, test_id: str, query: str, option: str) -> None:
    """Type into a SearchPicker and choose the result whose text is exactly `option`."""
    box = by_test_id(page, test_id)
    box.fill(query)
    results = by_test_id(page, f"{test_id}.results")
    results.get_by_text(option, exact=True).click()
