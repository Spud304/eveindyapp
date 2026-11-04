import base64
import hashlib

import jwt
import pytest

from apps.accounts import sso


def test_valid_token_yields_identity(make_token, rsa_keys):
    identity = sso.validate_access_token(
        make_token(character_id=123, name="Spud", owner="abc"), key=rsa_keys[1]
    )
    assert identity.character_id == 123 and identity.name == "Spud" and identity.owner_hash == "abc"
    assert identity.scopes == ("publicData",)


@pytest.mark.parametrize("iss", ["https://login.eveonline.com", "login.eveonline.com"])
def test_both_issuer_forms_accepted(make_token, rsa_keys, iss):
    assert sso.validate_access_token(make_token(iss=iss), key=rsa_keys[1]).character_id == 90000001


def test_unknown_issuer_rejected(make_token, rsa_keys):
    with pytest.raises(sso.SsoError):
        sso.validate_access_token(make_token(iss="https://evil.example"), key=rsa_keys[1])


def test_wrong_audience_rejected(make_token, rsa_keys):
    with pytest.raises(sso.SsoError):
        sso.validate_access_token(make_token(aud=["someone-else"]), key=rsa_keys[1])


def test_expired_token_rejected(make_token, rsa_keys):
    with pytest.raises(sso.SsoError):
        sso.validate_access_token(make_token(exp_offset=-30), key=rsa_keys[1])


def test_single_scope_string_normalised(make_token, rsa_keys):
    assert sso.validate_access_token(make_token(scp="publicData"), key=rsa_keys[1]).scopes == (
        "publicData",
    )


def test_non_character_subject_rejected(make_token, rsa_keys):
    claims = jwt.decode(make_token(), options={"verify_signature": False})
    bad = jwt.encode({**claims, "sub": "CORP:EVE:1"}, rsa_keys[0], algorithm="RS256")
    with pytest.raises(sso.SsoError):
        sso.validate_access_token(bad, key=rsa_keys[1])


def test_pkce_pair_is_s256():
    verifier, challenge = sso.make_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode() and "=" not in verifier


def test_network_failures_become_sso_errors(monkeypatch, settings):
    import httpx
    from django.core.cache import cache

    cache.clear()

    def down(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(sso.httpx, "get", down)
    with pytest.raises(sso.SsoError):
        sso.discovery()
    cache.set(
        sso.DISCOVERY_CACHE_KEY,
        {"authorization_endpoint": "a", "token_endpoint": "t", "jwks_uri": "j"},
        60,
    )
    monkeypatch.setattr(sso.httpx, "post", down)
    with pytest.raises(sso.SsoError):
        sso.exchange_code(code="c", code_verifier="v", redirect_uri="r")
    cache.clear()


@pytest.mark.parametrize(
    ("status", "body", "rejected"),
    [
        (400, {"error": "invalid_grant"}, True),
        (401, {"error": "invalid_token"}, True),
        (401, {"error": "invalid_client"}, False),  # this app's secret, not the token
        (401, {}, False),
        (500, {}, False),
    ],
)
def test_only_a_bad_refresh_token_counts_as_rejected(monkeypatch, status, body, rejected):
    import httpx
    from django.core.cache import cache

    cache.set(
        sso.DISCOVERY_CACHE_KEY,
        {
            "authorization_endpoint": "a",
            "token_endpoint": "https://sso.test/token",
            "jwks_uri": "j",
        },
        60,
    )
    monkeypatch.setattr(
        sso.httpx,
        "post",
        lambda *a, **kw: httpx.Response(status, json=body, request=httpx.Request("POST", a[0])),
    )
    with pytest.raises(sso.SsoError) as exc:
        sso.refresh_tokens("r")
    assert isinstance(exc.value, sso.SsoTokenRejected) is rejected
    cache.clear()


@pytest.mark.django_db
def test_login_page_explains_an_unreachable_sso(client, settings, monkeypatch):
    settings.EVE_CLIENT_ID = "client"

    def fail():
        raise sso.SsoError("EVE SSO is unreachable: no route")

    monkeypatch.setattr(sso, "discovery", fail)
    resp = client.get("/auth/login")
    assert resp.status_code == 503 and b"unreachable" in resp.content
