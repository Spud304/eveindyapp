"""EVE SSO v2: authorization-code flow with PKCE and offline JWT validation."""

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from django.conf import settings
from django.core.cache import cache
from jwt import PyJWKClient

log = logging.getLogger(__name__)

DISCOVERY_CACHE_KEY = "sso:discovery"
CLOCK_SKEW_SECONDS = 60  # leeway for iat / exp when validating tokens
_jwk_clients: dict[str, PyJWKClient] = {}


class SsoError(Exception):
    pass


def _headers() -> dict[str, str]:
    """The same User-Agent as ESI calls, so CCP can tell this app's SSO traffic apart."""
    return {"User-Agent": settings.ESI_USER_AGENT}


@dataclass(frozen=True)
class SsoIdentity:
    character_id: int
    name: str
    owner_hash: str
    scopes: tuple[str, ...]


def discovery() -> dict:
    doc = cache.get(DISCOVERY_CACHE_KEY)
    if doc:
        return doc
    try:
        resp = httpx.get(settings.EVE_SSO_DISCOVERY_URL, timeout=10, headers=_headers())
        resp.raise_for_status()
        doc = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SsoError(f"EVE SSO is unreachable: {exc}") from exc
    needed = ("authorization_endpoint", "token_endpoint", "jwks_uri")
    if not isinstance(doc, dict) or any(k not in doc for k in needed):
        raise SsoError("EVE SSO discovery document is missing endpoints")
    cache.set(DISCOVERY_CACHE_KEY, doc, 24 * 3600)
    return doc


def make_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(
    *, state: str, code_challenge: str, redirect_uri: str, scopes: list[str]
) -> str:
    params = {
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "client_id": settings.EVE_CLIENT_ID,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{discovery()['authorization_endpoint']}?{urlencode(params)}"


def exchange_code(*, code: str, code_verifier: str, redirect_uri: str) -> dict:
    try:
        resp = httpx.post(
            discovery()["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
            auth=(settings.EVE_CLIENT_ID, settings.EVE_CLIENT_SECRET),
            timeout=15,
            headers=_headers(),
        )
    except httpx.HTTPError as exc:
        raise SsoError(f"token exchange failed: {exc}") from exc
    if resp.status_code != 200:
        log.warning("sso token exchange failed: %s %s", resp.status_code, resp.text[:300])
        raise SsoError("token exchange failed")
    try:
        tokens = resp.json()
    except ValueError as exc:
        raise SsoError("token exchange answered with a non-JSON body") from exc
    if not isinstance(tokens, dict) or "access_token" not in tokens:
        raise SsoError("token exchange answered without an access token")
    return tokens


class SsoTokenRejected(SsoError):
    """SSO refused the refresh token (revoked, expired, or the character was transferred)."""


def refresh_tokens(refresh_token: str) -> dict:
    """Trade a refresh token for a new access token (and possibly a new refresh token)."""
    try:
        resp = httpx.post(
            discovery()["token_endpoint"],
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(settings.EVE_CLIENT_ID, settings.EVE_CLIENT_SECRET),
            timeout=15,
            headers=_headers(),
        )
    except httpx.HTTPError as exc:
        raise SsoError(f"token refresh failed: {exc}") from exc
    if resp.status_code in (400, 401):
        try:
            error = resp.json().get("error", "")
        except ValueError:
            error = ""
        # Only these say the refresh token itself is bad. Any other 400/401 (e.g.
        # `invalid_client` from a wrong EVE_CLIENT_SECRET) is this app's problem, and marking
        # every character's token as rejected would force relinking them all.
        if error in ("invalid_grant", "invalid_token"):
            raise SsoTokenRejected(f"refresh token rejected: {error}")
    if resp.status_code != 200:
        log.warning("sso token refresh failed: %s %s", resp.status_code, resp.text[:300])
        raise SsoError(f"token refresh failed: HTTP {resp.status_code}")
    try:
        tokens = resp.json()
    except ValueError as exc:
        raise SsoError("token refresh answered with a non-JSON body") from exc
    if not isinstance(tokens, dict) or "access_token" not in tokens:
        raise SsoError("token refresh answered without an access token")
    return tokens


def _signing_key(token: str):
    jwks_uri = discovery()["jwks_uri"]
    client = _jwk_clients.get(jwks_uri)
    if client is None:
        client = PyJWKClient(jwks_uri, cache_keys=True, lifespan=24 * 3600, headers=_headers())
        _jwk_clients[jwks_uri] = client
    return client.get_signing_key_from_jwt(token).key


def validate_access_token(token: str, *, key=None) -> SsoIdentity:
    """Validate an EVE SSO JWT offline. `key` lets tests inject a public key instead of the JWKS."""
    try:
        if key is None:
            key = _signing_key(token)  # PyJWKClientError is a PyJWTError
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=[settings.EVE_CLIENT_ID, "EVE Online"],
            options={"require": ["exp", "sub", "iss"]},
            # A clock a little behind CCP's (Docker Desktop's VM after a restart or sleep) makes
            # a just-issued token look "not yet valid (iat)".
            leeway=CLOCK_SKEW_SECONDS,
        )
    except jwt.PyJWTError as exc:
        raise SsoError(f"invalid token: {exc}") from exc
    if claims.get("iss") not in settings.EVE_SSO_ISSUERS:
        raise SsoError(f"unexpected issuer {claims.get('iss')!r}")
    sub = str(claims.get("sub", ""))
    prefix = "CHARACTER:EVE:"
    if not sub.startswith(prefix):
        raise SsoError(f"unexpected subject {sub!r}")
    try:
        character_id = int(sub[len(prefix) :])
    except ValueError as exc:
        raise SsoError(f"unexpected subject {sub!r}") from exc
    scp = claims.get("scp", [])
    if isinstance(scp, str):
        scp = [scp]
    return SsoIdentity(
        character_id=character_id,
        name=str(claims.get("name", "")),
        owner_hash=str(claims.get("owner", "")),
        scopes=tuple(scp),
    )
