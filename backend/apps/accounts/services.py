"""Character upsert, account creation, character linking and ESI token storage."""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.esi.client import EsiError, get_client

from . import crypto
from .models import EsiToken, EveCharacter, User
from .sso import SsoIdentity

log = logging.getLogger(__name__)


class LinkError(Exception):
    pass


def fetch_affiliation(character_id: int) -> dict | None:
    try:
        data = get_client().character_public(character_id)
    except EsiError as exc:
        log.warning("could not fetch affiliation for %s: %s", character_id, exc)
        return None
    return {"corporation_id": data.get("corporation_id"), "alliance_id": data.get("alliance_id")}


def upsert_character(identity: SsoIdentity, affiliation: dict | None = None) -> EveCharacter:
    """Create or update a character from a validated SSO identity.

    A changed owner hash means the character was sold or transferred: it is detached from its
    previous account and its stored token is dropped.
    """
    now = timezone.now()
    with transaction.atomic():
        char, created = EveCharacter.objects.select_for_update().get_or_create(
            character_id=identity.character_id,
            defaults={"name": identity.name, "owner_hash": identity.owner_hash},
        )
        if not created:
            transferred = (
                identity.owner_hash and char.owner_hash and char.owner_hash != identity.owner_hash
            )
            if transferred:
                previous = char.user
                log.info("character %s changed owner; detaching", char.character_id)
                EsiToken.objects.filter(character=char).delete()
                char.user = None
                if previous is not None and previous.main_character_id == char.character_id:
                    previous.main_character = None
                    previous.save(update_fields=["main_character"])
            if identity.owner_hash:
                char.owner_hash = identity.owner_hash
            if identity.name:
                user = char.user
                if user is not None and user.display_name == char.name != identity.name:
                    user.display_name = identity.name
                    user.save(update_fields=["display_name"])
                char.name = identity.name
        if affiliation:
            char.corporation_id = affiliation.get("corporation_id")
            char.alliance_id = affiliation.get("alliance_id")
            char.affiliation_checked_at = now
        char.last_login_at = now
        char.save()
    return char


def ensure_user(character: EveCharacter) -> User:
    """The account a character logs into; created (with it as main) on first login."""
    if character.user is not None:
        return character.user
    username = f"char:{character.character_id}"
    # After a transfer the previous owner's account still carries this username; it keeps its
    # data under a new one so the new owner can have theirs.
    previous = User.objects.filter(username=username).first()
    if previous is not None:
        previous.username = f"{username}:was:{previous.pk}"
        previous.save(update_fields=["username"])
    user = User.objects.create_user(username=username, display_name=character.name)
    character.user = user
    character.save(update_fields=["user"])
    user.main_character = character
    user.save(update_fields=["main_character"])
    return user


def link_character(user: User, character: EveCharacter) -> EveCharacter:
    if character.user is not None and character.user_id != user.pk:
        raise LinkError("character already belongs to another account")
    character.user = user
    character.save(update_fields=["user"])
    if user.main_character_id is None:
        user.main_character = character
        user.save(update_fields=["main_character"])
    return character


def unlink_character(user: User, character: EveCharacter) -> None:
    if character.user_id != user.pk:
        raise LinkError("character is not on this account")
    if user.main_character_id == character.character_id:
        raise LinkError("choose another main character before removing this one")
    with transaction.atomic():
        EsiToken.objects.filter(character=character).delete()
        character.user = None
        character.save(update_fields=["user"])


def set_main_character(user: User, character: EveCharacter) -> None:
    if character.user_id != user.pk:
        raise LinkError("character is not on this account")
    user.main_character = character
    user.display_name = character.name
    user.save(update_fields=["main_character", "display_name"])


def store_tokens(character: EveCharacter, tokens: dict, scopes: tuple[str, ...]) -> EsiToken:
    """Save the tokens from a code exchange or refresh, replacing any previous ones."""
    now = timezone.now()
    expires_in = int(tokens.get("expires_in") or 0)
    token, _ = EsiToken.objects.update_or_create(
        character=character,
        defaults={
            "scopes": sorted(scopes),
            "refresh_token": crypto.encrypt(tokens["refresh_token"]),
            "access_token": crypto.encrypt(tokens["access_token"]),
            "access_expires_at": now + timedelta(seconds=expires_in) if expires_in else None,
            "last_refreshed_at": now,
            "refresh_failed_at": None,
            "refresh_error": "",
        },
    )
    return token
