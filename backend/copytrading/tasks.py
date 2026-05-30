"""Celery tasks for copy trading.

For the infra step these are smoke-test stubs proving the worker and the 2s beat
schedule run. Real logic (order dispatch, reconciliation, alerts) lands in the
later steps described in PLAN.md.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def ping():
    """Trivial task to verify the Celery worker is processing the queue."""
    logger.info("copytrading.ping: worker is alive")
    return "pong"


@shared_task
def reconcile_positions():
    """Compare master vs copy positions every 2s; alert on mismatch.

    Skips fast outside market hours. Read-only against the brokers.
    """
    from .services.reconcile import reconcile

    try:
        return reconcile()
    except Exception:  # noqa: BLE001 - never let the beat task die
        logger.exception("reconcile_positions failed")
        return {"error": "exception"}
