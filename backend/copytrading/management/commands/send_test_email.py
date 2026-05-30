"""Send a test alert email to verify SMTP / ALERT_EMAIL_TO configuration.

    python manage.py send_test_email
    python manage.py send_test_email --to someone@example.com
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email using the configured email backend."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            help="Override recipient(s), comma-separated. Defaults to ALERT_EMAIL_TO.",
        )

    def handle(self, *args, **opts):
        recipients = (
            [e.strip() for e in opts["to"].split(",") if e.strip()]
            if opts.get("to")
            else settings.ALERT_EMAIL_TO
        )
        if not recipients:
            raise CommandError(
                "No recipients. Set ALERT_EMAIL_TO in .env or pass --to."
            )

        backend = settings.EMAIL_BACKEND.rsplit(".", 1)[-1]
        self.stdout.write(f"Backend: {backend}")
        self.stdout.write(f"From:    {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"To:      {', '.join(recipients)}")
        if "console" in settings.EMAIL_BACKEND:
            self.stdout.write(
                self.style.WARNING(
                    "Console backend in use — the email will print below, not actually send. "
                    "Set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend for real sends."
                )
            )

        try:
            sent = send_mail(
                subject="[CopyTrading] Test email",
                message="This is a test alert from the copy-trading app. "
                "If you received this, SMTP is configured correctly.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Send failed: {exc}")

        self.stdout.write(self.style.SUCCESS(f"send_mail returned {sent} (sent OK)."))
