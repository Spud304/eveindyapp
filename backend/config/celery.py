"""Celery app for on-demand work ("refresh now", first sync after linking a character).
Periodic work is cron's job (deploy/crontab); there is no beat."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("eveindy")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
