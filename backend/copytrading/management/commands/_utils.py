"""Shared helpers for copytrading management commands."""

from django.core.management.base import CommandError

from copytrading.models import BrokerAccount


def resolve_account(identifier: str) -> BrokerAccount:
    """Look up a BrokerAccount by primary key or by (case-insensitive) label."""
    if identifier.isdigit():
        try:
            return BrokerAccount.objects.get(pk=int(identifier))
        except BrokerAccount.DoesNotExist:
            raise CommandError(f"No BrokerAccount with id={identifier}")
    matches = list(BrokerAccount.objects.filter(label__iexact=identifier))
    if not matches:
        raise CommandError(f"No BrokerAccount with label '{identifier}'")
    if len(matches) > 1:
        raise CommandError(
            f"Multiple accounts labelled '{identifier}'; use the numeric id instead."
        )
    return matches[0]
