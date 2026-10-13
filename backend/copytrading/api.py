"""REST API for the web UI (all endpoints require login)."""

from django.conf import settings
from django.db.models import Max, Prefetch
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .brokers.base import BrokerError
from .market import is_market_open, last_token_reset
from .models import (
    AccountRole,
    Alert,
    AppSettings,
    BrokerAccount,
    CopyMode,
    CopyOrder,
    Instrument,
    Trade,
)
from .serializers import BrokerAccountSerializer, SettingsSerializer, TradeSerializer
from .services import accounts as account_service
from .services import positions as pos
from .services.alerts import broadcast, send_test_email


def _broker_error(exc: BrokerError) -> Response:
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _alert(a: Alert) -> dict:
    return {
        "id": a.id,
        "kind": a.kind,
        "kind_display": a.get_kind_display(),
        "account": a.account.label if a.account else None,
        "message": a.message,
        "count": a.count,
        "resolved": a.resolved,
        "created_at": a.created_at,
        "last_seen_at": a.last_seen_at,
    }


def _recent_trades(limit: int):
    return (
        Trade.objects.select_related("account")
        .prefetch_related(
            Prefetch("copy_orders", queryset=CopyOrder.objects.select_related("account"))
        )[:limit]
    )


class AccountViewSet(viewsets.ModelViewSet):
    queryset = BrokerAccount.objects.all()
    serializer_class = BrokerAccountSerializer

    def perform_create(self, serializer):
        account = serializer.save()
        # The very first account is the master by default.
        if not BrokerAccount.objects.filter(role=AccountRole.MASTER).exists():
            account_service.make_master(account)
        broadcast({"type": "accounts_changed"})

    def perform_update(self, serializer):
        serializer.save()
        broadcast({"type": "accounts_changed"})

    def perform_destroy(self, instance):
        instance.delete()
        broadcast({"type": "accounts_changed"})

    @action(detail=True, methods=["post"], url_path="make-master")
    def make_master(self, request, pk=None):
        account = account_service.make_master(self.get_object())
        return Response(self.get_serializer(account).data)

    @action(detail=True, methods=["get"], url_path="login-url")
    def login_url(self, request, pk=None):
        try:
            return Response({"url": account_service.kite_login_url(self.get_object())})
        except BrokerError as exc:
            return _broker_error(exc)

    @action(detail=True, methods=["post"])
    def login(self, request, pk=None):
        request_token = request.data.get("request_token", "").strip()
        if not request_token:
            raise serializers.ValidationError({"request_token": "Required."})
        try:
            account = account_service.complete_kite_login(self.get_object(), request_token)
        except BrokerError as exc:
            return _broker_error(exc)
        return Response(self.get_serializer(account).data)


def _checks(accounts: list[BrokerAccount], app: AppSettings) -> list[dict]:
    """Readiness checklist shown on the Home page (replaces `preflight`)."""
    checks = []

    def add(ok, text, level="error"):
        checks.append({"ok": ok, "level": "ok" if ok else level, "text": text})

    master = next((a for a in accounts if a.is_master), None)
    copies = [a for a in accounts if not a.is_master and a.active]

    if master is None:
        add(False, "No master account. Add one on the Accounts page.")
    elif not master.active:
        add(False, f"Master '{master.label}' is disabled.")
    else:
        add(master.token_valid, f"Master '{master.label}' logged in to Zerodha today")

    if not copies:
        add(False, "No enabled copy accounts.")
    for c in copies:
        add(c.token_valid, f"Copy '{c.label}' logged in to Zerodha today")

    synced = Instrument.objects.aggregate(last=Max("synced_at"))["last"]
    add(bool(synced and synced >= last_token_reset()),
        "F&O lot sizes synced today", level="warn")

    email_ok = bool(app.alert_email_list) and "console" not in settings.EMAIL_BACKEND
    add(email_ok, "Alert emails configured", level="warn")
    return checks


