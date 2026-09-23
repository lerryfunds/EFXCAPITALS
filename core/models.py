from django.db import models
from django.contrib.auth.models import User, AbstractUser
from django.utils import timezone
from decimal import Decimal
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

class User(AbstractUser):
    user_id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    phone_number = models.CharField(null=True, max_length=30)

class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    account_type = models.CharField(max_length=50, default="USDT")
    
    wallet_address = models.CharField(max_length=50, null=True)
    balance = models.DecimalField(max_digits=100, decimal_places=2, default=0.00)
    date_created = models.DateTimeField(auto_now=False, auto_now_add=True, null=True)
    date_updated = models.DateTimeField(auto_now=True, auto_now_add=False, null=True)
    referral_code = models.UUIDField(unique=True, default=uuid.uuid4, null=True)
    

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
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")
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
    referrer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="referrals_made")
    referred = models.ForeignKey(User, on_delete=models.CASCADE, related_name="referred_by_ref")
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
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="deposits")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    wallet_type = models.CharField(max_length=50, default="USDT")
    tx_hash = models.CharField(max_length=150, blank=True, default="")
    status = models.CharField(max_length=10, default="PENDING")
    date_requested = models.DateTimeField(default=timezone.now, editable=False)
    date_resolved = models.DateTimeField(null=True, blank=True)

class Withdrawal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    wallet_type = models.CharField(max_length=50)
    address = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    description = models.TextField(default="")
    status = models.CharField(max_length=10, default="PENDING")
    date_requested = models.DateTimeField(auto_now=False, auto_now_add=True)
    date_approved = models.DateTimeField(auto_now=True, auto_now_add=False)

class userPackage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(Account, on_delete=models.CASCADE)
    package = models.ForeignKey(Packages, on_delete=models.CASCADE, null=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    is_active = models.BooleanField(default=True)
    date_activated = models.DateTimeField(auto_now=False, auto_now_add=True)
    days = models.IntegerField(default=0)

    def parse_progress(self):
        return round(self.days / self.package.cycle * 100)

    def cycles_left(self):
        return self.package.cycle - self.days

    def perCycle(self):
        return round((self.amount * self.package.roi), 2)

    def total_projected(self):
        return (self.package.min_amount * self.package.roi * self.package.cycle) + self.amount

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