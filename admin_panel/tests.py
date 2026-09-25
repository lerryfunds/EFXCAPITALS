from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from core.models import Account, Packages, Withdrawal, Deposit, Transaction, Support, AuditLog, PlatformSettings
from decimal import Decimal
from unittest.mock import patch

User = get_user_model()


class AdminGuardTest(TestCase):
    def test_anonymous_redirected_from_panel(self):
        for url in ["/admin-secure-portal/", "/admin-secure-portal/deposits/", "/admin-secure-portal/logs/"]:
            r = Client().get(url)
            self.assertEqual(r.status_code, 302)


class AdminPageRenderingTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="page-user", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("0.00"))
        self.package = Packages.objects.create(
            name="Page Package",
            description="Page package",
            subtype="Fixed",
            roi=Decimal("5.00"),
            cycle=1,
            duration=30,
            interval=1,
            min_amount=Decimal("100.00"),
            max_amount=Decimal("1000.00"),
        )
        self.admin = User.objects.create_superuser(username="page-admin", password="x")
        self.client = Client()
        self.client.force_login(self.admin)

    def test_user_list_create_and_edit_render_with_get(self):
        urls = [
            "/admin-secure-portal/users/",
            "/admin-secure-portal/user/create/",
            f"/admin-secure-portal/user/edit/{self.user.user_id}/",
        ]
        rates = {"USDT": Decimal("1.00"), "BTC": Decimal("1.00"), "ETH": Decimal("1.00"), "SOL": Decimal("1.00")}
        with patch("admin_panel.views.get_rates", return_value=rates):
            for url in urls:
                with self.subTest(url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_package_list_create_and_edit_render_with_get(self):
        urls = [
            "/admin-secure-portal/packages/",
            "/admin-secure-portal/package/create/",
            f"/admin-secure-portal/package/edit/{self.package.id}",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class AdminUserActionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="action-user", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("0.00"))
        self.admin = User.objects.create_superuser(username="user-action-admin", password="x")
        self.client = Client()
        self.client.force_login(self.admin)

    def test_toggle_rejects_get(self):
        r = self.client.get(f"/admin-secure-portal/user/toggle_activity/{self.user.user_id}/")
        self.assertEqual(r.status_code, 405)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertFalse(AuditLog.objects.filter(action="Toggled user activity").exists())

    def test_toggle_cannot_deactivate_current_admin(self):
        response = self.client.post(
            f"/admin-secure-portal/user/toggle_activity/{self.admin.user_id}/"
        )

        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_toggle_changes_activity_with_post(self):
        r = self.client.post(f"/admin-secure-portal/user/toggle_activity/{self.user.user_id}/")
        self.assertEqual(r.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(AuditLog.objects.filter(action="Toggled user activity").exists())

    def test_delete_rejects_get(self):
        r = self.client.get(f"/admin-secure-portal/user/delete/{self.user.user_id}/")
        self.assertEqual(r.status_code, 405)
        self.assertTrue(User.objects.filter(user_id=self.user.user_id).exists())
        self.assertTrue(Account.objects.filter(id=self.account.id).exists())
        self.assertFalse(AuditLog.objects.filter(action="Deleted user").exists())

    def test_delete_deactivates_user_with_post(self):
        r = self.client.post(f"/admin-secure-portal/user/delete/{self.user.user_id}/")
        self.assertEqual(r.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(Account.objects.filter(id=self.account.id).exists())
        self.assertTrue(AuditLog.objects.filter(action="Deactivated user").exists())


class AdminPackageActionTest(TestCase):
    def setUp(self):
        self.package = Packages.objects.create(
            name="Gold",
            description="Gold package",
            subtype="Fixed",
            roi=Decimal("5.00"),
            cycle=1,
            duration=30,
            interval=1,
            min_amount=Decimal("100.00"),
            max_amount=Decimal("1000.00"),
        )
        self.admin = User.objects.create_superuser(username="package-action-admin", password="x")
        self.client = Client()
        self.client.force_login(self.admin)

    def test_toggle_rejects_get(self):
        r = self.client.get(f"/admin-secure-portal/package/toggle/is_active/{self.package.id}/")
        self.assertEqual(r.status_code, 405)
        self.package.refresh_from_db()
        self.assertTrue(self.package.is_active)
        self.assertFalse(AuditLog.objects.filter(action="Toggled package").exists())

    def test_toggle_changes_activity_with_post(self):
        r = self.client.post(f"/admin-secure-portal/package/toggle/is_active/{self.package.id}/")
        self.assertEqual(r.status_code, 302)
        self.package.refresh_from_db()
        self.assertFalse(self.package.is_active)
        self.assertTrue(AuditLog.objects.filter(action="Toggled package").exists())

    def test_delete_rejects_get(self):
        r = self.client.get(f"/admin-secure-portal/package/delete/{self.package.id}")
        self.assertEqual(r.status_code, 405)
        self.assertTrue(Packages.objects.filter(id=self.package.id).exists())
        self.assertFalse(AuditLog.objects.filter(action="Deleted package").exists())

    def test_delete_removes_package_with_post(self):
        r = self.client.post(f"/admin-secure-portal/package/delete/{self.package.id}")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Packages.objects.filter(id=self.package.id).exists())
        self.assertTrue(AuditLog.objects.filter(action="Deleted package").exists())


class AdminDepositTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="erin", password="x")
        self.account = Account.objects.create(user=self.user, balance=Decimal("0.00"))
        self.admin = User.objects.create_superuser(username="boss", password="x")
        self.client = Client()
        self.client.force_login(self.admin)

    def test_approve_credits_balance_and_completes_transaction(self):
        dep = Deposit.objects.create(user=self.user, amount=Decimal("200.00"), wallet_type="USDT", tx_hash="0x" + "a" * 64)
        Transaction.objects.create(user=self.user, tx_type="DEPOSIT", amount=Decimal("200.00"), status="PENDING", related_id=dep.id)

        r = self.client.post(f"/admin-secure-portal/deposits/approve/{dep.id}/")
        self.assertEqual(r.status_code, 302)
        dep.refresh_from_db()
        self.assertEqual(dep.status, "APPROVED")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("200.00"))
        tx = Transaction.objects.get(user=self.user, tx_type="DEPOSIT", related_id=dep.id)
        self.assertEqual(tx.status, "COMPLETED")
        self.assertTrue(AuditLog.objects.filter(action="Approved deposit").exists())

    def test_approve_rejects_get(self):
        dep = Deposit.objects.create(user=self.user, amount=Decimal("200.00"), wallet_type="USDT", tx_hash="0x" + "a" * 64)
        r = self.client.get(f"/admin-secure-portal/deposits/approve/{dep.id}/")
        self.assertEqual(r.status_code, 405)
        dep.refresh_from_db()
        self.assertEqual(dep.status, "PENDING")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertFalse(AuditLog.objects.filter(action="Approved deposit").exists())

    def test_reject_does_not_credit(self):
        dep = Deposit.objects.create(user=self.user, amount=Decimal("50.00"), wallet_type="USDT", tx_hash="0x" + "b" * 64)
        self.client.post(f"/admin-secure-portal/deposits/reject/{dep.id}/")
        dep.refresh_from_db()
        self.assertEqual(dep.status, "REJECTED")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertTrue(AuditLog.objects.filter(action="Rejected deposit").exists())

    def test_reject_rejects_get(self):
        dep = Deposit.objects.create(user=self.user, amount=Decimal("50.00"), wallet_type="USDT", tx_hash="0x" + "b" * 64)
        r = self.client.get(f"/admin-secure-portal/deposits/reject/{dep.id}/")
        self.assertEqual(r.status_code, 405)
        dep.refresh_from_db()
        self.assertEqual(dep.status, "PENDING")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertFalse(AuditLog.objects.filter(action="Rejected deposit").exists())


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

        self.client.post(f"/admin-secure-portal/withdrawals/reject/{w.id}/")
        w.refresh_from_db()
        self.assertEqual(w.status, "REJECTED")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("500.00"))
        self.assertEqual(Transaction.objects.get(user=self.user, tx_type="WITHDRAWAL", related_id=w.id).status, "REJECTED")

    def test_reject_rejects_get(self):
        w = Withdrawal.objects.create(user=self.user, wallet_type="USDT", address="abc", amount=Decimal("50.00"))
        r = self.client.get(f"/admin-secure-portal/withdrawals/reject/{w.id}/")
        self.assertEqual(r.status_code, 405)
        w.refresh_from_db()
        self.assertEqual(w.status, "PENDING")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("500.00"))
        self.assertFalse(AuditLog.objects.filter(action="Rejected withdrawal").exists())

    def test_approve_completes_transaction(self):
        w = Withdrawal.objects.create(user=self.user, wallet_type="USDT", address="abc", amount=Decimal("50.00"))
        self.account.balance -= w.amount
        self.account.save()
        Transaction.objects.create(user=self.user, tx_type="WITHDRAWAL", amount=-w.amount, status="PENDING", related_id=w.id)

        self.client.post(f"/admin-secure-portal/withdrawals/approve/{w.id}/")
        w.refresh_from_db()
        self.assertEqual(w.status, "APPROVED")
        self.assertEqual(Transaction.objects.get(user=self.user, tx_type="WITHDRAWAL", related_id=w.id).status, "COMPLETED")

    def test_approve_rejects_get(self):
        w = Withdrawal.objects.create(user=self.user, wallet_type="USDT", address="abc", amount=Decimal("50.00"))
        r = self.client.get(f"/admin-secure-portal/withdrawals/approve/{w.id}/")
        self.assertEqual(r.status_code, 405)
        w.refresh_from_db()
        self.assertEqual(w.status, "PENDING")
        self.assertFalse(AuditLog.objects.filter(action="Approved withdrawal").exists())


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
        c.post(f"/admin-secure-portal/support/read/{self.support.id}/")
        self.support.refresh_from_db()
        self.assertEqual(self.support.status, "READ")
        c.post(f"/admin-secure-portal/support/replied/{self.support.id}/")
        self.support.refresh_from_db()
        self.assertEqual(self.support.status, "REPLIED")

    def test_mark_read_rejects_get(self):
        c = Client()
        c.force_login(self.admin)
        r = c.get(f"/admin-secure-portal/support/read/{self.support.id}/")
        self.assertEqual(r.status_code, 405)
        self.support.refresh_from_db()
        self.assertEqual(self.support.status, "UNREAD")
        self.assertFalse(AuditLog.objects.filter(action="Support marked read").exists())

    def test_mark_replied_rejects_get(self):
        c = Client()
        c.force_login(self.admin)
        r = c.get(f"/admin-secure-portal/support/replied/{self.support.id}/")
        self.assertEqual(r.status_code, 405)
        self.support.refresh_from_db()
        self.assertEqual(self.support.status, "UNREAD")
        self.assertFalse(AuditLog.objects.filter(action="Support marked replied").exists())


