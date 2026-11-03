from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import crypto, services, sso, tokens, views
from apps.accounts.models import EsiToken, EveCharacter, User

from .conftest import ALT_ID, MAIN_ID

pytestmark = pytest.mark.django_db

INDUSTRY_SCOPES = ("publicData", "esi-skills.read_skills.v1")


@pytest.fixture
def sso_ok(monkeypatch, make_token, rsa_keys):
    """Fake SSO: code exchange returns tokens for `state['character_id']`."""
    state = {"character_id": MAIN_ID, "name": "Spud", "owner": "owner-1", "scopes": ("publicData",)}

    def exchange(**kwargs):
        access = make_token(
            character_id=state["character_id"],
            name=state["name"],
            owner=state["owner"],
            scp=state["scopes"],
        )
        return {"access_token": access, "refresh_token": "refresh-1", "expires_in": 1199}

    real_validate = sso.validate_access_token
    monkeypatch.setattr(sso, "exchange_code", exchange)
    monkeypatch.setattr(sso, "validate_access_token", lambda t: real_validate(t, key=rsa_keys[1]))
    monkeypatch.setattr(services, "fetch_affiliation", lambda cid: {"corporation_id": 98000001})
    monkeypatch.setattr(sso, "build_authorize_url", lambda **kw: "https://sso.test/authorize")
    return state


def start(client, mode=None):
    resp = client.get("/auth/login", {"mode": mode} if mode else {})
    assert resp.status_code == 302
    return client.session["sso"]["state"]


def test_first_login_creates_account_with_main(client, sso_ok):
    state = start(client)
    resp = client.get("/auth/callback", {"state": state, "code": "c"})
    assert resp.status_code == 302
    user = User.objects.get()
    assert user.main_character_id == MAIN_ID and user.display_name == "Spud"
    assert not EsiToken.objects.exists()  # login stores no token


def test_login_requests_only_login_scopes(client, sso_ok, monkeypatch, settings):
    seen = {}
    monkeypatch.setattr(sso, "build_authorize_url", lambda **kw: seen.update(kw) or "https://x")
    client.get("/auth/login")
    assert seen["scopes"] == settings.EVE_LOGIN_SCOPES
    client.get("/auth/dev-login", {"character_id": MAIN_ID})
    client.get("/auth/login", {"mode": "link"})
    assert seen["scopes"] == settings.EVE_CHARACTER_SCOPES


def test_alt_login_logs_into_the_same_account(client, sso_ok, login_as):
    login_as()
    sso_ok.update(character_id=ALT_ID, name="Alt", scopes=INDUSTRY_SCOPES)
    client.get("/auth/callback", {"state": start(client, "link"), "code": "c"})
    client.post("/auth/logout")
    client.get("/auth/callback", {"state": start(client), "code": "c"})
    assert client.get("/api/me").json()["user_id"] == User.objects.get().pk


def test_link_stores_encrypted_token(client, sso_ok, login_as):
    login_as()
    sso_ok.update(character_id=ALT_ID, name="Alt", scopes=INDUSTRY_SCOPES)
    resp = client.get("/auth/callback", {"state": start(client, "link"), "code": "c"})
    assert resp.status_code == 302
    token = EsiToken.objects.get(character_id=ALT_ID)
    assert token.refresh_token != "refresh-1"
    assert crypto.decrypt(token.refresh_token) == "refresh-1"
    assert token.scopes == sorted(INDUSTRY_SCOPES)
    assert EveCharacter.objects.get(pk=ALT_ID).user == User.objects.get()


def test_link_requires_login(client, sso_ok):
    resp = client.get("/auth/login", {"mode": "link"})
    assert resp.status_code == 302 and "/auth/login?next=" in resp["Location"]


def test_link_refuses_another_accounts_character(client, sso_ok, login_as):
    login_as(ALT_ID, "Alt")
    client.post("/auth/logout")
    login_as()
    sso_ok.update(character_id=ALT_ID, name="Alt", owner="dev-owner")  # same owner as dev-login
    resp = client.get("/auth/callback", {"state": start(client, "link"), "code": "c"})
    assert resp.status_code == 409


def test_state_mismatch_rejected(client, sso_ok):
    start(client)
    assert client.get("/auth/callback", {"state": "nope", "code": "c"}).status_code == 400


def test_owner_change_detaches_character_and_drops_token(make_character):
    char = make_character(owner="a")
    user = services.ensure_user(char)
    services.store_tokens(char, {"access_token": "x", "refresh_token": "y"}, ("publicData",))
    identity = sso.SsoIdentity(MAIN_ID, "Spud", "b", ("publicData",))
    char = services.upsert_character(identity)
    assert char.user is None and not EsiToken.objects.exists()
    user.refresh_from_db()
    assert user.main_character_id is None


