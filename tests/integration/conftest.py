"""Fixtures for Playwright integration tests: live server + authenticated browser."""

import threading
import pytest
from werkzeug.serving import make_server
from flask.sessions import SecureCookieSessionInterface

from tests.conftest import create_test_app
from src.models.models import db, User
from datetime import datetime, timezone, timedelta


@pytest.fixture(scope="session")
def live_app():
    """Session-scoped Flask app for integration tests."""
    return create_test_app()


@pytest.fixture(scope="session")
def base_url(live_app):
    """Run Flask app in a background thread on port 5099, return base URL."""
    server = make_server("127.0.0.1", 5099, live_app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:5099"
    server.shutdown()


@pytest.fixture()
def _integration_cleanup(live_app):
    """Reset DB session after each integration test."""
    yield
    with live_app.app_context():
        db.session.remove()


@pytest.fixture()
def page(browser, base_url, _integration_cleanup):
    """Unauthenticated Playwright page."""
    ctx = browser.new_context()
    p = ctx.new_page()
    yield p
    ctx.close()


@pytest.fixture()
def auth_page(live_app, browser, base_url, _integration_cleanup):
    """Playwright page with an authenticated session cookie."""
    # Create a test user + get a valid session cookie via Flask test client
    with live_app.app_context():
        user = User(
            character_id=12345678,
            character_name="TestPilot",
            character_owner_hash="testhash",
            main_character_id=12345678,
            access_token="test-access-token",
            access_token_expires=datetime.now(timezone.utc) + timedelta(hours=1),
            refresh_token="test-refresh-token",
        )
        db.session.merge(user)
        db.session.commit()

    # Generate a valid session cookie using Flask's session serializer
    # (shares the same secret key as the live server)
    si = SecureCookieSessionInterface()
    serializer = si.get_signing_serializer(live_app)
    cookie = serializer.dumps({"_user_id": "12345678"})

    ctx = browser.new_context()
    ctx.add_cookies(
        [
            {
                "name": "session",
                "value": cookie,
                "domain": "127.0.0.1",
                "path": "/",
            }
        ]
    )
    p = ctx.new_page()
    yield p
    ctx.close()