class OverviewView(APIView):
    """Everything the Home page needs in one call."""

    def get(self, request):
        app = AppSettings.load()
        accounts = list(BrokerAccount.objects.all())
        alerts = Alert.objects.filter(resolved=False).select_related("account")[:50]
        return Response({
            "mode": app.mode,
            "market_open": is_market_open(),
            "accounts": BrokerAccountSerializer(accounts, many=True).data,
            "checks": _checks(accounts, app),
            "alerts": [_alert(a) for a in alerts],
            "recent_trades": TradeSerializer(_recent_trades(10), many=True).data,
        })


class PositionsView(APIView):
    """Live positions from Zerodha: master's book plus a per-copy comparison."""

    def get(self, request):
        master = pos.master_account()
        if master is None:
            return Response({"master": None, "copies": []})
        master_pos = pos.fetch(master)
        copies = []
        for account in BrokerAccount.objects.filter(role=AccountRole.COPY, active=True):
            copy_pos = pos.fetch(account)
            rows = []
            if not master_pos.error and not copy_pos.error:
                rows = pos.compare(master_pos, copy_pos)
                for r in rows:
                    p = copy_pos.positions.get((r["exchange"], r["symbol"]))
                    r["pnl"] = p.pnl if p else None
            copies.append({
                "id": account.id,
                "label": account.label,
                "multiplier": account.multiplier,
                "error": copy_pos.error,
                "rows": rows,
            })
        return Response({
            "master": {
                "id": master.id,
                "label": master.label,
                "error": master_pos.error,
                "positions": [
                    {
                        "exchange": p.exchange,
                        "symbol": p.tradingsymbol,
                        "product": p.product,
                        "qty": p.net_quantity,
                        "avg_price": p.average_price,
                        "last_price": p.last_price,
                        "pnl": p.pnl,
                    }
                    for p in master_pos.positions.values()
                ],
            },
            "copies": copies,
        })


class OrdersView(APIView):
    """Master orders seen by the app, each with its copy orders."""

    def get(self, request):
        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except ValueError:
            limit = 100
        return Response(TradeSerializer(_recent_trades(limit), many=True).data)


class SettingsView(APIView):
    def get(self, request):
        return Response(SettingsSerializer(AppSettings.load()).data)

    def patch(self, request):
        app = AppSettings.load()
        was_off = app.mode == CopyMode.OFF
        serializer = SettingsSerializer(app, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        app = serializer.save()
        if was_off and app.mode != CopyMode.OFF:
            # Don't copy orders the master placed while copying was off.
            master = pos.master_account()
            if master:
                account_service.reset_baseline(master)
        broadcast({"type": "settings_changed", "mode": app.mode})
        return Response(SettingsSerializer(app).data)


class TestEmailView(APIView):
    def post(self, request):
        recipients = AppSettings.load().alert_email_list
        if not recipients:
            return Response({"detail": "Add at least one alert email first."}, status=400)
        if "console" in settings.EMAIL_BACKEND:
            return Response(
                {"detail": "Email sending isn't set up on the server (EMAIL_* in backend/.env)."},
                status=400,
            )
        try:
            send_test_email(recipients)
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": f"Sending failed: {exc}"}, status=400)
        return Response({"sent_to": recipients})


class AlertListView(APIView):
    def get(self, request):
        resolved = request.query_params.get("resolved") == "true"
        alerts = Alert.objects.filter(resolved=resolved).select_related("account")[:200]
        return Response([_alert(a) for a in alerts])


class ResolveAlertView(APIView):
    def post(self, request, pk):
        updated = Alert.objects.filter(pk=pk).update(resolved=True)
        if not updated:
            return Response({"detail": "not found"}, status=404)
        return Response({"id": pk, "resolved": True})


class ResolveAllAlertsView(APIView):
    def post(self, request):
        count = Alert.objects.filter(resolved=False).update(resolved=True)
        return Response({"resolved": count})
