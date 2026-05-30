"""REST API for the copy-trading dashboard (consumed by the Vue SPA)."""

from django.conf import settings
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AccountRole,
    Alert,
    BrokerAccount,
    CopyMapping,
    CopyOrder,
    Trade,
)


def _account(a):
    return {
        "id": a.id,
        "label": a.label,
        "role": a.role,
        "broker": a.broker,
        "active": a.active,
        "has_token": bool(a.access_token),
        "token_updated_at": a.token_updated_at,
        "copy_orders_since": a.copy_orders_since,
    }


class OverviewView(APIView):
    """One call returns everything the dashboard needs to render."""

    def get(self, request):
        accounts = [_account(a) for a in BrokerAccount.objects.all()]
        mappings = [
            {
                "id": m.id,
                "master": m.master.label,
                "copy": m.copy.label,
                "multiplier": str(m.multiplier),
                "zero_qty_policy": m.zero_qty_policy,
                "active": m.active,
            }
            for m in CopyMapping.objects.select_related("master", "copy")
        ]
        alerts = [
            {
                "id": a.id,
                "kind": a.kind,
                "account": a.account.label if a.account else None,
                "message": a.message,
                "count": a.count,
                "resolved": a.resolved,
                "last_seen_at": a.last_seen_at,
            }
            for a in Alert.objects.filter(resolved=False)[:100]
        ]
        copy_orders = [
            {
                "id": c.id,
                "symbol": c.trade.tradingsymbol,
                "side": c.trade.side,
                "qty": c.computed_quantity,
                "copy": c.mapping.copy.label,
                "status": c.status,
                "is_dry_run": c.is_dry_run,
                "attempts": c.attempts,
                "broker_order_id": c.broker_order_id,
                "error": c.error_message,
                "created_at": c.created_at,
            }
            for c in CopyOrder.objects.select_related("trade", "mapping__copy")[:50]
        ]
        trades = [
            {
                "id": t.id,
                "account": t.account.label,
                "symbol": t.tradingsymbol,
                "exchange": t.exchange,
                "side": t.side,
                "qty": t.quantity,
                "price": str(t.price) if t.price is not None else None,
                "order_type": t.order_type,
                "observed_at": t.observed_at,
            }
            for t in Trade.objects.select_related("account")[:50]
        ]
        return Response(
            {
                "accounts": accounts,
                "mappings": mappings,
                "alerts": alerts,
                "copy_orders": copy_orders,
                "trades": trades,
                "runtime": {
                    "live_orders": settings.COPYTRADING_LIVE_ORDERS,
                    "force_market_open": settings.COPYTRADING_FORCE_MARKET_OPEN,
                    "copy_max_retries": settings.COPYTRADING_COPY_MAX_RETRIES,
                    "alert_email_cooldown": settings.COPYTRADING_ALERT_EMAIL_COOLDOWN,
                    "alert_email_to": settings.ALERT_EMAIL_TO,
                    "masters": BrokerAccount.objects.filter(
                        role=AccountRole.MASTER, active=True
                    ).count(),
                },
            }
        )


class ResolveAlertView(GenericAPIView):
    """Mark an alert resolved (manual acknowledgement from the dashboard)."""

    queryset = Alert.objects.all()

    def post(self, request, pk):
        try:
            alert = Alert.objects.get(pk=pk)
        except Alert.DoesNotExist:
            return Response({"detail": "not found"}, status=404)
        alert.resolved = True
        alert.save(update_fields=["resolved"])
        return Response({"id": alert.id, "resolved": True})
