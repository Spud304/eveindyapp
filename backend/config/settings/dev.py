from .base import *  # noqa: F403

DEBUG = True
DEV_LOGIN_ENABLED = True
ALLOWED_HOSTS = ["*"]
# The frontend dev server (Vite) serves the app on localhost:5050 and proxies /api, /auth and
# /callback to Django on 127.0.0.1:8000. 5050 is the port the EVE application's callback uses.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5050", "http://127.0.0.1:5050"]
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
EVE_CALLBACK_URL = EVE_CALLBACK_URL or "http://localhost:5050/callback"  # noqa: F405
PUBLIC_ORIGIN = PUBLIC_ORIGIN or "http://localhost:5050"  # noqa: F405
