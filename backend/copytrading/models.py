"""Copy-trading data model.

Single-broker (Zerodha) v1. Credentials are stored as plain DB fields for now;
field-level encryption is a later hardening pass (see PLAN.md).
"""

from django.db import models


class Broker(models.TextChoices):
    ZERODHA = "zerodha", "Zerodha"
    # Future: ANGELONE, TRADEBULLS, GROWW


class AccountRole(models.TextChoices):
    MASTER = "master", "Master"
    COPY = "copy", "Copy"


class BrokerAccount(models.Model):
    """A brokerage login. Either the source (master) or a destination (copy)."""

    label = models.CharField(max_length=100, help_text="Friendly name, e.g. 'Main Zerodha'.")
    broker = models.CharField(max_length=20, choices=Broker.choices, default=Broker.ZERODHA)
    role = models.CharField(max_length=10, choices=AccountRole.choices)

    # --- Credentials (plain for now; encrypt later) ---
    api_key = models.CharField(max_length=200, blank=True)
    api_secret = models.CharField(max_length=200, blank=True)
    # Zerodha access tokens expire ~6 AM IST and must be refreshed daily.
    access_token = models.CharField(max_length=500, blank=True)
    token_updated_at = models.DateTimeField(null=True, blank=True)

    active = models.BooleanField(default=True)
    # Master only: copy orders that complete at/after this instant. Set to "now"
    # on first detection so pre-existing orders are not replayed on startup.
    copy_orders_since = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role", "label"]

    def __str__(self):
        return f"{self.label} ({self.get_role_display()}/{self.get_broker_display()})"


class ZeroQtyPolicy(models.TextChoices):
    SKIP_ALERT = "skip_alert", "Skip and alert"
    SKIP_SILENT = "skip_silent", "Skip silently"
    ROUND_UP = "round_up", "Round up to 1 lot"


class CopyMapping(models.Model):
    """Links a master account to a copy account with a quantity multiplier."""

    master = models.ForeignKey(
        BrokerAccount,
        on_delete=models.CASCADE,
        related_name="copy_mappings_as_master",
        limit_choices_to={"role": AccountRole.MASTER},
    )
    copy = models.ForeignKey(
        BrokerAccount,
        on_delete=models.CASCADE,
        related_name="copy_mappings_as_copy",
        limit_choices_to={"role": AccountRole.COPY},
    )
    multiplier = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=1,
        help_text="copy_qty = round_to_lot(master_qty x multiplier).",
    )
    zero_qty_policy = models.CharField(
        max_length=20,
        choices=ZeroQtyPolicy.choices,
        default=ZeroQtyPolicy.SKIP_ALERT,
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["master", "copy"], name="uniq_master_copy"),
        ]

    def __str__(self):
        return f"{self.master.label} -> {self.copy.label} (x{self.multiplier})"


class Side(models.TextChoices):
    BUY = "BUY", "Buy"
    SELL = "SELL", "Sell"


class Trade(models.Model):
    """An order/fill observed on the master account."""

    account = models.ForeignKey(
        BrokerAccount, on_delete=models.CASCADE, related_name="trades"
    )

    # Instrument
    tradingsymbol = models.CharField(max_length=50)
    exchange = models.CharField(max_length=10, help_text="NSE/NFO/BSE/MCX/CDS")
    instrument_token = models.BigIntegerField(null=True, blank=True)

    # Order details
    side = models.CharField(max_length=4, choices=Side.choices)
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    trigger_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    product = models.CharField(max_length=10, blank=True, help_text="MIS/NRML/CNC")
    order_type = models.CharField(max_length=10, blank=True, help_text="MARKET/LIMIT/SL/SL-M")
    variety = models.CharField(max_length=15, blank=True, default="regular")

    broker_order_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=30, blank=True)
    observed_at = models.DateTimeField(auto_now_add=True)
    placed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-observed_at"]
        indexes = [
            models.Index(fields=["account", "broker_order_id"]),
        ]
        constraints = [
            # The same master order should only be ingested once.
            models.UniqueConstraint(
                fields=["account", "broker_order_id"],
                condition=~models.Q(broker_order_id=""),
                name="uniq_account_broker_order",
            ),
        ]

    def __str__(self):
        return f"{self.side} {self.quantity} {self.tradingsymbol} @ {self.account.label}"


class CopyOrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PLACED = "placed", "Placed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"
    SIMULATED = "simulated", "Simulated (dry-run)"


class ErrorKind(models.TextChoices):
    TRANSIENT = "transient", "Transient (retry)"
    TERMINAL = "terminal", "Terminal (no retry)"


class CopyOrder(models.Model):
    """The attempt to mirror a master Trade onto one copy account."""

    trade = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name="copy_orders")
    mapping = models.ForeignKey(CopyMapping, on_delete=models.CASCADE, related_name="copy_orders")

    computed_quantity = models.IntegerField()
    status = models.CharField(
        max_length=10, choices=CopyOrderStatus.choices, default=CopyOrderStatus.PENDING
    )
    is_dry_run = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)

    broker_order_id = models.CharField(max_length=64, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_kind = models.CharField(max_length=10, choices=ErrorKind.choices, blank=True)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["trade", "mapping"], name="uniq_trade_mapping"),
        ]

    def __str__(self):
        return f"CopyOrder {self.computed_quantity} -> {self.mapping.copy.label} [{self.status}]"


class PositionSnapshot(models.Model):
    """Periodic net position per account+instrument, used for reconciliation."""

    account = models.ForeignKey(
        BrokerAccount, on_delete=models.CASCADE, related_name="position_snapshots"
    )
    tradingsymbol = models.CharField(max_length=50)
    exchange = models.CharField(max_length=10)
    net_quantity = models.IntegerField()
    avg_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-captured_at"]
        indexes = [
            models.Index(fields=["account", "tradingsymbol", "captured_at"]),
        ]

    def __str__(self):
        return f"{self.account.label} {self.tradingsymbol}: {self.net_quantity}"


class Instrument(models.Model):
    """Cached instrument metadata (lot size, tick size) synced from the broker.

    Populated by `manage.py kite_sync_instruments`. Used to round
    master_qty x multiplier to a valid lot for both reconciliation and order
    placement.
    """

    broker = models.CharField(max_length=20, choices=Broker.choices, default=Broker.ZERODHA)
    exchange = models.CharField(max_length=10)
    tradingsymbol = models.CharField(max_length=50)
    instrument_token = models.BigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=100, blank=True)
    lot_size = models.PositiveIntegerField(default=1)
    tick_size = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    instrument_type = models.CharField(max_length=10, blank=True, help_text="FUT/CE/PE/EQ")
    segment = models.CharField(max_length=20, blank=True)
    expiry = models.DateField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["broker", "exchange", "tradingsymbol"],
                name="uniq_instrument",
            ),
        ]
        indexes = [
            models.Index(fields=["exchange", "tradingsymbol"]),
        ]

    def __str__(self):
        return f"{self.exchange}:{self.tradingsymbol} (lot {self.lot_size})"


class AlertKind(models.TextChoices):
    MISMATCH = "mismatch", "Position mismatch"
    ORDER_FAILED = "order_failed", "Copy order failed"
    ZERO_QTY = "zero_qty", "Zero quantity skipped"
    TOKEN_EXPIRED = "token_expired", "Access token expired"


class Alert(models.Model):
    """An event requiring user attention; may be emailed.

    `dedup_key` collapses the same recurring condition (e.g. a mismatch on one
    instrument) into a single row so the 2s loop does not spam emails. `count`
    and `last_seen_at` track recurrence.
    """

    kind = models.CharField(max_length=20, choices=AlertKind.choices)
    account = models.ForeignKey(
        BrokerAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts"
    )
    message = models.TextField()
    dedup_key = models.CharField(max_length=200, blank=True, db_index=True)
    count = models.PositiveIntegerField(default=1)
    resolved = models.BooleanField(default=False)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["kind", "dedup_key", "resolved"]),
        ]

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.message[:50]}"
