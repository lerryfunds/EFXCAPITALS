from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from unittest import mock
from core.models import Account, Referral, Transaction, Support, CryptoRate
from core.currency import get_rates, convert, to_coin
from decimal import Decimal

User = get_user_model()


class RegistrationTest(TestCase):
    def test_register_creates_account(self):
        c = Client()
        r = c.post("/register/", {
            "full_name": "Jane Doe",
            "username": "janedoe",
            "email": "jane@example.com",
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
            "wallet-type": "USDT",
            "password": "secret123",
            "c_password": "secret123",
        })

        referenced = User.objects.get(username="newperson")
        self.assertEqual(Referral.objects.filter(referrer=referrer_user, referred=referenced).count(), 1)
        referrer_account.refresh_from_db()
        self.assertEqual(referrer_account.balance, Decimal("25.00"))
        self.assertEqual(Transaction.objects.filter(user=referrer_user, tx_type="REFERRAL").count(), 1)


class LoginTest(TestCase):
    def test_admin_rerouted_to_panel(self):
        User.objects.create_superuser(username="boss", password="x")
        c = Client()
        c.post("/login/", {"email_or_username": "boss", "password": "x"})
        self.assertRedirects(c.get("/login/"), "/admin-secure-portal/", fetch_redirect_response=False)


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