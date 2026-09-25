from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import Account, Withdrawal, Deposit, Transaction, Packages, userPackage, InvestmentPayout, PlatformSettings, CryptoRate
from datetime import timedelta
from decimal import Decimal
from unittest import mock
from user_panel.views import update_user_investments

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


class InvestmentUpdateTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = User.objects.create_user(username="investor", password="x")
        self.account = Account.objects.create(
            user=self.user,
            balance=Decimal("1000.00"),
        )
        self.package = Packages.objects.create(
            name="Six Hour Plan",
            description="Pays every six hours",
            subtype="Test",
            roi=Decimal("10.00"),
            cycle=5,
            duration=5,
            interval=6,
            min_amount=Decimal("100.00"),
            max_amount=Decimal("1000.00"),
            is_active=True,
        )

    def create_investment(self, elapsed, days=0):
        investment = userPackage.objects.create(
            user=self.account,
            package=self.package,
            amount=Decimal("100.00"),
            days=days,
        )
        userPackage.objects.filter(pk=investment.pk).update(
            date_activated=self.now - elapsed
        )
        investment.refresh_from_db()
        return investment

    def test_no_payout_before_interval_elapses(self):
        investment = self.create_investment(
            timedelta(hours=6) - timedelta(seconds=1)
        )

        with mock.patch("user_panel.views.timezone.now", return_value=self.now):
            update_user_investments(userPackage.objects.filter(pk=investment.pk))

        self.account.refresh_from_db()
        investment.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertEqual(investment.days, 0)
        self.assertFalse(Transaction.objects.filter(tx_type="ROI").exists())

    def test_missed_interval_cycles_are_paid_together(self):
        investment = self.create_investment(timedelta(hours=12))

        with mock.patch("user_panel.views.timezone.now", return_value=self.now):
            update_user_investments(userPackage.objects.filter(pk=investment.pk))

        self.account.refresh_from_db()
        investment.refresh_from_db()
        payouts = list(Transaction.objects.filter(tx_type="ROI").order_by("date"))
        self.assertEqual(self.account.balance, Decimal("1020.00"))
        self.assertEqual([payout.amount for payout in payouts], [Decimal("10.00"), Decimal("10.00")])
        self.assertEqual(investment.days, 2)
        self.assertTrue(investment.is_active)

    def test_final_cycle_returns_principal_only_once(self):
        self.package.cycle = 2
        self.package.save(update_fields=["cycle"])
        investment = self.create_investment(timedelta(hours=12))

        with mock.patch("user_panel.views.timezone.now", return_value=self.now):
            update_user_investments(userPackage.objects.filter(pk=investment.pk))
            update_user_investments(userPackage.objects.filter(pk=investment.pk))

        self.account.refresh_from_db()
        investment.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1120.00"))
        self.assertEqual(investment.days, 2)
        self.assertFalse(investment.is_active)
        self.assertEqual(Transaction.objects.filter(tx_type="ROI").count(), 2)
        self.assertEqual(Transaction.objects.filter(tx_type="PRINCIPAL").count(), 1)
        self.assertEqual(InvestmentPayout.objects.filter(investment=investment).count(), 3)

    def test_snapshot_investment_pays_without_package_row(self):
        investment = userPackage.objects.create(
            user=self.account,
            package=None,
            amount=Decimal("100.00"),
            roi=Decimal("10.00"),
            cycle=2,
            duration=2,
            interval=1,
        )
        userPackage.objects.filter(pk=investment.pk).update(
            date_activated=self.now - timedelta(hours=1)
        )

        with mock.patch("user_panel.views.timezone.now", return_value=self.now):
            update_user_investments(userPackage.objects.filter(pk=investment.pk))

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1010.00"))
        self.assertEqual(InvestmentPayout.objects.filter(investment=investment).count(), 1)

    def test_multiple_investments_do_not_overwrite_each_other(self):
        first = self.create_investment(timedelta(hours=6))
        second = self.create_investment(timedelta(hours=12))

        with mock.patch("user_panel.views.timezone.now", return_value=self.now):
            update_user_investments(
                userPackage.objects.filter(pk__in=[first.pk, second.pk])
            )

        self.account.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1030.00"))
        self.assertEqual(first.days, 1)
        self.assertEqual(second.days, 2)


class WithdrawTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bob", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("500.00"))
        PlatformSettings.load().wallet_address = "0x" + "1" * 40
        PlatformSettings.load().save(update_fields=["wallet_address"])
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
        platform = PlatformSettings.load()
        platform.wallet_address = "0x" + "1" * 40
        platform.save(update_fields=["wallet_address"])
        self.client = Client()
        self.client.force_login(self.user)

    def test_deposit_request_creates_pending(self):
        r = self.client.post("/dashboard/deposit/", {"wallet_type": "USDT", "amount": "200", "tx_hash": "0x" + "a" * 64})
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

    def test_inactive_session_is_logged_out(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.get("/dashboard/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/dashboard/").status_code, 302)


class DepositValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="deposit-validator", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("0.00"))
        platform = PlatformSettings.load()
        platform.wallet_address = "0x" + "1" * 40
        platform.save(update_fields=["wallet_address"])
        self.client = Client()
        self.client.force_login(self.user)

    def test_wrong_wallet_is_rejected(self):
        response = self.client.post(
            "/dashboard/deposit/",
            {
                "wallet_type": "BTC",
                "amount": "20.00",
                "tx_hash": "0x" + "a" * 64,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_account_wallet_mismatch_is_rejected(self):
        self.account.account_type = "BTC"
        self.account.save(update_fields=["account_type"])

        response = self.client.post(
            "/dashboard/deposit/",
            {
                "wallet_type": "USDT",
                "amount": "20.00",
                "tx_hash": "0x" + "a" * 64,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_invalid_hash_is_rejected(self):
        response = self.client.post(
            "/dashboard/deposit/",
            {
                "wallet_type": "USDT",
                "amount": "20.00",
                "tx_hash": "not-a-transaction-hash",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_duplicate_hash_is_idempotent(self):
        payload = {
            "wallet_type": "USDT",
            "amount": "20.00",
            "tx_hash": "0x" + "a" * 64,
        }

        first = self.client.post("/dashboard/deposit/", payload)
        second = self.client.post(
            "/dashboard/deposit/",
            {**payload, "tx_hash": payload["tx_hash"].upper()},
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Deposit.objects.count(), 1)
        self.assertEqual(Transaction.objects.filter(tx_type="DEPOSIT").count(), 1)

    def test_amount_is_rounded_consistently(self):
        self.client.post(
            "/dashboard/deposit/",
            {
                "wallet_type": "USDT",
                "amount": "1.005",
                "tx_hash": "0x" + "b" * 64,
            },
        )

        deposit = Deposit.objects.get()
        transaction = Transaction.objects.get(tx_type="DEPOSIT")
        self.assertEqual(deposit.amount, Decimal("1.01"))
        self.assertEqual(transaction.amount, Decimal("1.01"))


class ActivationSnapshotTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="snapshot-user", password="x")
        self.account = Account.objects.create(
            user=self.user,
            balance=Decimal("500.00"),
        )
        self.package = Packages.objects.create(
            name="Snapshot Plan",
            description="Snapshot package",
            subtype="Test",
            roi=Decimal("10.00"),
            cycle=3,
            duration=72,
            interval=6,
            min_amount=Decimal("100.00"),
            max_amount=Decimal("1000.00"),
            is_active=True,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_activation_snapshots_terms_before_package_edit(self):
        response = self.client.post(
            f"/dashboard/package/activate/{self.package.id}/",
            {"amount": "100.00"},
        )

        self.assertEqual(response.status_code, 302)
        investment = userPackage.objects.get()
        self.assertEqual(investment.roi, Decimal("10.00"))
        self.assertEqual(investment.cycle, 3)
        self.assertEqual(investment.duration, 72)
        self.assertEqual(investment.interval, 6)

        self.package.roi = Decimal("20.00")
        self.package.cycle = 5
        self.package.duration = 30
        self.package.interval = 1
        self.package.save(update_fields=["roi", "cycle", "duration", "interval"])
        investment.refresh_from_db()

        self.assertEqual(investment.roi, Decimal("10.00"))
        self.assertEqual(investment.cycle, 3)
        self.assertEqual(investment.duration, 72)
        self.assertEqual(investment.interval, 6)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("400.00"))
