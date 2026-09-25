from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from io import StringIO
from django.utils import timezone
from datetime import timedelta
from unittest import mock
import os
from core.models import Account, Referral, Transaction, Support, CryptoRate, Packages, PlatformSettings, userPackage, InvestmentPayout
from core.currency import get_rates, convert, to_coin
from decimal import Decimal

User = get_user_model()


class HomePageTest(TestCase):
    @mock.patch("core.views.get_rates", return_value={})
    def test_no_packages_does_not_render_static_featured_plan(self, _mock_get_rates):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["active_packages"]), [])
        self.assertIsNone(response.context["featured_package"])
        self.assertEqual(response.context["active_package_count"], 0)
        self.assertContains(response, "No investment packages are currently available")
        self.assertNotContains(response, "$100.00")

    @mock.patch("core.views.get_rates", return_value={})
    def test_featured_package_uses_database_values(self, _mock_get_rates):
        package = Packages.objects.create(
            name="Growth Plan",
            description="Database-backed featured plan",
            subtype="Balanced",
            roi=Decimal("12.34"),
            cycle=10,
            duration=14,
            interval=6,
            min_amount=Decimal("250.00"),
            max_amount=Decimal("5000.00"),
            is_featured=True,
            is_active=True,
        )

        response = self.client.get("/")

        self.assertEqual(response.context["featured_package"], package)
        self.assertContains(response, "Growth Plan")
        self.assertContains(response, "$250.00")
        self.assertContains(response, "12.34%")
        self.assertContains(response, "6h")

    @mock.patch("core.views.get_rates", return_value={})
    def test_inactive_featured_package_is_not_promoted(self, _mock_get_rates):
        Packages.objects.create(
            name="Retired Plan",
            description="Inactive",
            subtype="Legacy",
            roi=Decimal("4.00"),
            cycle=5,
            duration=5,
            interval=24,
            min_amount=Decimal("50.00"),
            max_amount=Decimal("500.00"),
            is_featured=True,
            is_active=False,
        )
        active_package = Packages.objects.create(
            name="Current Plan",
            description="Active but not featured",
            subtype="Standard",
            roi=Decimal("5.00"),
            cycle=5,
            duration=5,
            interval=24,
            min_amount=Decimal("75.00"),
            max_amount=Decimal("750.00"),
            is_featured=False,
            is_active=True,
        )

        response = self.client.get("/")

        self.assertIsNone(response.context["featured_package"])
        self.assertEqual(list(response.context["active_packages"]), [active_package])
        self.assertContains(response, "No package is currently marked as featured")
        self.assertNotContains(response, "Retired Plan")


