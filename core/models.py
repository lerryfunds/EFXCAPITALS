from django.db import models
from django.contrib.auth.models import User, AbstractUser
import uuid

# Create your models here.
class PlatformSettings(models.Model):
    wallet_type = models.CharField(max_length=50)
    wallet_address = models.CharField(max_length=150)
    date_updated = models.DateTimeField(auto_now=True, auto_now_add=False)

class User(AbstractUser):
    user_id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)

class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    account_type = models.CharField(max_length=50, default="USDT")
    wallet_address = models.CharField(max_length=50, null=True)
    balance = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    date_created = models.DateTimeField(auto_now=False, auto_now_add=True, null=True)
    date_updated = models.DateTimeField(auto_now=True, auto_now_add=False, null=True)
    

class Packages(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=50)
    description = models.TextField(null=True)
    subtype = models.CharField(max_length=50)
    roi = models.DecimalField(max_digits=5, decimal_places=2)
    cycle = models.IntegerField()
    duration = models.IntegerField()
    interval = models.IntegerField()
    min_amount = models.DecimalField(max_digits=5, decimal_places=2)
    max_amount = models.DecimalField(max_digits=5, decimal_places=2)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

class Transaction(models.Model):
    pass

class Referral(models.Model):
    pass

class SupportMessage(models.Model):
    pass

