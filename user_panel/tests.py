from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import Account, Withdrawal, Deposit, Transaction, Packages, userPackage, CryptoRate
from decimal import Decimal

User = get_user_model()


class RatesRenderTest(TestCase):
    def setUp(self):
        now = timezone.now()
        for sym, price in [("USDT", "1.00"), ("BTC", "60000"), ("ETH", "3000"), ("SOL", "150")]:
            CryptoRate.objects.update_or_create(symbol=sym, defaults={"usd_price": Decimal(price), "updated": now})
        self.user = User.objects.create_user(username="eve", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("30000.00"))
        self.client = Client()
        self.client.force_login(self.user)

    def test_deposit_page_renders_rates(self):
        r = self.client.get("/dashboard/deposit/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Live rates")
        self.assertContains(r, '"BTC": 60000.0')

    def test_withdraw_page_renders_rates(self):
        r = self.client.get("/dashboard/withdraw/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Live rates")
        self.assertContains(r, '"BTC": 60000.0')

    def test_dashboard_shows_market_panel(self):
        r = self.client.get("/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Market Rates")
        self.assertContains(r, "BTC")


class WithdrawTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bob", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("500.00"))
        self.client = Client()
        self.client.force_login(self.user)

    def test_below_minimum_rejected(self):
        r = self.client.post("/dashboard/withdraw/", {"wallet_type": "USDT", "amount": "10", "address": "abc"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Withdrawal.objects.count(), 0)

    def test_valid_withdraw_holds_funds_and_logs(self):
        r = self.client.post("/dashboard/withdraw/", {"wallet_type": "USDT", "amount": "100.50", "address": "abc"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Withdrawal.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("399.50"))
        tx = Transaction.objects.get(user=self.user, tx_type="WITHDRAWAL")
        self.assertEqual(tx.amount, Decimal("-100.50"))
        self.assertEqual(tx.status, "PENDING")
        self.assertEqual(tx.related_id, Withdrawal.objects.first().id)

    def test_overspend_rejected(self):
        self.client.post("/dashboard/withdraw/", {"wallet_type": "USDT", "amount": "9999", "address": "abc"})
        self.assertEqual(Withdrawal.objects.count(), 0)


class DepositTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="carol", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("0.00"))
        self.client = Client()
        self.client.force_login(self.user)

    def test_deposit_request_creates_pending(self):
        r = self.client.post("/dashboard/deposit/", {"wallet_type": "USDT", "amount": "200", "tx_hash": "0xabc"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Deposit.objects.filter(user=self.user, status="PENDING").count(), 1)
        tx = Transaction.objects.get(user=self.user, tx_type="DEPOSIT")
        self.assertEqual(tx.status, "PENDING")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))


class TransactionsPageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dave", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("77.00"))
        self.client = Client()
        self.client.force_login(self.user)

    def test_page_renders_user_transactions(self):
        Transaction.objects.create(user=self.user, tx_type="ROI", amount=Decimal("5.00"), status="COMPLETED")
        r = self.client.get("/dashboard/transactions/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Roi")
        self.assertContains(r, "+$5.00")