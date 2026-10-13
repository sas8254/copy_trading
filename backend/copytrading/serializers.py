from django.conf import settings
from rest_framework import serializers

from .models import AppSettings, BrokerAccount, CopyOrder, Trade


class BrokerAccountSerializer(serializers.ModelSerializer):
    # Secrets are write-only: the UI can set them but never reads them back.
    api_secret = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_api_secret = serializers.SerializerMethodField()
    logged_in = serializers.BooleanField(source="token_valid", read_only=True)
    is_master = serializers.BooleanField(read_only=True)

    class Meta:
        model = BrokerAccount
        fields = (
            "id", "label", "broker", "role", "is_master", "client_id",
            "api_key", "api_secret", "has_api_secret",
            "logged_in", "token_updated_at",
            "active", "multiplier", "zero_qty_policy",
        )
        read_only_fields = ("id", "broker", "role", "token_updated_at")

    def get_has_api_secret(self, obj):
        return bool(obj.api_secret)

    def validate_multiplier(self, value):
        if value <= 0:
            raise serializers.ValidationError("Must be greater than 0.")
        return value

    def update(self, instance, validated_data):
        # A blank secret on edit means "keep the current one".
        if not validated_data.get("api_secret"):
            validated_data.pop("api_secret", None)
        # A token belongs to one API key / Zerodha user; changing either
        # means the user must log in again.
        if (
            ("api_key" in validated_data and validated_data["api_key"] != instance.api_key)
            or ("client_id" in validated_data
                and validated_data["client_id"].upper() != instance.client_id.upper())
        ):
            instance.access_token = ""
            instance.token_updated_at = None
        return super().update(instance, validated_data)


class SettingsSerializer(serializers.ModelSerializer):
    # Server-level (.env) value, shown on the Settings page.
    fill_grace_seconds = serializers.SerializerMethodField()

    class Meta:
        model = AppSettings
        fields = ("mode", "copy_style", "alert_emails", "instant_feed",
                  "fill_grace_seconds", "updated_at")
        read_only_fields = ("updated_at",)

    def get_fill_grace_seconds(self, obj):
        return settings.COPYTRADING_FILL_GRACE_SECONDS

    def validate_alert_emails(self, value):
        emails = [e.strip() for e in value.split(",") if e.strip()]
        field = serializers.EmailField()
        for e in emails:
            field.run_validation(e)
        return ", ".join(emails)


class CopyOrderSerializer(serializers.ModelSerializer):
    account = serializers.CharField(source="account.label")

    class Meta:
        model = CopyOrder
        fields = (
            "id", "account", "kind", "computed_quantity", "filled_quantity", "status",
            "broker_status", "is_dry_run", "attempts", "modifications",
            "broker_order_id", "error_message", "created_at",
        )


class TradeSerializer(serializers.ModelSerializer):
    account = serializers.CharField(source="account.label")
    copies = CopyOrderSerializer(source="copy_orders", many=True)

    class Meta:
        model = Trade
        fields = (
            "id", "account", "tradingsymbol", "exchange", "side", "quantity",
            "filled_quantity", "price", "average_price", "trigger_price", "order_type",
            "product", "status", "copy_style", "finalized", "broker_order_id",
            "observed_at", "copies",
        )
