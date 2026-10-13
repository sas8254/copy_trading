"""Celery tasks for copy trading."""

import logging

from celery import shared_task
from django.conf import settings

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


@shared_task
def poll_master_orders():
    """One pass of the copy engine: read master orders, place / modify /
    cancel / top up copy orders (see services/sync.py)."""
    from .services.sync import run_cycle

    try:
        return run_cycle()
    except Exception:  # noqa: BLE001
        logger.exception("poll_master_orders failed")
        return {"error": "exception"}


@shared_task
def sync_instruments(account_id: int | None = None):
    """Refresh F&O lot sizes using the master's (or given account's) token."""
    from .models import BrokerAccount
    from .services.accounts import sync_instruments as _sync
    from .services.positions import master_account

    account = (
        BrokerAccount.objects.filter(pk=account_id).first() if account_id else master_account()
    )
    if account is None or not account.access_token:
        logger.info("sync_instruments: no logged-in account; skipping")
        return {"skipped": "no_token"}
    try:
        return {"synced": _sync(account)}
    except Exception:  # noqa: BLE001
        logger.exception("sync_instruments failed")
        return {"error": "exception"}


@shared_task(bind=True, max_retries=10)
def place_copy_order(self, copy_order_id: int):
    """Place one CopyOrder, retrying transient broker failures with backoff."""
    from .brokers.base import BrokerError
    from .services.dispatch import place_copy_order as _place

    try:
        return _place(copy_order_id, retries=self.request.retries)
    except BrokerError as exc:
        # Exponential backoff: 2, 4, 8, ... seconds (capped).
        countdown = min(2 ** (self.request.retries + 1), 60)
        logger.warning(
            "copy order %s transient failure (retry %s): %s",
            copy_order_id, self.request.retries, exc,
        )
        raise self.retry(exc=exc, countdown=countdown,
                         max_retries=settings.COPYTRADING_COPY_MAX_RETRIES)
