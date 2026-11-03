from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = [DOMAIN, "web", "localhost", "127.0.0.1"]  # noqa: F405
CSRF_TRUSTED_ORIGINS = [f"https://{DOMAIN}"]  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

if SECRET_KEY in ("", "change-me", "dev-insecure-secret-key"):  # noqa: F405
    raise RuntimeError("SECRET_KEY is not set; set it in deploy/.env (see deploy/.env.example)")
