from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("popcorn_n_such")

# Read all CELERY_* keys from Django settings.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover tasks in every INSTALLED_APP's tasks.py.
app.autodiscover_tasks()
