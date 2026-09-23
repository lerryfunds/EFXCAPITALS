from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from core.models import Account, Withdrawal, Deposit, Transaction, Support, AuditLog, PlatformSettings
from decimal import Decimal

User = get_user_model()


class AdminGuardTest(TestCase):
    def test_anonymous_redirected_from_panel(self):
        for url in ["/admin-secure-portal/", "/admin-secure-portal/deposits/", "/admin-secure-portal/logs/"]:
            r = Client().get(url)
            self.assertEqual(r.status_code, 302)


class AdminDepositTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="erin", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("0.00"))
        self.admin = User.objects.create_superuser(username="boss", password="x")
        self.client = Client()
        self.client.force_login(self.admin)

    def test_approve_credits_balance_and_completes_transaction(self):
        dep = Deposit.objects.create(user=self.user, amount=Decimal("200.00"), wallet_type="USDT")
        Transaction.objects.create(user=self.user, tx_type="DEPOSIT", amount=Decimal("200.00"), status="PENDING", related_id=dep.id)

        r = self.client.get(f"/admin-secure-portal/deposits/approve/{dep.id}/")
        self.assertEqual(r.status_code, 302)
        dep.refresh_from_db()
        self.assertEqual(dep.status, "APPROVED")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("200.00"))
        tx = Transaction.objects.get(user=self.user, tx_type="DEPOSIT", related_id=dep.id)
        self.assertEqual(tx.status, "COMPLETED")
        self.assertTrue(AuditLog.objects.filter(action="Approved deposit").exists())

    def test_reject_does_not_credit(self):
        dep = Deposit.objects.create(user=self.user, amount=Decimal("50.00"), wallet_type="USDT")
        self.client.get(f"/admin-secure-portal/deposits/reject/{dep.id}/")
        dep.refresh_from_db()
        self.assertEqual(dep.status, "REJECTED")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertTrue(AuditLog.objects.filter(action="Rejected deposit").exists())


class AdminWithdrawalTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="fiona", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("500.00"))
        self.admin = User.objects.create_superuser(username="boss2", password="x")
        self.client = Client()
        self.client.force_login(self.admin)

    def test_reject_refunds_and_updates_transaction(self):
        w = Withdrawal.objects.create(user=self.user, wallet_type="USDT", address="abc", amount=Decimal("50.00"))
        self.account.balance -= w.amount
        self.account.save()
        Transaction.objects.create(user=self.user, tx_type="WITHDRAWAL", amount=-w.amount, status="PENDING", related_id=w.id)

        self.client.get(f"/admin-secure-portal/withdrawals/reject/{w.id}/")
        w.refresh_from_db()
        self.assertEqual(w.status, "REJECTED")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("500.00"))
        self.assertEqual(Transaction.objects.get(user=self.user, tx_type="WITHDRAWAL", related_id=w.id).status, "REJECTED")

    def test_approve_completes_transaction(self):
        w = Withdrawal.objects.create(user=self.user, wallet_type="USDT", address="abc", amount=Decimal("50.00"))
        self.account.balance -= w.amount
        self.account.save()
        Transaction.objects.create(user=self.user, tx_type="WITHDRAWAL", amount=-w.amount, status="PENDING", related_id=w.id)

        self.client.get(f"/admin-secure-portal/withdrawals/approve/{w.id}/")
        w.refresh_from_db()
        self.assertEqual(w.status, "APPROVED")
        self.assertEqual(Transaction.objects.get(user=self.user, tx_type="WITHDRAWAL", related_id=w.id).status, "COMPLETED")


class AdminSupportTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="grace", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("0.00"))
        self.admin = User.objects.create_superuser(username="boss3", password="x")
        self.support = Support.objects.create(user=self.account, topic="Other", subject="Hi", message="Need help")

    def test_page_admin_only(self):
        self.assertEqual(Client().get("/admin-secure-portal/support/").status_code, 302)
        c = Client()
        c.force_login(self.admin)
        r = c.get("/admin-secure-portal/support/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Need help")

    def test_mark_status(self):
        c = Client()
        c.force_login(self.admin)
        c.get(f"/admin-secure-portal/support/read/{self.support.id}/")
        self.support.refresh_from_db()
        self.assertEqual(self.support.status, "READ")
        c.get(f"/admin-secure-portal/support/replied/{self.support.id}/")
        self.support.refresh_from_db()
        self.assertEqual(self.support.status, "REPLIED")


class AuditLogPageTest(TestCase):
    def test_logs_page(self):
        admin = User.objects.create_superuser(username="heidi", password="x")
        AuditLog.objects.create(admin=admin, action="Tested action", detail="hello")
        c = Client()
        c.force_login(admin)
        r = c.get("/admin-secure-portal/logs/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Tested action")


class AdminSettingsTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="ivan", password="x")
        self.client = Client()
        self.client.force_login(self.admin)
        PlatformSettings.load().refresh_from_db()

    def test_update_settings(self):
        r = self.client.post("/admin-secure-portal/settings/", {
            "wallet-type": "TRON",
            "wallet-address": "TQx.....xyz",
            "referral-reward": "40.00",
        })
        self.assertEqual(r.status_code, 302)
        platform = PlatformSettings.load()
        self.assertEqual(platform.wallet_type, "TRON")
        self.assertEqual(platform.wallet_address, "TQx.....xyz")
        self.assertEqual(platform.referral_reward, Decimal("40.00"))
        self.assertTrue(AuditLog.objects.filter(action="Updated platform settings").exists())

    def test_page_admin_only(self):
        self.assertEqual(Client().get("/admin-secure-portal/settings/").status_code, 302)
        r = self.client.get("/admin-secure-portal/settings/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Referral Reward")