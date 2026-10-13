"""Revamp: one master at a time, copy settings on the account, settings in DB.

- Moves multiplier / zero-qty policy from CopyMapping onto the copy account and
  points CopyOrder at the copy account directly; drops CopyMapping.
- Drops PositionSnapshot (unused audit table).
- Adds AppSettings (seeded in dry-run mode, alert emails from ALERT_EMAIL_TO).
- Encrypts api_secret / access_token at rest.
- Enforces a single master (extra masters are demoted to copy).
"""

import os

import django.db.models.deletion
from django.db import migrations, models

import copytrading.fields


def forwards(apps, schema_editor):
    BrokerAccount = apps.get_model("copytrading", "BrokerAccount")
    CopyMapping = apps.get_model("copytrading", "CopyMapping")
    CopyOrder = apps.get_model("copytrading", "CopyOrder")
    AppSettings = apps.get_model("copytrading", "AppSettings")

    for m in CopyMapping.objects.all():
        fields = {"multiplier": m.multiplier, "zero_qty_policy": m.zero_qty_policy}
        if not m.active:
            fields["active"] = False
        BrokerAccount.objects.filter(pk=m.copy_id).update(**fields)
    for co in CopyOrder.objects.select_related("mapping"):
        co.account_id = co.mapping.copy_id
        co.save(update_fields=["account"])

    masters = list(BrokerAccount.objects.filter(role="master").order_by("id"))
    for extra in masters[1:]:
        extra.role = "copy"
        extra.save(update_fields=["role"])

    # Re-save so secrets get encrypted by EncryptedTextField.get_prep_value.
    for a in BrokerAccount.objects.all():
        a.save(update_fields=["api_secret", "access_token"])

    AppSettings.objects.get_or_create(
        pk=1,
        defaults={"mode": "dry_run", "alert_emails": os.environ.get("ALERT_EMAIL_TO", "")},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("copytrading", "0003_brokeraccount_copy_orders_since_copyorder_is_dry_run_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("off", "Off"), ("dry_run", "Dry run"), ("live", "Live")], default="dry_run", help_text="off = copy nothing, dry_run = simulate copies, live = place real orders.", max_length=10)),
                ("alert_emails", models.TextField(blank=True, help_text="Comma-separated addresses that receive alert emails.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "settings", "verbose_name_plural": "settings"},
        ),
        migrations.AddField(
            model_name="brokeraccount",
            name="client_id",
            field=models.CharField(blank=True, help_text="Zerodha user ID (e.g. AB1234). Filled in on first login if blank.", max_length=20),
        ),
        migrations.AddField(
            model_name="brokeraccount",
            name="multiplier",
            field=models.DecimalField(decimal_places=4, default=1, help_text="copy_qty = round_to_lot(master_qty x multiplier).", max_digits=8),
        ),
        migrations.AddField(
            model_name="brokeraccount",
            name="zero_qty_policy",
            field=models.CharField(choices=[("skip_alert", "Skip and alert"), ("skip_silent", "Skip silently"), ("round_up", "Round up to 1 lot")], default="skip_alert", max_length=20),
        ),
        migrations.AlterField(
            model_name="brokeraccount",
            name="api_secret",
            field=copytrading.fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name="brokeraccount",
            name="access_token",
            field=copytrading.fields.EncryptedTextField(blank=True),
        ),
        migrations.AddField(
            model_name="copyorder",
            name="account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="copy_orders", to="copytrading.brokeraccount"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="copyorder", name="uniq_trade_mapping"),
        migrations.RemoveField(model_name="copyorder", name="mapping"),
        migrations.AlterField(
            model_name="copyorder",
            name="account",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="copy_orders", to="copytrading.brokeraccount"),
        ),
        migrations.AddConstraint(
            model_name="copyorder",
            constraint=models.UniqueConstraint(fields=("trade", "account"), name="uniq_trade_account"),
        ),
        migrations.DeleteModel(name="CopyMapping"),
        migrations.DeleteModel(name="PositionSnapshot"),
        migrations.AddConstraint(
            model_name="brokeraccount",
            constraint=models.UniqueConstraint(condition=models.Q(("role", "master")), fields=("role",), name="single_master"),
        ),
        migrations.AlterField(
            model_name="alert",
            name="kind",
            field=models.CharField(choices=[("mismatch", "Position mismatch"), ("order_failed", "Copy order failed"), ("zero_qty", "Zero quantity skipped"), ("token_expired", "Login needed")], max_length=20),
        ),
        migrations.AlterField(
            model_name="brokeraccount",
            name="active",
            field=models.BooleanField(default=True, help_text="Disabled accounts are ignored."),
        ),
        migrations.AlterField(
            model_name="brokeraccount",
            name="label",
            field=models.CharField(help_text="Friendly name, e.g. 'Mom Zerodha'.", max_length=100),
        ),
        migrations.AlterField(
            model_name="brokeraccount",
            name="role",
            field=models.CharField(choices=[("master", "Master"), ("copy", "Copy")], default="copy", max_length=10),
        ),
        migrations.AlterField(
            model_name="trade",
            name="exchange",
            field=models.CharField(help_text="NSE/NFO/BSE/BFO", max_length=10),
        ),
    ]
