"""Read-only check: print live net positions for an account.

    python manage.py kite_positions --account "Main Zerodha"

Use this to confirm the adapter + access token work before any order placement.
"""

from django.core.management.base import BaseCommand, CommandError

from copytrading.brokers import get_client
from copytrading.brokers.base import BrokerError

from ._utils import resolve_account


class Command(BaseCommand):
    help = "Print live net positions for a BrokerAccount (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--account", required=True, help="BrokerAccount id or label")

    def handle(self, *args, **opts):
        account = resolve_account(opts["account"])
        if not account.access_token:
            raise CommandError(
                f"Account '{account.label}' has no access token. "
                "Run kite_login first."
            )

        client = get_client(account)
        try:
            positions = client.positions()
        except BrokerError as exc:
            raise CommandError(f"{exc} (kind={exc.kind})")

        if not positions:
            self.stdout.write("No open positions.")
            return

        self.stdout.write(f"Net positions for '{account.label}':")
        self.stdout.write(f"{'SYMBOL':<24}{'EXCH':<6}{'QTY':>8}{'AVG':>12}")
        for p in positions:
            self.stdout.write(
                f"{p.tradingsymbol:<24}{p.exchange:<6}{p.net_quantity:>8}"
                f"{str(p.average_price):>12}"
            )
