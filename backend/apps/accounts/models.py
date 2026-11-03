"""An account is a `User` (the person, named after their main character) owning linked
`EveCharacter`s. Config, stations and plans belong to the account, never to a character.

A character linked for planning has an `EsiToken`: the refresh token for the industry scopes.
Logging in alone stores no token (login uses publicData only).
"""

from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

if TYPE_CHECKING:
    from django_stubs_ext.db.models.manager import RelatedManager


class UserManager(BaseUserManager):
    def create_user(self, username: str, **extra) -> "User":
        user = self.model(username=username, **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(
        self, username: str, email: str | None = None, password: str | None = None, **extra
    ) -> "User":
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("display_name", username)
        user = self.model(username=username, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    """An account. Logs in only through EVE SSO and owns one or more characters."""

    username = models.CharField(max_length=64, unique=True)
    display_name = models.CharField(max_length=100)
    main_character = models.ForeignKey(
        "accounts.EveCharacter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects = UserManager()

    if TYPE_CHECKING:
        characters: "RelatedManager[EveCharacter]"
        main_character_id: int | None

    class Meta:
        db_table = "accounts_user"

    def __str__(self) -> str:
        return self.display_name or self.username


class EveCharacter(models.Model):
    character_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    owner_hash = models.CharField(max_length=64, blank=True)
    corporation_id = models.BigIntegerField(null=True, blank=True)
    alliance_id = models.BigIntegerField(null=True, blank=True)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="characters"
    )
    affiliation_checked_at = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    if TYPE_CHECKING:
        user_id: int | None
        esi_token: "EsiToken"

    class Meta:
        db_table = "accounts_eve_character"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class EsiToken(models.Model):
    """ESI tokens for one character. Both tokens are Fernet-encrypted (see crypto.py).

    EVE may rotate the refresh token on every refresh, so the stored one is replaced each time.
    `refresh_failed_at` is set when SSO rejects the refresh token (revoked, character
    transferred); the character must be linked again.
    """

    character = models.OneToOneField(
        EveCharacter, primary_key=True, on_delete=models.CASCADE, related_name="esi_token"
    )
    scopes = models.JSONField(default=list)
    refresh_token = models.TextField()
    access_token = models.TextField(blank=True)
    access_expires_at = models.DateTimeField(null=True, blank=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    refresh_failed_at = models.DateTimeField(null=True, blank=True)
    refresh_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_esi_token"

    def __str__(self) -> str:
        return f"ESI token for {self.character_id}"

    def has_scopes(self, *needed: str) -> bool:
        return set(needed) <= set(self.scopes)
