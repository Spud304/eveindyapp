"""SSO login and character linking.

- `/auth/login`: publicData only. Proves who you are and logs you into the account the
  character belongs to (created on first login). Anyone with an EVE account may sign up.
- `/auth/login?mode=link`: signed in; requests the industry scopes and stores the refresh
  token, attaching the character to your account. Use it for your main too.
"""

import logging
import secrets
from typing import cast

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from . import services, sso
from .models import User

log = logging.getLogger(__name__)
BACKEND = "django.contrib.auth.backends.ModelBackend"


def _safe_next(request: HttpRequest, candidate: str | None) -> str:
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return "/"


def _callback_uri(request: HttpRequest) -> str:
    return settings.EVE_CALLBACK_URL or request.build_absolute_uri(reverse("accounts:callback"))


def _error(message: str, status: int) -> HttpResponse:
    return HttpResponse(f"EVE SSO: {message}", status=status, content_type="text/plain")


@require_http_methods(["GET"])
def login_view(request: HttpRequest) -> HttpResponse:
    if not settings.EVE_CLIENT_ID:
        return _error("not configured: set EVE_CLIENT_ID and EVE_CLIENT_SECRET.", 503)
    mode = "link" if request.GET.get("mode") == "link" else "login"
    if mode == "link" and not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")
    verifier, challenge = sso.make_pkce()
    state = secrets.token_urlsafe(24)
    request.session["sso"] = {
        "state": state,
        "verifier": verifier,
        "next": _safe_next(request, request.GET.get("next")),
        "mode": mode,
    }
    scopes = settings.EVE_CHARACTER_SCOPES if mode == "link" else settings.EVE_LOGIN_SCOPES
    try:
        url = sso.build_authorize_url(
            state=state,
            code_challenge=challenge,
            redirect_uri=_callback_uri(request),
            scopes=scopes,
        )
    except sso.SsoError as exc:
        log.warning("sso failure: %s", exc)
        return _error(str(exc), 503)
    return redirect(url)


@require_http_methods(["GET"])
def callback_view(request: HttpRequest) -> HttpResponse:
    pending = request.session.pop("sso", None)
    if not pending or request.GET.get("state") != pending.get("state"):
        return HttpResponseBadRequest("login state mismatch; start again")
    if request.GET.get("error"):
        return _error(request.GET.get("error_description") or request.GET["error"], 400)
    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("missing code")
    try:
        tokens = sso.exchange_code(
            code=code, code_verifier=pending["verifier"], redirect_uri=_callback_uri(request)
        )
        identity = sso.validate_access_token(tokens["access_token"])
    except sso.SsoError as exc:
        log.warning("sso failure: %s", exc)
        return _error(str(exc), 400)

    character = services.upsert_character(
        identity, services.fetch_affiliation(identity.character_id)
    )
    next_url = pending.get("next") or "/"

    if pending.get("mode") == "link":
        if not request.user.is_authenticated:
            return _error("sign in before linking a character", 403)
        try:
            services.link_character(cast(User, request.user), character)
        except services.LinkError as exc:
            return _error(str(exc), 409)
        if not tokens.get("refresh_token"):
            return _error("SSO returned no refresh token; link the character again", 400)
        services.store_tokens(character, tokens, identity.scopes)
        return redirect(next_url)

    user = services.ensure_user(character)
    auth_login(request, user, backend=BACKEND)
    return redirect(next_url)


@require_http_methods(["POST"])  # a GET would let any page log the user out
def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    return redirect("/")


@require_http_methods(["GET"])
def dev_login_view(request: HttpRequest) -> HttpResponse:
    """Local-only shortcut: /auth/dev-login?character_id=1&name=Test[&corporation_id=..]."""
    if not settings.DEV_LOGIN_ENABLED:
        raise Http404
    try:
        character_id = int(request.GET["character_id"])
    except (KeyError, ValueError):
        return HttpResponseBadRequest("character_id required")
    identity = sso.SsoIdentity(
        character_id=character_id,
        name=request.GET.get("name", f"Dev Character {character_id}"),
        owner_hash=request.GET.get("owner", "dev-owner"),
        scopes=("publicData",),
    )
    try:
        affiliation = {
            key: int(request.GET[key]) if request.GET.get(key) else None
            for key in ("corporation_id", "alliance_id")
        }
    except ValueError:
        return HttpResponseBadRequest("corporation_id and alliance_id must be numbers")
    character = services.upsert_character(identity, affiliation)
    auth_login(request, services.ensure_user(character), backend=BACKEND)
    return redirect(_safe_next(request, request.GET.get("next")))
