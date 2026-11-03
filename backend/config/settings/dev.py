from .base import *  # noqa: F403

DEBUG = True
DEV_LOGIN_ENABLED = True
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000"]
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
# 127.0.0.1, not localhost: the browser must use the same host as the callback for the session
# cookie to match.
EVE_CALLBACK_URL = EVE_CALLBACK_URL or "http://127.0.0.1:5173/auth/callback"  # noqa: F405
PUBLIC_ORIGIN = PUBLIC_ORIGIN or "http://127.0.0.1:5173"  # noqa: F405
