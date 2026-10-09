from django.db import models
from django.contrib.auth.models import User, AbstractUser
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
import uuid
import math

# Create your models here.
class PlatformSettings(models.Model):
    wallet_type = models.CharField(max_length=50, default="USDT")
    wallet_address = models.CharField(max_length=150, default="")
    referral_reward = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("25.00"))
    date_updated = models.DateTimeField(auto_now=True, auto_now_add=False)

    class Meta:
        verbose_name = "Platform settings"
        verbose_name_plural = "Platform settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # always the same row
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # don't allow deleting the row

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Platform settings"

class PaymentRail(models.Model):
    key = models.CharField(max_length=50, unique=True)
    symbol = models.CharField(max_length=10)
    network = models.CharField(max_length=20)
    label = models.CharField(max_length=50)
    is_active = models.BooleanField(default=False)
    address = models.CharField(max_length=150, blank=True, default="")
    min_deposit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    max_deposit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    min_withdraw = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    max_withdraw = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    display_order = models.IntegerField(default=0)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "key"]
        verbose_name = "Payment rail"
        verbose_name_plural = "Payment rails"

    @classmethod
    def rails(cls):
        return cls.objects.all().order_by("display_order", "key")

    @classmethod
    def active_rails(cls):
        return cls.rails().filter(is_active=True)

    def __str__(self):
        return self.label or self.key


def legacy_rail_for_symbol(symbol):
    # Imported here rather than at module scope on purpose: core.rails imports
    # core.models, so a module-level import in this file would be circular.
    from .rails import LEGACY_PREFIX

    normalized = (symbol or "").strip().upper()
    if not normalized:
        return None
    key = f"{LEGACY_PREFIX}{normalized}"
    rail, _ = PaymentRail.objects.get_or_create(
        key=key,
        defaults={
            "symbol": normalized[:10],
            "network": "LEGACY",
            "label": f"{normalized} (retired network)",
            "is_active": False,
            "address": "",
            "display_order": 9999,
        },
    )
    return rail

class User(AbstractUser):
    user_id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    phone_number = models.CharField(null=True, max_length=30)

class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.OneToOneField(User, on_delete=models.PROTECT)
    account_type = models.CharField(max_length=50, default="USDT")
    
    wallet_address = models.CharField(max_length=150, null=True)
    balance = models.DecimalField(max_digits=100, decimal_places=2, default=0.00)
    date_created = models.DateTimeField(auto_now=False, auto_now_add=True, null=True)
    date_updated = models.DateTimeField(auto_now=True, auto_now_add=False, null=True)
    referral_code = models.UUIDField(unique=True, default=uuid.uuid4, null=True)
    preferred_rail = models.ForeignKey(PaymentRail, null=True, blank=True, on_delete=models.SET_NULL, related_name="accounts")


class Wallet(models.Model):
    class Asset(models.TextChoices):
        USDT = "USDT", "USDT"
        ETH = "ETH", "Ethereum"
        BTC = "BTC", "Bitcoin"
        SOL = "SOL", "Solana"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="wallets")
    asset = models.CharField(max_length=10, choices=Asset.choices)
    address = models.CharField(max_length=150, blank=True, default="")
    balance = models.DecimalField(max_digits=36, decimal_places=18, default=Decimal("0"))
    is_active = models.BooleanField(default=False)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "asset"], name="unique_user_wallet_asset"),
        ]
        ordering = ["asset"]

    def __str__(self):
        return f"{self.user.username} {self.asset} wallet"


class Packages(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=50)
    description = models.TextField(null=True)
    subtype = models.CharField(max_length=50)
    roi = models.DecimalField(max_digits=5, decimal_places=2)
    cycle = models.IntegerField()
    duration = models.IntegerField()
    interval = models.IntegerField()
    min_amount = models.DecimalField(max_digits=18, decimal_places=2)
    max_amount = models.DecimalField(max_digits=18, decimal_places=2)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

class Transaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="transactions")
    tx_type = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(max_length=10, default="COMPLETED")
    reference = models.UUIDField(default=uuid.uuid4)
    related_id = models.UUIDField(null=True, blank=True)
    description = models.TextField(default="")
    date = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self):
        return f"{self.tx_type} {self.amount} ({self.status})"

class Referral(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    referrer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="referrals_made")
    referred = models.ForeignKey(User, on_delete=models.PROTECT, related_name="referred_by_ref")
    reward = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    date = models.DateTimeField(default=timezone.now, editable=False)

class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    admin = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=150)
    detail = models.CharField(max_length=255, blank=True, default="")
    date = models.DateTimeField(default=timezone.now, editable=False)

class Deposit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="deposits")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    wallet_type = models.CharField(max_length=50, default="USDT")
    tx_hash = models.CharField(max_length=150, blank=True, default="")
    tx_hash_key = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        editable=False,
        unique=True,
    )
    status = models.CharField(max_length=10, default="PENDING")
    date_requested = models.DateTimeField(default=timezone.now, editable=False)
    date_resolved = models.DateTimeField(null=True, blank=True)
    rail = models.ForeignKey(PaymentRail, null=True, on_delete=models.PROTECT, related_name="deposits")
    amount_coin = models.DecimalField(max_digits=36, decimal_places=18, null=True, blank=True)
    rate_used = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)

class Withdrawal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    wallet_type = models.CharField(max_length=50)
    address = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    description = models.TextField(default="")
    status = models.CharField(max_length=10, default="PENDING")
    date_requested = models.DateTimeField(auto_now=False, auto_now_add=True)
    date_approved = models.DateTimeField(null=True, blank=True)
    rail = models.ForeignKey(PaymentRail, null=True, on_delete=models.PROTECT, related_name="withdrawals")
    amount_coin = models.DecimalField(max_digits=36, decimal_places=18, null=True, blank=True)
    rate_used = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)

class userPackage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(Account, on_delete=models.PROTECT)
    package = models.ForeignKey(Packages, on_delete=models.PROTECT, null=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    roi = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cycle = models.IntegerField(null=True, blank=True)
    duration = models.IntegerField(null=True, blank=True)
    interval = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    date_activated = models.DateTimeField(auto_now=False, auto_now_add=True)
    days = models.IntegerField(default=0)

    def effective_cycle(self):
        if self.cycle is not None:
            return self.cycle
        return self.package.cycle if self.package else 0

    def effective_interval(self):
        if self.interval is not None:
            return self.interval
        return self.package.interval if self.package else 0

    def effective_roi(self):
        if self.roi is not None:
            return self.roi
        return self.package.roi if self.package else Decimal("0.00")

    def parse_progress(self):
        cycle = self.effective_cycle()
        if cycle <= 0:
            return 0
        return round(self.days / cycle * 100)

    def cycles_left(self):
        return max(self.effective_cycle() - self.days, 0)

    def perCycle(self):
        return ((self.amount * self.effective_roi()) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def total_projected(self):
        return self.amount + (self.perCycle() * self.effective_cycle())


class InvestmentPayout(models.Model):
    class Kind(models.TextChoices):
        ROI = "ROI", "ROI"
        PRINCIPAL = "PRINCIPAL", "Principal"

    investment = models.ForeignKey(
        userPackage,
        on_delete=models.PROTECT,
        related_name="payouts",
    )
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="investment_payout",
    )
    kind = models.CharField(max_length=9, choices=Kind.choices)
    cycle_number = models.PositiveIntegerField(default=0)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["investment", "kind", "cycle_number"],
                name="unique_investment_payout",
            )
        ]

class Support(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(Account, on_delete=models.CASCADE)
    topic = models.CharField(max_length=50)
    subject = models.CharField(max_length=50)
    message = models.TextField()
    status = models.CharField(max_length=10, default="UNREAD")
    date_sent = models.DateTimeField(auto_now=False, auto_now_add=True)

class CryptoRate(models.Model):
    symbol = models.CharField(max_length=10, primary_key=True)
    usd_price = models.DecimalField(max_digits=20, decimal_places=8)
    updated = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self):
        return f"{self.symbol} = ${self.usd_price}"
