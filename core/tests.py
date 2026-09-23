from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from core.models import Account, Referral, Transaction, Support
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