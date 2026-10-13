"""Copy-trading data model.

One master account at a time; every enabled copy account mirrors it using its
own multiplier. Global switches (copy mode, alert emails) live in AppSettings so
they can be changed from the web UI without restarts.
"""

from django.db import models

from .fields import EncryptedTextField


class Broker(models.TextChoices):
    ZERODHA = "zerodha", "Zerodha"
    # Future: ANGELONE, TRADEBULLS, GROWW


class AccountRole(models.TextChoices):
    MASTER = "master", "Master"
    COPY = "copy", "Copy"


class CopyMode(models.TextChoices):
    OFF = "off", "Off"
    DRY_RUN = "dry_run", "Dry run"
    LIVE = "live", "Live"


class CopyStyle(models.TextChoices):
    ON_FILL = "on_fill", "When filled"
    MIRROR = "mirror", "Mirror"


class ZeroQtyPolicy(models.TextChoices):
    SKIP_ALERT = "skip_alert", "Skip and alert"
    SKIP_SILENT = "skip_silent", "Skip silently"
    ROUND_UP = "round_up", "Round up to 1 lot"


class AppSettings(models.Model):
    """Singleton (pk=1) holding the switches editable from the Settings page."""

    mode = models.CharField(
        max_length=10,
        choices=CopyMode.choices,
        default=CopyMode.DRY_RUN,
        help_text="off = copy nothing, dry_run = simulate copies, live = place real orders.",
    )
    alert_emails = models.TextField(
        blank=True, help_text="Comma-separated addresses that receive alert emails."
    )
    copy_style = models.CharField(
        max_length=10,
        choices=CopyStyle.choices,
        default=CopyStyle.ON_FILL,
        help_text="on_fill = copy once the master's order fills; mirror = copy when "
                  "placed and follow its modifications/cancellation.",
    )
    instant_feed = models.BooleanField(
        default=False,
        help_text="Use Zerodha's live order WebSocket (needs the paid Kite Connect "
                  "streaming add-on on the master). Off = 2s polling only.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "settings"
        verbose_name_plural = "settings"

    def __str__(self):
        return f"Settings (mode={self.mode})"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "AppSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def alert_email_list(self) -> list[str]:
        return [e.strip() for e in self.alert_emails.split(",") if e.strip()]


class BrokerAccount(models.Model):
    """A brokerage login: the master (source) or a copy (destination)."""

    label = models.CharField(max_length=100, help_text="Friendly name, e.g. 'Mom Zerodha'.")
    broker = models.CharField(max_length=20, choices=Broker.choices, default=Broker.ZERODHA)
    role = models.CharField(max_length=10, choices=AccountRole.choices, default=AccountRole.COPY)
    client_id = models.CharField(
        max_length=20, blank=True,
        help_text="Zerodha user ID (e.g. AB1234). Filled in on first login if blank.",
    )

    # --- Credentials (encrypted at rest) ---
    api_key = models.CharField(max_length=200, blank=True)
    api_secret = EncryptedTextField(blank=True)
    # Zerodha access tokens expire ~6 AM IST and must be refreshed daily.
    access_token = EncryptedTextField(blank=True)
    token_updated_at = models.DateTimeField(null=True, blank=True)

    active = models.BooleanField(default=True, help_text="Disabled accounts are ignored.")

    # --- Copy settings (used when role=copy) ---
    multiplier = models.DecimalField(
        max_digits=8, decimal_places=4, default=1,
        help_text="copy_qty = round_to_lot(master_qty x multiplier).",
    )
    zero_qty_policy = models.CharField(
        max_length=20, choices=ZeroQtyPolicy.choices, default=ZeroQtyPolicy.SKIP_ALERT
    )

    # Master only: copy orders that complete at/after this instant. Reset to
    # "now" whenever the account becomes master, logs in, or copying is turned
    # back on, so older orders are never replayed.
    copy_orders_since = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["role"],
                condition=models.Q(role="master"),
                name="single_master",
            ),
        ]

    def __str__(self):
        return f"{self.label} ({self.get_role_display()}/{self.get_broker_display()})"

    @property
    def is_master(self) -> bool:
        return self.role == AccountRole.MASTER

    @property
    def token_valid(self) -> bool:
        """True if a token was obtained since the last 6 AM IST reset."""
        from .market import last_token_reset

        return bool(
            self.access_token
            and self.token_updated_at
            and self.token_updated_at >= last_token_reset()
        )


