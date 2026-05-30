"""Sync instrument metadata (lot sizes) from Zerodha into the Instrument table.

    python manage.py kite_sync_instruments --account "Main Zerodha"
    python manage.py kite_sync_instruments --account "Main Zerodha" --exchange NFO

Defaults to NFO (F&O) since that is where lot sizes matter. The dump is large,
so run this once per day (instruments change on expiry rolls), not every loop.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from copytrading.brokers import get_client
from copytrading.models import Broker, Instrument

from ._utils import resolve_account


class Command(BaseCommand):
    help = "Sync instrument lot sizes from the broker into the Instrument table."

    def add_arguments(self, parser):
        parser.add_argument("--account", required=True, help="BrokerAccount id or label")
        parser.add_argument(
            "--exchange",
            default="NFO",
            help="Exchange segment to sync (default NFO). Use 'ALL' for everything.",
        )

    def handle(self, *args, **opts):
        account = resolve_account(opts["account"])
        if not account.access_token:
            raise CommandError(f"'{account.label}' has no access token; run kite_login.")

        client = get_client(account)
        exchange = opts["exchange"]
        kite = client.kite  # Zerodha-specific; fine for a Zerodha-only command.

        self.stdout.write(f"Fetching instruments ({exchange})...")
        rows = kite.instruments() if exchange == "ALL" else kite.instruments(exchange)
        self.stdout.write(f"Got {len(rows)} instruments; upserting...")

        created = updated = 0
        with transaction.atomic():
            for r in rows:
                obj, was_created = Instrument.objects.update_or_create(
                    broker=Broker.ZERODHA,
                    exchange=r.get("exchange", ""),
                    tradingsymbol=r.get("tradingsymbol", ""),
                    defaults={
                        "instrument_token": r.get("instrument_token"),
                        "name": r.get("name", "") or "",
                        "lot_size": r.get("lot_size") or 1,
                        "tick_size": r.get("tick_size") or 0,
                        "instrument_type": r.get("instrument_type", "") or "",
                        "segment": r.get("segment", "") or "",
                        "expiry": r.get("expiry") or None,
                    },
                )
                created += was_created
                updated += not was_created

        self.stdout.write(
            self.style.SUCCESS(f"Done. created={created} updated={updated}")
        )
