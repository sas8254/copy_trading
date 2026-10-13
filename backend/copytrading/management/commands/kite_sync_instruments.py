"""Sync F&O lot sizes from Zerodha into the Instrument table.

Normally automatic (every weekday morning and right after the master logs in).
Run by hand only if lot sizes look wrong:

    python manage.py kite_sync_instruments
    python manage.py kite_sync_instruments --account "Mom Zerodha" --exchange NFO
"""

from django.core.management.base import BaseCommand, CommandError

from copytrading.services.accounts import SYNC_EXCHANGES, sync_instruments
from copytrading.services.positions import master_account

from ._utils import resolve_account


class Command(BaseCommand):
    help = "Sync F&O instrument lot sizes from the broker."

    def add_arguments(self, parser):
        parser.add_argument("--account", help="BrokerAccount id or label (default: master)")
        parser.add_argument(
            "--exchange", action="append",
            help=f"Exchange to sync; repeatable (default: {', '.join(SYNC_EXCHANGES)}).",
        )

    def handle(self, *args, **opts):
        account = resolve_account(opts["account"]) if opts["account"] else master_account()
        if account is None:
            raise CommandError("No master account; pass --account.")
        if not account.access_token:
            raise CommandError(f"'{account.label}' is not logged in to Zerodha.")
        exchanges = opts["exchange"] or SYNC_EXCHANGES
        self.stdout.write(f"Syncing {', '.join(exchanges)} via '{account.label}'...")
        total = sync_instruments(account, exchanges)
        self.stdout.write(self.style.SUCCESS(f"Done. {total} instruments synced."))