class Side(models.TextChoices):
    BUY = "BUY", "Buy"
    SELL = "SELL", "Sell"


# Zerodha order statuses.
OPEN_STATUSES = ("OPEN", "TRIGGER PENDING")
TERMINAL_STATUSES = ("COMPLETE", "CANCELLED", "REJECTED")


class Trade(models.Model):
    """An order observed on the master account.

    on_fill style: created once the order is filled (or cancelled after a
    partial fill). mirror style: created as soon as the order is open, and
    kept up to date (price, quantity, status, filled quantity) every poll.
    `finalized` is set once every copy account's filled quantity has been
    checked against the master's.
    """

    account = models.ForeignKey(
        BrokerAccount, on_delete=models.CASCADE, related_name="trades"
    )

    # Instrument
    tradingsymbol = models.CharField(max_length=50)
    exchange = models.CharField(max_length=10, help_text="NSE/NFO/BSE/BFO")
    instrument_token = models.BigIntegerField(null=True, blank=True)

    # Order details
    side = models.CharField(max_length=4, choices=Side.choices)
    quantity = models.IntegerField()
    filled_quantity = models.IntegerField(default=0)
    price = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, help_text="Limit price."
    )
    average_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    trigger_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    product = models.CharField(max_length=10, blank=True, help_text="MIS/NRML/CNC")
    order_type = models.CharField(max_length=10, blank=True, help_text="MARKET/LIMIT/SL/SL-M")
    variety = models.CharField(max_length=15, blank=True, default="regular")
    copy_style = models.CharField(
        max_length=10, choices=CopyStyle.choices, default=CopyStyle.ON_FILL
    )

    broker_order_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=30, blank=True)
    observed_at = models.DateTimeField(auto_now_add=True)
    placed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(
        null=True, blank=True, help_text="When we first saw the order finished."
    )
    finalized = models.BooleanField(default=False)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

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


class CopyOrderKind(models.TextChoices):
    COPY = "copy", "Copy"
    TOPUP = "topup", "Top-up"


class CopyOrder(models.Model):
    """One order placed on a copy account for a master Trade.

    kind=copy is the main copy; kind=topup is the MARKET order that fills any
    gap left once the master's order has finished.
    """

    trade = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name="copy_orders")
    account = models.ForeignKey(
        BrokerAccount, on_delete=models.CASCADE, related_name="copy_orders"
    )
    kind = models.CharField(
        max_length=10, choices=CopyOrderKind.choices, default=CopyOrderKind.COPY
    )

    computed_quantity = models.IntegerField()
    status = models.CharField(
        max_length=10, choices=CopyOrderStatus.choices, default=CopyOrderStatus.PENDING
    )
    is_dry_run = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)

    broker_order_id = models.CharField(max_length=64, blank=True)
    # Live state of the order at the broker, refreshed every poll.
    broker_status = models.CharField(max_length=30, blank=True)
    filled_quantity = models.IntegerField(default=0)
    # What we last sent to the broker, to detect when a master modification
    # needs to be mirrored.
    placed_quantity = models.IntegerField(null=True, blank=True)
    placed_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    placed_trigger_price = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    placed_order_type = models.CharField(max_length=10, blank=True)
    modifications = models.PositiveIntegerField(default=0)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_kind = models.CharField(max_length=10, choices=ErrorKind.choices, blank=True)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["trade", "account", "kind"], name="uniq_trade_account_kind"
            ),
        ]

    def __str__(self):
        return f"CopyOrder {self.computed_quantity} -> {self.account.label} [{self.status}]"

    @property
    def is_open_at_broker(self) -> bool:
        """Placed and not yet finished at the broker."""
        return (
            self.status == CopyOrderStatus.PLACED
            and not self.is_dry_run
            and self.broker_status not in TERMINAL_STATUSES
        )


class Instrument(models.Model):
    """Cached instrument metadata (lot size, tick size) synced from the broker.

    Synced automatically every weekday morning and after the master logs in.
    Used to round master_qty x multiplier to a valid lot.
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
    TOKEN_EXPIRED = "token_expired", "Login needed"


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
