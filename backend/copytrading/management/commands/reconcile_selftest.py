"""End-to-end self-test of the reconciliation pipeline using fake broker data.

Creates temporary master/copy accounts + a mapping, patches the broker client
with canned positions, and runs reconcile() through the real alert/email code.
Everything is rolled back, so no permanent rows and no broker calls are made.

    python manage.py reconcile_selftest
"""

from decimal import Decimal
from unittest.mock import patch

from django.core.management.base import BaseCommand
from django.db import transaction
from django.test import override_settings

from copytrading.brokers.base import Position
from copytrading.models import (
    AccountRole,
    Alert,
    AlertKind,
    BrokerAccount,
    CopyMapping,
    Instrument,
)


class _FakeClient:
    def __init__(self, positions):
        self._positions = positions

    def positions(self):
        return self._positions


class Command(BaseCommand):
    help = "Self-test the reconciliation + alert pipeline with fake data (no broker calls)."

    def handle(self, *args, **opts):
        try:
            with transaction.atomic():
                self._run()
                # Roll back everything we created.
                transaction.set_rollback(True)
        except _Done:
            pass

    def _run(self):
        out = self.stdout
        style = self.style

        # --- temp fixtures ---
        master = BrokerAccount.objects.create(
            label="SELFTEST-master", role=AccountRole.MASTER, access_token="x"
        )
        copy = BrokerAccount.objects.create(
            label="SELFTEST-copy", role=AccountRole.COPY, access_token="x"
        )
        mapping = CopyMapping.objects.create(master=master, copy=copy, multiplier=Decimal("1"))
        Instrument.objects.update_or_create(
            exchange="NFO",
            tradingsymbol="NIFTY24JUNFUT",
            defaults={"lot_size": 50, "name": "NIFTY"},
        )

        master_pos = [
            Position("NIFTY24JUNFUT", "NFO", net_quantity=50, average_price=Decimal("100"))
        ]

        from copytrading.services import reconcile as recon

        common = dict(
            COPYTRADING_FORCE_MARKET_OPEN=True,
            ALERT_EMAIL_TO=["test@example.com"],
            EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        )

        def run_with(copy_qty):
            copy_pos = (
                [Position("NIFTY24JUNFUT", "NFO", net_quantity=copy_qty,
                          average_price=Decimal("100"))]
                if copy_qty
                else []
            )

            def fake_get_client(account):
                return _FakeClient(master_pos if account.id == master.id else copy_pos)

            with override_settings(**common), patch.object(recon, "get_client", fake_get_client):
                return recon.reconcile()

        # Scope all assertions to THIS mapping's dedup key so pre-existing real
        # mismatch alerts in the DB don't pollute the counts.
        dedup_key = f"recon:{mapping.id}:NFO:NIFTY24JUNFUT"
        scoped = lambda **kw: Alert.objects.filter(dedup_key=dedup_key, **kw)  # noqa: E731

        # 1) Mismatch: master 50, copy 0 -> expected 50 != 0
        out.write(style.MIGRATE_HEADING("\n[1] Mismatch case (master 50, copy 0):"))
        summary = run_with(0)
        out.write(f"    summary: {summary}")
        a = scoped(resolved=False).first()
        out.write(style.SUCCESS(f"    alert created: {a.message}") if a
                  else style.ERROR("    FAIL: no mismatch alert"))

        # 2) Still mismatched next tick -> same alert, count increments, no new row
        out.write(style.MIGRATE_HEADING("\n[2] Dedup (second tick, still mismatched):"))
        run_with(0)
        a.refresh_from_db()
        n = scoped().count()
        out.write(style.SUCCESS(f"    same alert reused, count={a.count}, total rows={n}")
                  if a.count == 2 and n == 1 else style.ERROR(f"    FAIL: count={a.count} rows={n}"))

        # 3) Now matched: copy 50 -> alert auto-resolves
        out.write(style.MIGRATE_HEADING("\n[3] Match case (copy now 50) -> auto-resolve:"))
        summary = run_with(50)
        out.write(f"    summary: {summary}")
        a.refresh_from_db()
        out.write(style.SUCCESS("    alert auto-resolved") if a.resolved
                  else style.ERROR("    FAIL: alert not resolved"))

        out.write(style.MIGRATE_HEADING("\n(Console email output above shows the emailed alert.)"))
        out.write("All temporary rows rolled back.\n")
        raise _Done()


class _Done(Exception):
    pass
