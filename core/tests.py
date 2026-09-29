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
from core.rails import (RAIL_CATALOG, catalog_entry, valid_address, valid_txid, DEFAULT_MIN_DEPOSIT, DEFAULT_MIN_WITHDRAW, LEGACY_PREFIX)
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


class RailCatalogTest(TestCase):
    def test_catalog_contains_the_five_seeded_rails(self):
        self.assertEqual(
            set(RAIL_CATALOG),
            {"USDT:TRC20", "USDT:BEP20", "BTC", "ETH", "SOL"},
        )

    def test_every_entry_declares_the_fields_the_code_relies_on(self):
        for key, entry in RAIL_CATALOG.items():
            with self.subTest(rail=key):
                self.assertEqual(entry["symbol"], key.split(":")[0])
                self.assertTrue(entry["network"])
                self.assertTrue(entry["label"])
                self.assertTrue(entry["coin_id"])
                self.assertTrue(entry["address_re"])
                self.assertTrue(entry["txid_re"])
                self.assertGreaterEqual(entry["coin_decimals"], 0)
                for low, high in (("min_deposit", "max_deposit"), ("min_withdraw", "max_withdraw")):
                    self.assertLessEqual(Decimal(entry[low]), Decimal(entry[high]))

    def test_catalog_entry_returns_none_for_an_unknown_key(self):
        self.assertIsNone(catalog_entry("DOGE:ERC20"))
        self.assertIsNone(catalog_entry(""))

    def test_legacy_key_has_no_catalog_entry(self):
        self.assertIsNone(catalog_entry(f"{LEGACY_PREFIX}TRON"))

    def test_none_key_has_no_catalog_entry(self):
        self.assertIsNone(catalog_entry(None))


class RailValidationTest(TestCase):
    def test_tron_accepts_a_34_char_base58_address(self):
        self.assertTrue(valid_address("USDT:TRC20", "T" + "1" * 33))

    def test_tron_rejects_a_33_char_address(self):
        self.assertFalse(valid_address("USDT:TRC20", "T" + "1" * 32))

    def test_bep20_rejects_a_tron_address(self):
        self.assertFalse(valid_address("USDT:BEP20", "T" + "1" * 33))

    def test_eth_accepts_a_lowercase_0x_address(self):
        self.assertTrue(valid_address("ETH", "0x" + "a" * 40))

    def test_btc_accepts_p2pkh_and_bech32(self):
        self.assertTrue(valid_address("BTC", "1" + "a" * 33))
        self.assertTrue(valid_address("BTC", "bc1q" + "a" * 38))

    def test_btc_base58_addresses_still_match(self):
        self.assertTrue(valid_address("BTC", "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"))
        self.assertTrue(valid_address("BTC", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"))

    def test_btc_bech32_length_bounds(self):
        p2wpkh = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"  # 42 chars
        taproot = "bc1pqqqsyqcyq5rqwzqfpg9scrgwpugpzysnzs23v9ccrydpk8qarc0sagmhkq"  # 62 chars
        self.assertTrue(valid_address("BTC", p2wpkh))
        self.assertTrue(valid_address("BTC", taproot))
        self.assertFalse(valid_address("BTC", p2wpkh[:-1]))
        self.assertFalse(valid_address("BTC", taproot + "q"))

    def test_sol_address_length_bounds(self):
        self.assertFalse(valid_address("SOL", "1" * 31))
        self.assertTrue(valid_address("SOL", "1" * 32))
        self.assertFalse(valid_address("SOL", "1" * 45))

    def test_empty_address_is_never_valid(self):
        for key in RAIL_CATALOG:
            with self.subTest(rail=key):
                self.assertFalse(valid_address(key, ""))
                self.assertFalse(valid_address(key, "   "))

    def test_unknown_and_legacy_keys_never_validate(self):
        self.assertFalse(valid_address("DOGE:ERC20", "T" + "1" * 33))
        self.assertFalse(valid_address(f"{LEGACY_PREFIX}TRON", "T" + "1" * 33))
        self.assertFalse(valid_txid("DOGE:ERC20", "a" * 64))
        self.assertFalse(valid_txid(f"{LEGACY_PREFIX}TRON", "a" * 64))

    def test_txid_formats_are_rail_specific(self):
        self.assertTrue(valid_txid("USDT:TRC20", "a" * 64))
        self.assertFalse(valid_txid("USDT:TRC20", "0x" + "a" * 64))
        self.assertTrue(valid_txid("ETH", "0x" + "A" * 64))
        self.assertFalse(valid_txid("ETH", "a" * 64))
        self.assertTrue(valid_txid("BTC", "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"))
        self.assertTrue(valid_txid("BTC", "a" * 64))
        self.assertFalse(valid_txid("BTC", "0x" + "a" * 64))
        self.assertTrue(valid_txid("SOL", "1" * 88))

    def test_btc_txid_requires_exactly_64_hex_characters(self):
        self.assertFalse(valid_txid("BTC", "z" * 64))
        self.assertFalse(valid_txid("BTC", "z" * 32))
        self.assertFalse(valid_txid("BTC", "a" * 63))
        self.assertFalse(valid_txid("BTC", "a" * 65))
        self.assertFalse(valid_txid("BTC", "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"))

    def test_sol_txid_length_bounds(self):
        self.assertTrue(valid_txid("SOL", "1" * 87))
        self.assertTrue(valid_txid("SOL", "1" * 88))
        self.assertFalse(valid_txid("SOL", "5" * 64))
        self.assertFalse(valid_txid("SOL", "1" * 86))
        self.assertFalse(valid_txid("SOL", "1" * 89))

    def test_none_keys_and_values_never_validate(self):
        self.assertFalse(valid_address(None, None))
        self.assertFalse(valid_txid(None, None))
        self.assertFalse(valid_address("BTC", None))
        self.assertFalse(valid_txid("BTC", None))

    def test_validators_strip_surrounding_whitespace(self):
        self.assertTrue(valid_txid("ETH", "  0x" + "a" * 64 + "\n"))
        self.assertTrue(valid_address("ETH", " 0x" + "a" * 40 + " "))