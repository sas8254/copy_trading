"""Copy-trading tests. Broker calls are faked; nothing reaches Zerodha.

    docker compose exec web python manage.py test copytrading
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from knox.models import AuthToken
from rest_framework.test import APIClient

from .brokers.base import BrokerError, Position
from .fields import PREFIX
from .models import (
    AccountRole,
    Alert,
    AlertKind,
    AppSettings,
    BrokerAccount,
    CopyMode,
    CopyOrder,
    CopyOrderKind,
    CopyOrderStatus,
    CopyStyle,
    Instrument,
    Trade,
    ZeroQtyPolicy,
)
from .services import accounts as account_service
from .services import dispatch, sync
from .services.reconcile import reconcile


class FakeClient:
    """Stands in for ZerodhaClient: one shared fake Zerodha with an order book
    and positions per account (keyed by api_key)."""

    books: dict = {}
    positions_by_key: dict = {}
    placed: list = []
    modified: list = []
    cancelled: list = []
    fail: BrokerError | None = None
    session = {"access_token": "new-token", "user_id": "AB1234"}

    @classmethod
    def reset(cls):
        cls.books, cls.positions_by_key = {}, {}
        cls.placed, cls.modified, cls.cancelled = [], [], []
        cls.fail = None

    def __init__(self, account):
        self.account = account
        self.book = FakeClient.books.setdefault(account.api_key, {})

    def positions(self):
        return FakeClient.positions_by_key.get(self.account.api_key, [])

    def orders(self):
        return [dict(o) for o in self.book.values()]

    def place_order(self, req):
        if FakeClient.fail:
            raise FakeClient.fail
        order_id = f"C{len(FakeClient.placed) + 1}"
        self.book[order_id] = {
            "order_id": order_id, "status": "OPEN", "quantity": req.quantity,
            "filled_quantity": 0, "order_type": req.order_type, "price": req.price,
            "trigger_price": req.trigger_price, "variety": req.variety,
        }
        FakeClient.placed.append((self.account.label, req))
        return order_id

    def modify_order(self, order_id, **kw):
        self.book[order_id].update(kw)
        FakeClient.modified.append((order_id, kw))

    def cancel_order(self, order_id, *, variety):
        self.book[order_id]["status"] = "CANCELLED"
        FakeClient.cancelled.append(order_id)

    def login_url(self, redirect_params=""):
        return f"https://kite.zerodha.com/connect/login?api_key={self.account.api_key}" \
               f"&redirect_params={redirect_params}"

    def generate_session(self, request_token):
        return dict(FakeClient.session)


def fake_get_client(account):
    return FakeClient(account)


def pos(symbol, qty, exchange="NFO"):
    return Position(tradingsymbol=symbol, exchange=exchange, net_quantity=qty,
                    pnl=Decimal("0"))


@override_settings(COPYTRADING_FORCE_MARKET_OPEN=True, COPYTRADING_COPY_MAX_RETRIES=0,
                   COPYTRADING_FILL_GRACE_SECONDS=0)
class CopyTradingTestCase(TestCase):
    def setUp(self):
        for target in ("positions", "dispatch", "accounts", "sync"):
            self.enterContext(patch(f"copytrading.services.{target}.get_client", fake_get_client))
        # Celery isn't running in tests: place copy orders inline.
        self.enterContext(patch("copytrading.tasks.place_copy_order.delay",
                                side_effect=dispatch.place_copy_order))
        self.enterContext(patch("copytrading.tasks.sync_instruments.delay"))
        FakeClient.reset()
        now = timezone.now() - timedelta(minutes=1)
        self.master = BrokerAccount.objects.create(
            label="Mom", role=AccountRole.MASTER, api_key="mk", api_secret="ms",
            access_token="mt", token_updated_at=now, copy_orders_since=now,
        )
        self.copy = BrokerAccount.objects.create(
            label="Me", role=AccountRole.COPY, api_key="ck", api_secret="cs",
            access_token="ct", token_updated_at=now, multiplier=Decimal("2"),
        )
        Instrument.objects.create(exchange="NFO", tradingsymbol="NIFTYFUT", lot_size=65)
        self.set_mode(CopyMode.LIVE)

    def set_mode(self, mode=None, style=None):
        app = AppSettings.load()
        app.mode = mode or app.mode
        app.copy_style = style or app.copy_style
        app.save()

    # --- fake broker activity ---
    def master_order(self, order_id="M1", status="OPEN", qty=65, filled=0,
                     order_type="LIMIT", price=100, avg=None, trigger=None):
        FakeClient.books.setdefault("mk", {})[order_id] = {
            "order_id": order_id, "status": status, "quantity": qty,
            "filled_quantity": filled, "order_type": order_type, "price": price,
            "average_price": avg or (price if filled else 0), "trigger_price": trigger,
            "tradingsymbol": "NIFTYFUT", "exchange": "NFO", "transaction_type": "BUY",
            "product": "NRML", "variety": "regular", "order_timestamp": timezone.now(),
        }

    def update_master(self, order_id="M1", **fields):
        FakeClient.books["mk"][order_id].update(fields)

    def update_copy(self, order_id, **fields):
        FakeClient.books["ck"][order_id].update(fields)

    def fill_copy(self, order_id, filled, status="COMPLETE"):
        self.update_copy(order_id, filled_quantity=filled, status=status)

    def cycle(self):
        return sync.run_cycle()

    def copies(self, kind=None):
        qs = CopyOrder.objects.order_by("id")
        return list(qs.filter(kind=kind) if kind else qs)

    def trade(self):
        return Trade.objects.get()


class OnFillTests(CopyTradingTestCase):
    def test_dry_run_simulates_and_never_calls_broker(self):
        self.set_mode(CopyMode.DRY_RUN)
        self.master_order(status="COMPLETE", filled=65)
        self.cycle()
        [co] = self.copies()
        self.assertEqual((co.status, co.computed_quantity), (CopyOrderStatus.SIMULATED, 130))
        self.assertTrue(self.trade().finalized)
        self.assertEqual(FakeClient.placed, [])

    def test_open_order_is_not_copied_until_filled(self):
        self.master_order(status="OPEN")
        self.cycle()
        self.assertFalse(Trade.objects.exists())

    @override_settings(COPYTRADING_FILL_GRACE_SECONDS=60)
    def test_limit_copied_at_master_fill_price_then_finalized(self):
        self.master_order(status="COMPLETE", filled=65, price=100, avg=101)
        self.cycle()
        [(label, req)] = FakeClient.placed
        self.assertEqual((label, req.quantity, req.order_type, req.price),
                         ("Me", 130, "LIMIT", 101.0))
        self.assertFalse(self.trade().finalized)  # waiting for the copy to fill
        self.fill_copy("C1", 130)
        self.cycle()
        self.assertTrue(self.trade().finalized)
        self.assertEqual(len(self.copies()), 1)  # no top-up needed

    def test_stop_loss_is_copied_at_market(self):
        self.master_order(status="COMPLETE", filled=65, order_type="SL", price=99, trigger=100)
        self.cycle()
        req = FakeClient.placed[0][1]
        self.assertEqual((req.order_type, req.price, req.trigger_price), ("MARKET", None, None))

    def test_partially_filled_then_cancelled_copies_the_filled_part(self):
        self.master_order(status="CANCELLED", qty=130, filled=65)
        self.cycle()
        self.assertEqual(FakeClient.placed[0][1].quantity, 130)  # 65 filled x2

    def test_unfilled_copy_is_cancelled_after_grace_then_topped_up_at_market(self):
        self.master_order(status="COMPLETE", filled=65)
        self.cycle()  # place copy; grace 0 -> cancel request
        self.assertEqual(FakeClient.cancelled, ["C1"])
        self.cycle()  # sees CANCELLED, 0 filled -> MARKET top-up for 130
        [top] = self.copies(CopyOrderKind.TOPUP)
        req = FakeClient.placed[1][1]
        self.assertEqual((top.computed_quantity, req.order_type), (130, "MARKET"))
        self.cycle()
        self.assertFalse(self.trade().finalized)  # top-up still open
        self.fill_copy("C2", 130)
        self.cycle()
        self.assertTrue(self.trade().finalized)
        self.assertFalse(Alert.objects.exists())

    @override_settings(COPYTRADING_FILL_GRACE_SECONDS=60)
    def test_grace_period_is_respected(self):
        self.master_order(status="COMPLETE", filled=65)
        self.cycle()
        self.cycle()
        self.assertEqual(FakeClient.cancelled, [])

    def test_off_records_but_never_copies(self):
        self.set_mode(CopyMode.OFF)
        self.master_order(status="COMPLETE", filled=65)
        self.cycle()
        self.assertTrue(self.trade().finalized)
        self.assertEqual(self.copies(), [])

    def test_disabled_copy_account_is_ignored(self):
        self.copy.active = False
        self.copy.save()
        self.master_order(status="COMPLETE", filled=65)
        self.cycle()
        self.assertEqual(self.copies(), [])
        self.assertTrue(self.trade().finalized)

    def test_terminal_failure_marks_failed_and_alerts_without_topup(self):
        FakeClient.fail = BrokerError("insufficient margin", kind="terminal")
        self.master_order(status="COMPLETE", filled=65)
        self.cycle()
        self.cycle()
        [co] = self.copies()
        self.assertEqual(co.status, CopyOrderStatus.FAILED)
        self.assertTrue(Alert.objects.filter(kind=AlertKind.ORDER_FAILED).exists())
        self.assertTrue(self.trade().finalized)

    @override_settings(COPYTRADING_FILL_GRACE_SECONDS=60)
    def test_rejected_after_placing_alerts_without_topup(self):
        self.master_order(status="COMPLETE", filled=65)
        self.cycle()
        self.update_copy("C1", status="REJECTED", status_message="Insufficient funds")
        self.cycle()
        [co] = self.copies()
        self.assertEqual(co.broker_status, "REJECTED")
        alert = Alert.objects.get(kind=AlertKind.ORDER_FAILED)
        self.assertIn("Insufficient funds", alert.message)
        self.assertTrue(self.trade().finalized)

    def test_zero_qty_skips_and_alerts(self):
        self.copy.multiplier = Decimal("0.5")
        self.copy.save()
        self.master_order(status="COMPLETE", filled=65)  # 32.5 -> 0 lots
        self.cycle()
        [co] = self.copies()
        self.assertEqual(co.status, CopyOrderStatus.SKIPPED)
        self.assertTrue(Alert.objects.filter(kind=AlertKind.ZERO_QTY).exists())
        self.assertTrue(self.trade().finalized)

    def test_zero_qty_round_up_places_one_lot(self):
        self.copy.multiplier = Decimal("0.5")
        self.copy.zero_qty_policy = ZeroQtyPolicy.ROUND_UP
        self.copy.save()
        self.master_order(status="COMPLETE", filled=65)
        self.cycle()
        self.assertEqual(FakeClient.placed[0][1].quantity, 65)

    def test_orders_before_baseline_are_ignored(self):
        self.master_order(status="COMPLETE", filled=65)
        self.update_master(order_timestamp=timezone.now() - timedelta(hours=1))
        self.cycle()
        self.assertFalse(Trade.objects.exists())

    def test_each_order_is_copied_once(self):
        self.master_order(status="COMPLETE", filled=65)
        for _ in range(3):
            self.cycle()
        self.assertEqual(len(self.copies(CopyOrderKind.COPY)), 1)

    def test_switching_off_after_queueing_skips_placement(self):
        self.master_order(status="COMPLETE", filled=65)
        with patch("copytrading.tasks.place_copy_order.delay"):
            self.cycle()
        self.set_mode(CopyMode.OFF)
        co = CopyOrder.objects.get()
        dispatch.place_copy_order(co.id)
        co.refresh_from_db()
        self.assertEqual(co.status, CopyOrderStatus.SKIPPED)
        self.assertEqual(FakeClient.placed, [])


class MirrorTests(CopyTradingTestCase):
    def setUp(self):
        super().setUp()
        self.set_mode(style=CopyStyle.MIRROR)

    def test_open_order_is_copied_immediately_with_same_price(self):
        self.master_order(status="OPEN", price=100)
        self.cycle()
        [(label, req)] = FakeClient.placed
        self.assertEqual((req.quantity, req.order_type, req.price), (130, "LIMIT", 100.0))
        self.assertFalse(self.trade().finalized)

    def test_stop_loss_keeps_its_trigger(self):
        self.master_order(status="TRIGGER PENDING", order_type="SL", price=99, trigger=100)
        self.cycle()
        req = FakeClient.placed[0][1]
        self.assertEqual((req.order_type, req.price, req.trigger_price), ("SL", 99.0, 100.0))

    def test_master_modification_is_mirrored_once(self):
        self.master_order(status="OPEN", price=100)
        self.cycle()
        self.update_master(price=98, quantity=130)
        self.cycle()
        [(order_id, kw)] = FakeClient.modified
        self.assertEqual((order_id, kw["price"], kw["quantity"]), ("C1", 98.0, 260))
        co = CopyOrder.objects.get()
        self.assertEqual((co.modifications, co.computed_quantity), (1, 260))
        self.cycle()
        self.assertEqual(len(FakeClient.modified), 1)  # not re-sent

    def test_master_cancel_cancels_copy(self):
        self.master_order(status="OPEN")
        self.cycle()
        self.update_master(status="CANCELLED")
        self.cycle()
        self.assertEqual(FakeClient.cancelled, ["C1"])
        self.cycle()
        self.assertTrue(self.trade().finalized)
        self.assertEqual(len(FakeClient.placed), 1)  # no top-up
        self.assertFalse(Alert.objects.exists())

    def test_copy_behind_gets_topped_up_after_master_fills(self):
        self.master_order(status="OPEN")
        self.cycle()
        self.fill_copy("C1", 65, status="OPEN")  # copy half filled
        self.update_master(status="COMPLETE", filled_quantity=65, average_price=100)
        self.cycle()  # grace 0 -> cancel the copy's remainder
        self.assertEqual(FakeClient.cancelled, ["C1"])
        self.cycle()  # top up the other 65 at MARKET
        req = FakeClient.placed[1][1]
        self.assertEqual((req.quantity, req.order_type), (65, "MARKET"))
        self.fill_copy("C2", 65)
        self.cycle()
        self.assertTrue(self.trade().finalized)
        self.assertFalse(Alert.objects.exists())

    def test_copy_ahead_alerts_and_never_auto_exits(self):
        self.master_order(status="OPEN")
        self.cycle()
        self.fill_copy("C1", 130)
        self.update_master(status="CANCELLED")
        self.cycle()
        self.assertTrue(self.trade().finalized)
        self.assertEqual(len(FakeClient.placed), 1)
        alert = Alert.objects.get(kind=AlertKind.MISMATCH)
        self.assertIn("130 extra", alert.message)

    def test_order_first_seen_already_filled_is_copied_at_market(self):
        self.master_order(status="COMPLETE", filled=65, order_type="MARKET", price=0)
        self.cycle()
        [top] = self.copies()
        self.assertEqual((top.kind, top.computed_quantity), (CopyOrderKind.TOPUP, 130))
        self.assertEqual(FakeClient.placed[0][1].order_type, "MARKET")

    def test_dry_run_records_modifications_without_broker(self):
        self.set_mode(CopyMode.DRY_RUN)
        self.master_order(status="OPEN", price=100)
        self.cycle()
        self.update_master(price=99)
        self.cycle()
        co = CopyOrder.objects.get()
        self.assertEqual((co.status, co.modifications), (CopyOrderStatus.SIMULATED, 1))
        self.update_master(status="CANCELLED")
        self.cycle()
        self.assertTrue(self.trade().finalized)
        self.assertEqual((FakeClient.placed, FakeClient.modified), ([], []))

    def test_turning_off_stops_following(self):
        self.master_order(status="OPEN", price=100)
        self.cycle()
        self.set_mode(CopyMode.OFF)
        self.update_master(price=98)
        self.cycle()
        self.assertEqual(FakeClient.modified, [])
        self.assertTrue(self.trade().finalized)

    def test_non_regular_orders_fall_back_to_copy_on_fill(self):
        self.master_order(status="OPEN")
        self.update_master(variety="iceberg")
        self.cycle()
        self.assertFalse(Trade.objects.exists())


class ReconcileTests(CopyTradingTestCase):
    def test_mismatch_alerts_then_auto_resolves(self):
        FakeClient.positions_by_key = {"mk": [pos("NIFTYFUT", 65)], "ck": []}
        self.assertEqual(reconcile()["mismatches"], 1)
        alert = Alert.objects.get(kind=AlertKind.MISMATCH)
        self.assertIn("expected 130", alert.message)

        FakeClient.positions_by_key["ck"] = [pos("NIFTYFUT", 130)]
        self.assertEqual(reconcile()["mismatches"], 0)
        alert.refresh_from_db()
        self.assertTrue(alert.resolved)

    def test_symbols_still_being_copied_are_not_flagged(self):
        Trade.objects.create(account=self.master, tradingsymbol="NIFTYFUT", exchange="NFO",
                             side="BUY", quantity=65, broker_order_id="X", status="OPEN")
        FakeClient.positions_by_key = {"mk": [pos("NIFTYFUT", 65)], "ck": []}
        self.assertEqual(reconcile()["mismatches"], 0)

    def test_skipped_unless_live(self):
        self.set_mode(CopyMode.DRY_RUN)
        FakeClient.positions_by_key = {"mk": [pos("NIFTYFUT", 65)], "ck": []}
        self.assertEqual(reconcile(), {"skipped": "not_live"})
        self.assertFalse(Alert.objects.exists())


class AccountServiceTests(CopyTradingTestCase):
    def test_make_master_demotes_previous_master(self):
        account_service.make_master(self.copy)
        self.master.refresh_from_db()
        self.copy.refresh_from_db()
        self.assertEqual(self.master.role, AccountRole.COPY)
        self.assertEqual(self.copy.role, AccountRole.MASTER)
        self.assertIsNotNone(self.copy.copy_orders_since)

    def test_login_stores_token_and_fills_client_id(self):
        self.master.access_token = ""
        self.master.save()
        before = timezone.now()
        account_service.complete_kite_login(self.master, "req")
        self.master.refresh_from_db()
        self.assertEqual(self.master.access_token, "new-token")
        self.assertEqual(self.master.client_id, "AB1234")
        self.assertTrue(self.master.token_valid)
        self.assertGreaterEqual(self.master.copy_orders_since, before)

    def test_login_as_wrong_zerodha_user_is_rejected(self):
        self.copy.client_id = "ZZ9999"
        self.copy.save()
        with self.assertRaises(BrokerError):
            account_service.complete_kite_login(self.copy, "req")

    def test_secrets_are_encrypted_in_database(self):
        with connection.cursor() as cur:
            cur.execute("SELECT api_secret, access_token FROM copytrading_brokeraccount "
                        "WHERE id = %s", [self.master.id])
            secret, token = cur.fetchone()
        self.assertTrue(secret.startswith(PREFIX))
        self.assertTrue(token.startswith(PREFIX))
        self.assertNotIn("ms", secret[len(PREFIX):][:2])
        self.master.refresh_from_db()
        self.assertEqual(self.master.api_secret, "ms")


class ApiTests(CopyTradingTestCase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user("me", password="pw")
        _, token = AuthToken.objects.create(user)
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_requires_login(self):
        self.assertEqual(APIClient().get("/api/copytrading/overview/").status_code, 401)

    def test_registration_is_closed(self):
        r = APIClient().post("/api/auth/register/", {"username": "x", "password": "y"})
        self.assertEqual(r.status_code, 404)

    def test_account_api_never_returns_secret(self):
        r = self.api.get(f"/api/copytrading/accounts/{self.master.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("api_secret", r.data)
        self.assertNotIn("access_token", r.data)
        self.assertTrue(r.data["has_api_secret"])
        self.assertTrue(r.data["logged_in"])

    def test_blank_secret_on_edit_keeps_existing(self):
        r = self.api.patch(f"/api/copytrading/accounts/{self.copy.id}/",
                           {"api_secret": "", "multiplier": "3"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.copy.refresh_from_db()
        self.assertEqual((self.copy.api_secret, self.copy.multiplier), ("cs", Decimal("3")))

    def test_changing_api_key_logs_account_out(self):
        self.api.patch(f"/api/copytrading/accounts/{self.copy.id}/",
                       {"api_key": "other"}, format="json")
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.access_token, "")

    def test_first_account_becomes_master(self):
        BrokerAccount.objects.all().delete()
        r = self.api.post("/api/copytrading/accounts/",
                          {"label": "New", "api_key": "k", "api_secret": "s"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(BrokerAccount.objects.get().role, AccountRole.MASTER)

    def test_make_master_endpoint(self):
        r = self.api.post(f"/api/copytrading/accounts/{self.copy.id}/make-master/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["is_master"])

    def test_login_flow(self):
        r = self.api.get(f"/api/copytrading/accounts/{self.copy.id}/login-url/")
        self.assertIn(f"account%3D{self.copy.id}", r.data["url"].replace("=", "%3D"))
        r = self.api.post(f"/api/copytrading/accounts/{self.copy.id}/login/",
                          {"request_token": "req"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["logged_in"])

    def test_old_backend_redirect_url_forwards_to_website(self):
        r = APIClient().get("/?account=2&status=success&request_token=abc")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("/kite/callback?account=2&status=success&request_token=abc"))

    def test_settings_turning_copying_back_on_resets_baseline(self):
        self.set_mode(CopyMode.OFF)
        old = self.master.copy_orders_since
        r = self.api.patch("/api/copytrading/settings/", {"mode": "live"}, format="json")
        self.assertEqual(r.data["mode"], "live")
        self.master.refresh_from_db()
        self.assertGreater(self.master.copy_orders_since, old)

    def test_copy_style_and_instant_feed(self):
        r = self.api.patch("/api/copytrading/settings/",
                           {"copy_style": "mirror", "instant_feed": True}, format="json")
        self.assertEqual((r.data["copy_style"], r.data["instant_feed"]), ("mirror", True))
        app = AppSettings.load()
        self.assertEqual((app.copy_style, app.instant_feed), (CopyStyle.MIRROR, True))

    def test_settings_rejects_bad_email(self):
        r = self.api.patch("/api/copytrading/settings/",
                           {"alert_emails": "a@b.com, nope"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_positions_compare(self):
        FakeClient.positions_by_key = {"mk": [pos("NIFTYFUT", 65)], "ck": [pos("NIFTYFUT", 65)]}
        r = self.api.get("/api/copytrading/positions/")
        [row] = r.data["copies"][0]["rows"]
        self.assertEqual((row["expected"], row["actual"], row["ok"]), (130, 65, False))

    def test_orders_include_copy_details(self):
        self.master_order(status="COMPLETE", filled=65)
        sync.run_cycle()
        [t] = self.api.get("/api/copytrading/orders/").data
        self.assertEqual((t["status"], t["filled_quantity"]), ("COMPLETE", 65))
        [c] = t["copies"]
        self.assertEqual((c["kind"], c["broker_status"]), ("copy", "OPEN"))

    def test_overview(self):
        r = self.api.get("/api/copytrading/overview/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["mode"], CopyMode.LIVE)
        self.assertTrue(any(c["ok"] for c in r.data["checks"]))
