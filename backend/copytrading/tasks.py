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

    Stub for now — just confirms Celery Beat is firing on schedule. The real
    implementation will fetch positions per BrokerAccount, apply each
    CopyMapping multiplier, and email an Alert when they diverge.
    """
    logger.debug("copytrading.reconcile_positions: tick (stub, no accounts yet)")
    return "ok"
