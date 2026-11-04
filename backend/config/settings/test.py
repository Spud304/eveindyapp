from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-secret-key"
ALLOWED_HOSTS = ["*"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
# Tests run on Postgres: JSONB, ON CONFLICT upserts and advisory locks are core behaviour.
# Default is the dev container from deploy/docker-compose.dev.yml.
DATABASES = {
    "default": env.dj_db_url(  # noqa: F405
        "TEST_DATABASE_URL", "postgres://eveindy:eveindy@localhost:5434/eveindy"
    )
}
DATABASES["default"].setdefault("OPTIONS", {})["connect_timeout"] = 5
INSTANCE_DIR = BASE_DIR / "instance-test"  # noqa: F405
SDE_DIR = INSTANCE_DIR / "sde"
DEV_LOGIN_ENABLED = True
DEV_LOGIN_CHARACTER_IDS = None  # a throwaway database; unit tests use their own ids
EVE_CLIENT_ID = "test-client-id"
EVE_CLIENT_SECRET = "test-client-secret"
CELERY_TASK_ALWAYS_EAGER = True  # tasks run inline in tests
