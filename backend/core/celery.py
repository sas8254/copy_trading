"""Celery application for the core project."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")

# All Celery settings live in Django settings, prefixed with CELERY_.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover tasks.py in every installed app.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
