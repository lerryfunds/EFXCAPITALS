# Generated manually after local Python launcher was unavailable.

import uuid
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_payment_rail"),
    ]

    operations = [
        migrations.CreateModel(
            name="Wallet",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "asset",
                    models.CharField(
                        choices=[
                            ("USDT", "USDT"),
                            ("ETH", "Ethereum"),
                            ("BTC", "Bitcoin"),
                            ("SOL", "Solana"),
                        ],
                        max_length=10,
                    ),
                ),
                ("address", models.CharField(blank=True, default="", max_length=150)),
                ("balance", models.DecimalField(decimal_places=18, default=Decimal("0"), max_digits=36)),
                ("is_active", models.BooleanField(default=False)),
                ("date_created", models.DateTimeField(auto_now_add=True)),
                ("date_updated", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="wallets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["asset"],
            },
        ),
        migrations.AddConstraint(
            model_name="wallet",
            constraint=models.UniqueConstraint(fields=("user", "asset"), name="unique_user_wallet_asset"),
        ),
    ]