class AuditLogPageTest(TestCase):
    def test_logs_page(self):
        admin = User.objects.create_superuser(username="heidi", password="x")
        AuditLog.objects.create(admin=admin, action="Tested action", detail="hello")
        c = Client()
        c.force_login(admin)
        r = c.get("/admin-secure-portal/logs/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Tested action")


class AdminFinancialSafetyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="financial-user", password="x")
        self.account = Account.objects.create(
            user=self.user,
            balance=Decimal("100.00"),
        )
        self.admin = User.objects.create_superuser(
            username="financial-admin",
            password="x",
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def test_duplicate_deposit_approval_does_not_credit_twice(self):
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal("50.00"),
            wallet_type="USDT",
            tx_hash="0x" + "c" * 64,
        )
        transaction = Transaction.objects.create(
            user=self.user,
            tx_type="DEPOSIT",
            amount=Decimal("50.00"),
            status="PENDING",
            related_id=deposit.id,
        )

        self.client.post(f"/admin-secure-portal/deposits/approve/{deposit.id}/")
        self.client.post(f"/admin-secure-portal/deposits/approve/{deposit.id}/")

        self.account.refresh_from_db()
        transaction.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("150.00"))
        self.assertEqual(transaction.status, "COMPLETED")
        self.assertEqual(
            AuditLog.objects.filter(action="Approved deposit").count(),
            1,
        )

    def test_pending_withdrawal_has_no_resolution_timestamp(self):
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            wallet_type="USDT",
            address="abc",
            amount=Decimal("20.00"),
        )

        self.assertIsNone(withdrawal.date_approved)

    def test_invalid_pending_deposit_is_not_approved(self):
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal("50.00"),
            wallet_type="BTC",
            tx_hash="0x" + "d" * 64,
        )

        response = self.client.post(
            f"/admin-secure-portal/deposits/approve/{deposit.id}/"
        )

        self.assertEqual(response.status_code, 302)
        deposit.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(deposit.status, "PENDING")
        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertFalse(AuditLog.objects.filter(action="Approved deposit").exists())

    def test_deposit_without_matching_ledger_is_not_approved(self):
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal("50.00"),
            wallet_type="USDT",
            tx_hash="0x" + "f" * 64,
        )

        response = self.client.post(
            f"/admin-secure-portal/deposits/approve/{deposit.id}/"
        )

        self.assertEqual(response.status_code, 302)
        deposit.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(deposit.status, "PENDING")
        self.assertEqual(self.account.balance, Decimal("100.00"))

    def test_withdrawal_without_matching_ledger_is_not_refunded(self):
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            wallet_type="USDT",
            address="abc",
            amount=Decimal("20.00"),
        )

        response = self.client.post(
            f"/admin-secure-portal/withdrawals/reject/{withdrawal.id}/"
        )

        self.assertEqual(response.status_code, 302)
        withdrawal.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(withdrawal.status, "PENDING")
        self.assertEqual(self.account.balance, Decimal("100.00"))

    def test_negative_user_balance_is_rejected(self):
        response = self.client.post(
            "/admin-secure-portal/user/create/",
            {
                "full_name": "Invalid Balance",
                "username": "invalid-balance",
                "email": "invalid@example.com",
                "address": "0x" + "e" * 40,
                "wallet-type": "USDT",
                "balance": "-1.00",
                "password": "secret123",
                "c_password": "secret123",
                "role": "user",
                "status": "active",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="invalid-balance").exists())
        self.assertFalse(Account.objects.filter(user__username="invalid-balance").exists())


class AdminPackageHistoryTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="package-history-user", password="x")
        self.account = Account.objects.create(
            user=self.user,
            balance=Decimal("500.00"),
        )
        self.package = Packages.objects.create(
            name="Protected History",
            description="Protected package",
            subtype="Test",
            roi=Decimal("5.00"),
            cycle=2,
            duration=48,
            interval=24,
            min_amount=Decimal("100.00"),
            max_amount=Decimal("1000.00"),
        )
        from core.models import userPackage

        userPackage.objects.create(
            user=self.account,
            package=self.package,
            amount=Decimal("100.00"),
        )
        self.admin = User.objects.create_superuser(
            username="package-history-admin",
            password="x",
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def test_delete_recommends_deactivation_for_investment_history(self):
        response = self.client.post(
            f"/admin-secure-portal/package/delete/{self.package.id}"
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Packages.objects.filter(id=self.package.id).exists())
        self.assertFalse(AuditLog.objects.filter(action="Deleted package").exists())



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

    def test_wallet_change_is_blocked_for_incompatible_accounts(self):
        user = User.objects.create_user(username="legacy-wallet", password="x")
        Account.objects.create(
            user=user,
            account_type="BTC",
            balance=Decimal("0.00"),
        )

        response = self.client.post(
            "/admin-secure-portal/settings/",
            {
                "wallet-type": "TRON",
                "wallet-address": "T" * 34,
                "referral-reward": "40.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlatformSettings.load().wallet_type, "USDT")

    def test_page_admin_only(self):
        self.assertEqual(Client().get("/admin-secure-portal/settings/").status_code, 302)
        r = self.client.get("/admin-secure-portal/settings/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Referral Reward")