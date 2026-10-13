"""Django admin: a backup to the web UI (everything is editable from the UI)."""

from django.contrib import admin

from .models import Alert, AppSettings, BrokerAccount, CopyOrder, Instrument, Trade


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ("mode", "alert_emails", "updated_at")

    def has_add_permission(self, request):
        return not AppSettings.objects.exists()


@admin.register(BrokerAccount)
class BrokerAccountAdmin(admin.ModelAdmin):
    list_display = ("label", "role", "client_id", "multiplier", "active", "token_updated_at")
    list_filter = ("role", "active")
    search_fields = ("label", "client_id")
    # Secrets are not shown; set them from the web UI.
    fields = (
        "label", "broker", "role", "client_id", "api_key",
        "active", "multiplier", "zero_qty_policy",
        "token_updated_at", "copy_orders_since",
    )
    readonly_fields = ("token_updated_at",)


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = (
        "observed_at", "account", "side", "quantity", "tradingsymbol", "exchange", "status",
    )
    list_filter = ("account", "side", "exchange", "status")
    search_fields = ("tradingsymbol", "broker_order_id")
    date_hierarchy = "observed_at"


@admin.register(CopyOrder)
class CopyOrderAdmin(admin.ModelAdmin):
    list_display = (
        "created_at", "account", "computed_quantity", "status", "is_dry_run",
        "attempts", "error_kind", "broker_order_id",
    )
    list_filter = ("status", "is_dry_run", "error_kind", "account")
    search_fields = ("broker_order_id", "error_code")


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
