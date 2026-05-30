"""Daily Zerodha login flow.

Zerodha access tokens expire ~6 AM IST, so this is run once each morning.

Step 1 - print the login URL:
    python manage.py kite_login --account "Main Zerodha"

  Open the URL, log in, and Zerodha redirects to your app's redirect URL with
  ?request_token=XXXX in the query string. Copy that token.

Step 2 - exchange the request token for an access token (stored on the account):
    python manage.py kite_login --account "Main Zerodha" --request-token XXXX
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from copytrading.brokers import get_client

from ._utils import resolve_account


class Command(BaseCommand):
    help = "Generate/refresh a Zerodha daily access token for a BrokerAccount."

    def add_arguments(self, parser):
        parser.add_argument("--account", required=True, help="BrokerAccount id or label")
        parser.add_argument(
            "--request-token",
            help="request_token from the redirect URL. Omit to just print the login URL.",
        )

    def handle(self, *args, **opts):
        account = resolve_account(opts["account"])
        if not account.api_key or not account.api_secret:
            raise CommandError(
                f"Account '{account.label}' is missing api_key/api_secret. "
                "Set them in the admin first."
            )

        client = get_client(account)
        request_token = opts.get("request_token")

        if not request_token:
            self.stdout.write(self.style.WARNING("Open this URL, log in, then copy the"))
            self.stdout.write(self.style.WARNING("request_token from the redirect URL:\n"))
            self.stdout.write(client.login_url())
            self.stdout.write(
                "\nThen rerun with:  --request-token <token-from-redirect>"
            )
            return

        data = client.generate_session(request_token)
        account.access_token = data["access_token"]
        account.token_updated_at = timezone.now()
        account.save(update_fields=["access_token", "token_updated_at"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Access token stored for '{account.label}' "
                f"(user: {data.get('user_id', '?')})."
            )
        )
