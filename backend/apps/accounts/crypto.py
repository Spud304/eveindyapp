"""Encryption at rest for ESI tokens."""

import base64
import hashlib
from functools import cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class TokenDecryptError(Exception):
    pass


@cache
def _fernet(key_setting: str, secret_key: str) -> Fernet:
    if key_setting:
        return Fernet(key_setting.encode())
    # Derived key: stable for a given SECRET_KEY.
    digest = hashlib.sha256(b"eveindy-esi-token:" + secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def fernet() -> Fernet:
    return _fernet(settings.TOKEN_ENCRYPTION_KEY, settings.SECRET_KEY)


def encrypt(plain: str) -> str:
    return fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptError("stored token cannot be decrypted with the current key") from exc
