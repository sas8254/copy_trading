from django.contrib import admin

from .models import (
    Alert,
    BrokerAccount,
    CopyMapping,
    CopyOrder,
    Instrument,
    PositionSnapshot,
    Trade,
)


@admin.register(BrokerAccount)
class BrokerAccountAdmin(admin.ModelAdmin):
    list_display = ("label", "broker", "role", "active", "token_updated_at")
    list_filter = ("broker", "role", "active")
    search_fields = ("label",)
    # Secrets are write-only-ish: hidden from the changelist, editable on the form.
    fields = (
        "label",
        "broker",
        "role",
        "api_key",
        "api_secret",
        "access_token",
        "token_updated_at",
        "active",
    )
    readonly_fields = ("token_updated_at",)


@admin.register(CopyMapping)
class CopyMappingAdmin(admin.ModelAdmin):
    list_display = ("master", "copy", "multiplier", "zero_qty_policy", "active")
    list_filter = ("active", "zero_qty_policy")
    autocomplete_fields = ("master", "copy")


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = (
        "observed_at",
        "account",
        "side",
        "quantity",
        "tradingsymbol",
        "exchange",
        "status",
    )
    list_filter = ("account", "side", "exchange", "status")
    search_fields = ("tradingsymbol", "broker_order_id")
    date_hierarchy = "observed_at"


@admin.register(CopyOrder)
class CopyOrderAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "mapping",
        "computed_quantity",
        "status",
        "is_dry_run",
        "attempts",
        "error_kind",
        "broker_order_id",
    )
    list_filter = ("status", "is_dry_run", "error_kind")
    search_fields = ("broker_order_id", "error_code")


@admin.register(PositionSnapshot)
class PositionSnapshotAdmin(admin.ModelAdmin):
    list_display = ("captured_at", "account", "tradingsymbol", "exchange", "net_quantity")
    list_filter = ("account", "exchange")
    search_fields = ("tradingsymbol",)
    date_hierarchy = "captured_at"


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ("tradingsymbol", "exchange", "lot_size", "instrument_type", "expiry")
    list_filter = ("exchange", "instrument_type")
    search_fields = ("tradingsymbol", "name")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("last_seen_at", "kind", "account", "count", "resolved", "emailed_at")
    list_filter = ("kind", "resolved")
    search_fields = ("message", "dedup_key")
    date_hierarchy = "created_at"
