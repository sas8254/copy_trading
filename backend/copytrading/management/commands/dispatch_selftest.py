"""End-to-end self-test of the dispatcher with fake broker data (no real orders).

Runs the real detect->dispatch->place pipeline against canned data, covering:
dry-run, live success, terminal failure, and zero-qty skip. Everything is
rolled back; the broker client is patched, so no Kite calls are made.

    python manage.py dispatch_selftest
"""

from decimal import Decimal
from unittest.mock import patch

from django.core.management.base import BaseCommand
from django.db import transaction
from django.test import override_settings

from copytrading.brokers.base import BrokerError
from copytrading.models import (
    AccountRole,
    BrokerAccount,
    CopyMapping,
    CopyOrder,
    CopyOrderStatus,
    Instrument,
    Side,
    Trade,
    ZeroQtyPolicy,
)


class _FakeClient:
    def __init__(self, *, fail=None):
        self.fail = fail
        self.placed = []

    def place_order(self, req):
        if self.fail:
            raise BrokerError(self.fail_msg, kind=self.fail)
        self.placed.append(req)
        return "FAKE123"

    fail_msg = "insufficient margin"


class _Done(Exception):
    pass


class Command(BaseCommand):
    help = "Self-test the dispatcher pipeline with fake data (no broker calls)."

    def handle(self, *args, **opts):
        try:
            with transaction.atomic():
                self._run()
                transaction.set_rollback(True)
        except _Done:
            pass

    def _make_trade(self, master, qty=65):
        return Trade.objects.create(
            account=master, tradingsymbol="NIFTY24JUNFUT", exchange="NFO",
            side=Side.BUY, quantity=qty, price=Decimal("100"),
            product="NRML", order_type="LIMIT", variety="regular",
            broker_order_id=f"ORD{Trade.objects.count()+1}", status="COMPLETE",
        )

    def _run(self):
        out, style = self.stdout, self.style
        from copytrading.services import dispatch as disp

        master = BrokerAccount.objects.create(label="DT-master", role=AccountRole.MASTER,
                                              access_token="x")
        copy = BrokerAccount.objects.create(label="DT-copy", role=AccountRole.COPY,
                                            access_token="x")
        mapping = CopyMapping.objects.create(master=master, copy=copy,
                                             multiplier=Decimal("1"))
        Instrument.objects.update_or_create(
            exchange="NFO", tradingsymbol="NIFTY24JUNFUT",
            defaults={"lot_size": 65, "name": "NIFTY"})

        eager = dict(CELERY_TASK_ALWAYS_EAGER=True, COPYTRADING_FORCE_MARKET_OPEN=True)

        # 1) Dry-run (default): copy order recorded as simulated, no place_order call
        out.write(style.MIGRATE_HEADING("\n[1] Dry-run (LIVE_ORDERS=False):"))
        with override_settings(COPYTRADING_LIVE_ORDERS=False, **eager):
            t = self._make_trade(master)
            disp.dispatch_trade(t.id)
            co = CopyOrder.objects.get(trade=t, mapping=mapping)
        ok = co.status == CopyOrderStatus.SIMULATED and co.computed_quantity == 65 and co.is_dry_run
        out.write(self._line(ok, f"status={co.status} qty={co.computed_quantity} dry_run={co.is_dry_run}"))

        # 2) Live success (patched broker)
        out.write(style.MIGRATE_HEADING("\n[2] Live order success (patched broker):"))
        fake = _FakeClient()
        with override_settings(COPYTRADING_LIVE_ORDERS=True, **eager), \
                patch.object(disp, "get_client", lambda a: fake):
            t = self._make_trade(master)
            disp.dispatch_trade(t.id)
            co = CopyOrder.objects.get(trade=t, mapping=mapping)
        ok = co.status == CopyOrderStatus.PLACED and co.broker_order_id == "FAKE123" and len(fake.placed) == 1
        out.write(self._line(ok, f"status={co.status} broker_id={co.broker_order_id} "
                                 f"sent_type={fake.placed[0].order_type if fake.placed else '-'}"))

        # 3) Terminal failure (margin) -> failed + alert, no retry
        out.write(style.MIGRATE_HEADING("\n[3] Terminal failure (insufficient margin):"))
        with override_settings(COPYTRADING_LIVE_ORDERS=True, **eager), \
                patch.object(disp, "get_client", lambda a: _FakeClient(fail="terminal")):
            t = self._make_trade(master)
            disp.dispatch_trade(t.id)
            co = CopyOrder.objects.get(trade=t, mapping=mapping)
        ok = co.status == CopyOrderStatus.FAILED and co.error_kind == "terminal"
        out.write(self._line(ok, f"status={co.status} error_kind={co.error_kind}"))

        # 4) Zero-qty skip + alert
        out.write(style.MIGRATE_HEADING("\n[4] Zero-qty (multiplier 0.001 -> 0 lots):"))
        mapping.multiplier = Decimal("0.001")
        mapping.zero_qty_policy = ZeroQtyPolicy.SKIP_ALERT
        mapping.save()
        with override_settings(COPYTRADING_LIVE_ORDERS=False, **eager):
            t = self._make_trade(master)
            disp.dispatch_trade(t.id)
            co = CopyOrder.objects.get(trade=t, mapping=mapping)
        ok = co.status == CopyOrderStatus.SKIPPED and co.computed_quantity == 0
        out.write(self._line(ok, f"status={co.status} qty={co.computed_quantity}"))

        out.write("\nAll temporary rows rolled back.\n")
        raise _Done()

    def _line(self, ok, detail):
        return (self.style.SUCCESS if ok else self.style.ERROR)(
            f"    {'PASS' if ok else 'FAIL'}: {detail}")