class RegistrationTest(TestCase):
    def test_register_creates_account(self):
        c = Client()
        r = c.post("/register/", {
            "full_name": "Jane Doe",
            "username": "janedoe",
            "email": "jane@example.com",
            "address": "0x" + "1" * 40,
            "wallet-type": "USDT",
            "whatsapp-number": "+1 555 000 1234",
            "password": "secret123",
            "c_password": "secret123",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(User.objects.filter(username="janedoe").count(), 1)
        self.assertEqual(User.objects.get(username="janedoe").phone_number, "+1 555 000 1234")
        self.assertEqual(Account.objects.filter(user__username="janedoe").count(), 1)

    def test_register_with_referral_credits_referrer(self):
        referrer_user = User.objects.create_user(username="refuser", password="x")
        referrer_account = Account.objects.create(user=referrer_user, balance=Decimal("0.00"))
        ref_code = referrer_account.referral_code

        c = Client()
        c.post(f"/register/?ref={ref_code}", {
            "full_name": "New Person",
            "username": "newperson",
            "email": "new@example.com",
            "address": "0x" + "2" * 40,
            "wallet-type": "USDT",
            "password": "secret123",
            "c_password": "secret123",
        })

        referenced = User.objects.get(username="newperson")
        self.assertEqual(Referral.objects.filter(referrer=referrer_user, referred=referenced).count(), 1)
        referrer_account.refresh_from_db()
        self.assertEqual(referrer_account.balance, Decimal("25.00"))
        self.assertEqual(Transaction.objects.filter(user=referrer_user, tx_type="REFERRAL").count(), 1)


class RegistrationSafetyTest(TestCase):
    def setUp(self):
        platform = PlatformSettings.load()
        platform.wallet_type = "TRON"
        platform.wallet_address = "T" * 34
        platform.save(update_fields=["wallet_type", "wallet_address"])

    def test_registration_rejects_a_different_wallet_network(self):
        response = Client().post(
            "/register/",
            {
                "full_name": "Jane Doe",
                "username": "wrong-wallet",
                "email": "wrong-wallet@example.com",
                "address": "T" * 34,
                "wallet-type": "USDT",
                "password": "secret123",
                "c_password": "secret123",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="wrong-wallet").exists())

    def test_registration_rejects_empty_password(self):
        response = Client().post(
            "/register/",
            {
                "full_name": "Jane Doe",
                "username": "empty-password",
                "email": "empty-password@example.com",
                "address": "T" * 34,
                "wallet-type": "TRON",
                "password": "",
                "c_password": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="empty-password").exists())


class ROICommandTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = User.objects.create_user(username="roi-user", password="x")
        self.account = Account.objects.create(
            user=self.user,
            balance=Decimal("100.00"),
        )
        self.package = Packages.objects.create(
            name="Audit Plan",
            description="Audit",
            subtype="Test",
            roi=Decimal("10.00"),
            cycle=3,
            duration=3,
            interval=1,
            min_amount=Decimal("10.00"),
            max_amount=Decimal("100.00"),
        )

    def test_legacy_roi_is_reported_without_mutation(self):
        investment = userPackage.objects.create(
            user=self.account,
            package=self.package,
            amount=Decimal("100.00"),
            roi=Decimal("10.00"),
            cycle=3,
            duration=3,
            interval=1,
            days=1,
        )
        userPackage.objects.filter(pk=investment.pk).update(
            date_activated=self.now - timedelta(hours=2)
        )
        Transaction.objects.create(
            user=self.user,
            tx_type="ROI",
            amount=Decimal("10.00"),
            status="COMPLETED",
            related_id=investment.id,
        )
        output = StringIO()

        with mock.patch(
            "core.management.commands.audit_roi.timezone.now",
            return_value=self.now,
        ):
            call_command("audit_roi", "--json", stdout=output)

        self.assertIn("amount_mismatch", output.getvalue())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertEqual(InvestmentPayout.objects.count(), 0)

    def test_current_payouts_pass_audit(self):
        investment = userPackage.objects.create(
            user=self.account,
            package=self.package,
            amount=Decimal("100.00"),
            roi=Decimal("10.00"),
            cycle=3,
            duration=3,
            interval=1,
        )
        userPackage.objects.filter(pk=investment.pk).update(
            date_activated=self.now - timedelta(hours=1)
        )
        with mock.patch("user_panel.views.timezone.now", return_value=self.now):
            from user_panel.views import update_user_investments
            update_user_investments(userPackage.objects.filter(pk=investment.pk))

        output = StringIO()
        with mock.patch(
            "core.management.commands.audit_roi.timezone.now",
            return_value=self.now,
        ):
            call_command("audit_roi", "--json", stdout=output)

        self.assertIn('"discrepancies": []', output.getvalue())

    def test_cycle_counter_ahead_is_reported(self):
        investment = userPackage.objects.create(
            user=self.account,
            package=self.package,
            amount=Decimal("100.00"),
            roi=Decimal("10.00"),
            cycle=3,
            duration=3,
            interval=1,
            days=2,
        )
        userPackage.objects.filter(pk=investment.pk).update(
            date_activated=self.now - timedelta(hours=1)
        )
        output = StringIO()

        with mock.patch(
            "core.management.commands.audit_roi.timezone.now",
            return_value=self.now,
        ):
            call_command("audit_roi", "--json", stdout=output)

        self.assertIn("cycle_counter_ahead", output.getvalue())

    def test_payout_and_ledger_mismatch_is_reported(self):
        investment = userPackage.objects.create(
            user=self.account,
            package=self.package,
            amount=Decimal("100.00"),
            roi=Decimal("10.00"),
            cycle=3,
            duration=3,
            interval=1,
        )
        userPackage.objects.filter(pk=investment.pk).update(
            date_activated=self.now - timedelta(hours=1)
        )
        transaction = Transaction.objects.create(
            user=self.user,
            tx_type="ROI",
            amount=Decimal("9.99"),
            status="COMPLETED",
            related_id=investment.id,
        )
        InvestmentPayout.objects.create(
            investment=investment,
            transaction=transaction,
            kind=InvestmentPayout.Kind.ROI,
            cycle_number=1,
            amount=Decimal("10.00"),
        )
        output = StringIO()

        with mock.patch(
            "core.management.commands.audit_roi.timezone.now",
            return_value=self.now,
        ):
            call_command("audit_roi", "--json", stdout=output)

        report = output.getvalue()
        self.assertIn("payout_transaction_mismatch", report)
        self.assertIn("ledger_mismatch", report)


class LoginTest(TestCase):
    def test_admin_rerouted_to_panel(self):
        User.objects.create_superuser(username="boss", password="x")
        c = Client()
        c.post("/login/", {"email_or_username": "boss", "password": "x"})
        self.assertRedirects(c.get("/login/"), "/admin-secure-portal/", fetch_redirect_response=False)


class EnsureAdminTest(TestCase):
    def test_missing_password_does_not_create_admin(self):
        with mock.patch.dict(os.environ, {"DJANGO_ADMIN_PASSWORD": ""}):
            with self.assertRaises(CommandError):
                call_command(
                    "ensure_admin",
                    username="new-admin",
                    email="admin@example.com",
                )

        self.assertFalse(User.objects.filter(username="new-admin").exists())

    def test_password_repairs_unusable_admin(self):
        User.objects.create(username="admin")

        call_command(
            "ensure_admin",
            username="admin",
            email="admin@example.com",
            password="replacement-password",
        )

        admin = User.objects.get(username="admin")
        self.assertTrue(admin.has_usable_password())
        self.assertTrue(admin.check_password("replacement-password"))
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_existing_admin_is_reactivated(self):
        User.objects.create_superuser(
            username="inactive-admin",
            password="existing-password",
            is_active=False,
        )

        call_command(
            "ensure_admin",
            username="inactive-admin",
        )

        admin = User.objects.get(username="inactive-admin")
        self.assertTrue(admin.is_active)

    def test_missing_password_preserves_existing_password(self):
        User.objects.create_superuser(
            username="admin",
            password="existing-password",
        )

        with mock.patch.dict(os.environ, {"DJANGO_ADMIN_PASSWORD": ""}):
            call_command("ensure_admin", username="admin")

        admin = User.objects.get(username="admin")
        self.assertTrue(admin.check_password("existing-password"))


class CurrencyTest(TestCase):
    def _seed(self, now, **prices):
        for symbol, price in prices.items():
            CryptoRate.objects.update_or_create(
                symbol=symbol,
                defaults={"usd_price": Decimal(price), "updated": now},
            )

    def test_fetch_populates_rates(self):
        fetched = {"USDT": Decimal("1.00"), "BTC": Decimal("60000"), "ETH": Decimal("3000"), "SOL": Decimal("150")}
        with mock.patch("core.currency._fetch_rates", return_value=fetched) as fetcher:
            rates = get_rates()
        fetcher.assert_called_once()
        self.assertEqual(rates["BTC"], Decimal("60000"))
        self.assertEqual(rates["USDT"], Decimal("1.00"))
        self.assertTrue(CryptoRate.objects.filter(symbol="BTC").exists())

    def test_cached_within_window(self):
        now = timezone.now()
        self._seed(now, USDT="1.00", BTC="60000", ETH="3000", SOL="150")
        with mock.patch("core.currency._fetch_rates", side_effect=RuntimeError("no network")) as fetcher:
            rates = get_rates()
        fetcher.assert_not_called()
        self.assertEqual(rates["BTC"], Decimal("60000"))

    def test_uses_stale_rates_when_api_down(self):
        stale = timezone.now() - timedelta(minutes=30)
        self._seed(stale, USDT="1.00", BTC="50000", ETH="2000", SOL="100")
        with mock.patch("core.currency._fetch_rates", side_effect=RuntimeError("api down")):
            rates = get_rates()
        self.assertEqual(rates["BTC"], Decimal("50000"))
        self.assertEqual(rates["USDT"], Decimal("1.00"))

    def test_convert_and_to_coin(self):
        self._seed(timezone.now(), USDT="1.00", BTC="60000", ETH="3000", SOL="150")
        self.assertEqual(convert("BTC", Decimal("0.5")), Decimal("30000.00"))
        self.assertEqual(convert("USDT", Decimal("5")), Decimal("5.00"))
        self.assertEqual(convert("SOL", Decimal("2")), Decimal("300.00"))
        self.assertEqual(to_coin("BTC", Decimal("30000")), Decimal("0.5"))
        self.assertIsNone(convert("DOGE", Decimal("1")))