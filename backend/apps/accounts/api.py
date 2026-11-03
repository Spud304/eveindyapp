from datetime import datetime
from typing import cast

from django.conf import settings
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError

from . import services
from .models import EsiToken, EveCharacter, User

router = Router(tags=["accounts"])


class TokenOut(Schema):
    scopes: list[str]
    missing_scopes: list[str]
    last_refreshed_at: datetime | None
    rejected: bool
    error: str


class CharacterOut(Schema):
    character_id: int
    name: str
    corporation_id: int | None
    alliance_id: int | None
    is_main: bool
    esi: TokenOut | None


class MeOut(Schema):
    authenticated: bool
    user_id: int | None = None
    display_name: str | None = None
    characters: list[CharacterOut] = []
    sso_configured: bool = True
    version: str = ""


def _token_out(token: EsiToken | None) -> dict | None:
    if token is None:
        return None
    return {
        "scopes": token.scopes,
        "missing_scopes": sorted(set(settings.EVE_CHARACTER_SCOPES) - set(token.scopes)),
        "last_refreshed_at": token.last_refreshed_at,
        "rejected": token.refresh_failed_at is not None,
        "error": token.refresh_error,
    }


def _characters(user: User) -> list[dict]:
    tokens = {t.character_id: t for t in EsiToken.objects.filter(character__user=user)}
    return [
        {
            "character_id": c.character_id,
            "name": c.name,
            "corporation_id": c.corporation_id,
            "alliance_id": c.alliance_id,
            "is_main": c.character_id == user.main_character_id,
            "esi": _token_out(tokens.get(c.character_id)),
        }
        for c in user.characters.order_by("name")
    ]


@router.get("/me", auth=None, response=MeOut)
def me(request: HttpRequest):
    base = {"sso_configured": bool(settings.EVE_CLIENT_ID), "version": settings.APP_VERSION}
    if not request.user.is_authenticated:
        return {"authenticated": False, **base}
    user = cast(User, request.user)
    return {
        "authenticated": True,
        "user_id": user.pk,
        "display_name": user.display_name,
        "characters": _characters(user),
        **base,
    }


def _own_character(request: HttpRequest, character_id: int) -> tuple[User, EveCharacter]:
    user = cast(User, request.user)
    return user, get_object_or_404(EveCharacter, character_id=character_id, user=user)


@router.post("/characters/{character_id}/main", response=list[CharacterOut])
def set_main(request: HttpRequest, character_id: int):
    user, character = _own_character(request, character_id)
    services.set_main_character(user, character)
    return _characters(user)


@router.delete("/characters/{character_id}", response=list[CharacterOut])
def unlink(request: HttpRequest, character_id: int):
    user, character = _own_character(request, character_id)
    try:
        services.unlink_character(user, character)
    except services.LinkError as exc:
        raise HttpError(409, str(exc)) from exc
    return _characters(user)