def test_me_lists_characters_and_scopes(client, login_as, settings):
    login_as()
    char = EveCharacter.objects.get(pk=MAIN_ID)
    services.store_tokens(char, {"access_token": "x", "refresh_token": "y"}, ("publicData",))
    body = client.get("/api/me").json()
    assert body["authenticated"] and body["display_name"] == "Spud"
    (c,) = body["characters"]
    assert c["is_main"] and c["esi"]["scopes"] == ["publicData"]
    assert set(c["esi"]["missing_scopes"]) == set(settings.EVE_CHARACTER_SCOPES) - {"publicData"}


def test_me_anonymous(client):
    assert client.get("/api/me").json()["authenticated"] is False


def test_unlink_and_main(client, login_as):
    login_as()
    user = User.objects.get()
    alt = services.upsert_character(sso.SsoIdentity(ALT_ID, "Alt", "o", ()))
    services.link_character(user, alt)
    assert client.delete(f"/api/characters/{MAIN_ID}").status_code == 409  # main
    resp = client.post(f"/api/characters/{ALT_ID}/main")
    assert [c["is_main"] for c in resp.json()] == [True, False]  # Alt, Spud
    assert client.delete(f"/api/characters/{MAIN_ID}").status_code == 200
    assert EveCharacter.objects.get(pk=MAIN_ID).user is None


def test_cannot_touch_other_accounts_characters(client, login_as):
    login_as(ALT_ID, "Alt")
    client.post("/auth/logout")
    login_as()
    assert client.delete(f"/api/characters/{ALT_ID}").status_code == 404


# --- tokens ---------------------------------------------------------------------


@pytest.fixture
def linked(make_character):
    char = make_character()
    services.ensure_user(char)
    services.store_tokens(
        char, {"access_token": "old", "refresh_token": "r1", "expires_in": 1200}, INDUSTRY_SCOPES
    )
    return char


def test_fresh_token_returned_without_refresh(linked, monkeypatch):
    monkeypatch.setattr(sso, "refresh_tokens", lambda r: pytest.fail("should not refresh"))
    assert tokens.access_token(linked, "esi-skills.read_skills.v1") == "old"


def test_expiring_token_refreshed_and_rotated(linked, monkeypatch, make_token, rsa_keys):
    EsiToken.objects.filter(pk=MAIN_ID).update(
        access_expires_at=timezone.now() + timedelta(seconds=30)
    )
    new_access = make_token(scp=INDUSTRY_SCOPES)
    calls = []

    def refresh(r):
        calls.append(r)
        return {"access_token": new_access, "refresh_token": "r2", "expires_in": 1199}

    real_validate = sso.validate_access_token
    monkeypatch.setattr(sso, "refresh_tokens", refresh)
    monkeypatch.setattr(sso, "validate_access_token", lambda t: real_validate(t, key=rsa_keys[1]))
    assert tokens.access_token(MAIN_ID) == new_access
    assert calls == ["r1"]
    token = EsiToken.objects.get(pk=MAIN_ID)
    assert crypto.decrypt(token.refresh_token) == "r2"
    assert token.access_expires_at > timezone.now() + timedelta(seconds=1000)


def test_rejected_refresh_marks_token(linked, monkeypatch):
    EsiToken.objects.filter(pk=MAIN_ID).update(access_expires_at=timezone.now())

    def reject(r):
        raise sso.SsoTokenRejected("refresh token rejected: invalid_grant")

    monkeypatch.setattr(sso, "refresh_tokens", reject)
    with pytest.raises(tokens.TokenUnavailable):
        tokens.access_token(MAIN_ID)
    token = EsiToken.objects.get(pk=MAIN_ID)
    assert token.refresh_failed_at is not None and "invalid_grant" in token.refresh_error
    with pytest.raises(tokens.TokenUnavailable, match="link it again"):
        tokens.access_token(MAIN_ID)


def test_missing_scope_is_unavailable(linked):
    with pytest.raises(tokens.TokenUnavailable, match="lacks scopes"):
        tokens.access_token(MAIN_ID, "esi-assets.read_corporation_assets.v1")


def test_unlinked_character_has_no_token(make_character):
    make_character()
    with pytest.raises(tokens.TokenUnavailable, match="no ESI token"):
        tokens.access_token(MAIN_ID)


def test_derived_key_changes_with_secret_key(settings):
    encrypted = crypto.encrypt("secret")
    settings.SECRET_KEY = "another-secret"
    with pytest.raises(crypto.TokenDecryptError):
        crypto.decrypt(encrypted)


def test_views_module_has_no_admission_gate():
    # Anyone with an EVE account may sign up (docs/redesign.md: "for me and anyone").
    assert not hasattr(views, "_denied")
