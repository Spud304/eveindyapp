"""Valid access tokens on demand.

Every ESI call asks for a token here, and the token is refreshed synchronously when it is
within `TOKEN_REFRESH_MARGIN_SECONDS` of expiry. There is no refresh schedule to fall behind,
which fixes the old app's bug 6 (refresh window shorter than the beat interval).
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import crypto, sso
from .models import EsiToken, EveCharacter

log = logging.getLogger(__name__)


class TokenUnavailable(Exception):
    """No usable token: never linked, missing scopes, or rejected by SSO."""


class TokenRefreshFailed(TokenUnavailable):
    """The refresh did not complete (SSO down, a bad answer, a client credential problem).
    The token itself is kept; the next attempt tries again."""


def access_token(character: EveCharacter | int, *scopes: str) -> str:
    character_id = character if isinstance(character, int) else character.character_id
    with transaction.atomic():
        # Row lock: two workers refreshing at once would each spend the same refresh token.
        token = EsiToken.objects.select_for_update().filter(character_id=character_id).first()
        if token is None:
            raise TokenUnavailable(f"character {character_id} has no ESI token; link it first")
        if token.refresh_failed_at is not None:
            raise TokenUnavailable(
                f"character {character_id} token was rejected ({token.refresh_error}); link it again"
            )
        if scopes and not token.has_scopes(*scopes):
            missing = sorted(set(scopes) - set(token.scopes))
            raise TokenUnavailable(f"character {character_id} token lacks scopes {missing}")

        margin = timedelta(seconds=settings.TOKEN_REFRESH_MARGIN_SECONDS)
        fresh = (
            token.access_token
            and token.access_expires_at is not None
            and token.access_expires_at - margin > timezone.now()
        )
        if fresh:
            return crypto.decrypt(token.access_token)
        try:
            return _refresh(token)
        except sso.SsoTokenRejected as exc:
            # Saved inside the transaction; the error is raised after it commits so the
            # rejection is not rolled back with it.
            token.refresh_failed_at = timezone.now()
            token.refresh_error = str(exc)[:300]
            token.access_token = ""
            token.save(update_fields=["refresh_failed_at", "refresh_error", "access_token"])
            log.warning("token for %s rejected: %s", token.character_id, exc)
            rejected = exc
        except sso.SsoError as exc:
            log.warning("token refresh for %s failed: %s", token.character_id, exc)
            raise TokenRefreshFailed(
                f"token refresh failed; the next sync tries again ({exc})"
            ) from exc
    raise TokenUnavailable(f"character {character_id} token rejected; link it again") from rejected


def _refresh(token: EsiToken) -> str:
    tokens = sso.refresh_tokens(crypto.decrypt(token.refresh_token))

    identity = sso.validate_access_token(tokens["access_token"])
    if identity.character_id != token.character_id:
        raise sso.SsoError("refreshed token belongs to a different character")
    now = timezone.now()
    token.access_token = crypto.encrypt(tokens["access_token"])
    token.access_expires_at = now + timedelta(seconds=int(tokens.get("expires_in") or 0))
    if tokens.get("refresh_token"):
        token.refresh_token = crypto.encrypt(tokens["refresh_token"])
    token.scopes = sorted(identity.scopes)
    token.last_refreshed_at = now
    token.save()
    return tokens["access_token"]
