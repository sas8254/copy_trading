"""Raise alerts: persist (deduped), email (rate-limited), broadcast to dashboard."""

from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from ..models import Alert, BrokerAccount

logger = logging.getLogger(__name__)

DASHBOARD_GROUP = "dashboard"


def broadcast(payload: dict) -> None:
    """Push an event to the browser dashboard group (best-effort)."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            DASHBOARD_GROUP, {"type": "dashboard_event", "payload": payload}
        )
    except Exception:  # noqa: BLE001 - never let a broadcast break the caller
        logger.exception("dashboard broadcast failed")


def raise_alert(
    kind: str,
    message: str,
    *,
    account: BrokerAccount | None = None,
    dedup_key: str = "",
    email: bool = True,
) -> Alert:
    """Create or update a deduped Alert and email it (subject to cooldown).

    Same (kind, dedup_key) collapses into one unresolved row whose `count` and
    `last_seen_at` advance. An email is only (re)sent once per
    COPYTRADING_ALERT_EMAIL_COOLDOWN seconds.
    """
    now = timezone.now()
    alert = None
    if dedup_key:
        alert = (
            Alert.objects.filter(kind=kind, dedup_key=dedup_key, resolved=False)
            .order_by("-last_seen_at")
            .first()
        )

    if alert:
        alert.count += 1
        alert.message = message
        alert.account = account or alert.account
        alert.save(update_fields=["count", "message", "account", "last_seen_at"])
    else:
        alert = Alert.objects.create(
            kind=kind, message=message, account=account, dedup_key=dedup_key
        )

    broadcast(
        {
            "type": "alert",
            "kind": kind,
            "message": message,
            "account": account.label if account else None,
            "count": alert.count,
        }
    )

    if email:
        _maybe_email(alert, now)
    return alert


def _maybe_email(alert: Alert, now) -> None:
    cooldown = settings.COPYTRADING_ALERT_EMAIL_COOLDOWN
    if alert.emailed_at and (now - alert.emailed_at).total_seconds() < cooldown:
        return
    recipients = settings.ALERT_EMAIL_TO
    if not recipients:
        logger.warning("ALERT_EMAIL_TO is empty; alert not emailed: %s", alert.message)
        return
    try:
        send_mail(
            subject=f"[CopyTrading] {alert.get_kind_display()}",
            message=alert.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to send alert email")
        return
    alert.emailed_at = now
    alert.save(update_fields=["emailed_at"])
