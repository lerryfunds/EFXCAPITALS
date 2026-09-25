from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.contrib import messages
from django.db.models import Avg, Count, Max, Min, F
from django.db import IntegrityError, transaction
from decimal import Decimal
from .models import Account, Packages, Referral, Transaction, PlatformSettings
from .currency import get_rates

User = get_user_model()

# Create your views here.
def health_view(request):
    return HttpResponse("ok")
def home_view(request):
    active_packages = Packages.objects.filter(is_active=True)
    package_stats = active_packages.aggregate(
        count=Count("id"),
        minimum_amount=Min("min_amount"),
        top_roi=Max("roi"),
        average_duration=Avg("duration"),
    )
    context = {
        "is_logged_in": request.user.is_authenticated,
        "is_admin": request.user.is_superuser,
        "active_packages": active_packages.order_by("-is_featured", "id")[:5],
        "featured_package": active_packages.filter(is_featured=True).order_by("id").first(),
        "active_package_count": package_stats["count"],
        "minimum_amount": package_stats["minimum_amount"],
        "top_roi": package_stats["top_roi"],
        "average_duration": package_stats["average_duration"],
        "prices": get_rates(),
    }
    return render(request, "index.html", context)

def privacy_view(request):
    return render(request, "privacy.html")

def login_view(request):
    if request.user.is_authenticated:
        if not request.user.is_active:
            logout(request)
        elif request.user.is_superuser:
            return redirect("admin_dashboard")
        else:
            return redirect("dashboard")

    if request.method == "POST":
        form = request.POST

        username = form.get("email_or_username", '').strip()
        password = form.get("password", '')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            if user.is_superuser:
                return redirect("admin_dashboard")
            else:
                return redirect("dashboard")

        else:
            messages.error(request, "Invalid Credentials, please try again or create an account")

    
    return render(request, "login.html")

def register_view(request):
    if request.method == "POST":
        form = request.POST
        full_name = form.get("full_name", "").strip()
        name_parts = full_name.split()
        if len(name_parts) < 2:
            messages.error(request, "Please enter 2 names in the full name input box")
            return redirect("register")
        first_name = name_parts[0]
        last_name = " ".join(name_parts[1:])

        username = form.get("username", "").strip()
        email = form.get("email", "").strip()
        requested_wallet_type = form.get("wallet-type", "").strip().upper()
        wallet_address = form.get("address", "").strip()
        phone_number = form.get("whatsapp-number", "").strip()
        password = form.get("password", "")
        c_password = form.get("c_password", "")
        platform = PlatformSettings.load()

        if not username or not email:
            messages.error(request, "Username and email are required")
            return redirect("register")
        if (
            len(username) > 150
            or len(email) > 254
            or len(first_name) > 150
            or len(last_name) > 150
            or len(phone_number) > 30
        ):
            messages.error(request, "One or more account fields are too long")
            return redirect("register")
        if requested_wallet_type != platform.wallet_type.strip().upper():
            messages.error(request, f"Accounts are currently limited to {platform.wallet_type}")
            return redirect("register")
        if not wallet_address:
            messages.error(request, "Wallet address is required")
            return redirect("register")
        if len(wallet_address) > 150:
            messages.error(request, "Wallet address is too long")
            return redirect("register")
        if not password:
            messages.error(request, "Password is required")
            return redirect("register")
        if password != c_password:
            messages.error(request, "Passwords don't match try again")
            return redirect("register")

        ref_code = request.GET.get("ref", "").strip()
        try:
            with transaction.atomic():
                platform = PlatformSettings.objects.select_for_update().get(pk=1)
                if requested_wallet_type != platform.wallet_type.strip().upper():
                    messages.error(request, f"Accounts are currently limited to {platform.wallet_type}")
                    return redirect("register")
                if (
                    not platform.referral_reward.is_finite()
                    or platform.referral_reward < 0
                ):
                    messages.error(request, "Referral rewards are temporarily unavailable")
                    return redirect("register")
                user = User.objects.create_user(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                )
                if phone_number:
                    user.phone_number = phone_number
                user.set_password(password)
                user.save(update_fields=["password", "phone_number"])

                Account.objects.create(
                    user=user,
                    account_type=platform.wallet_type.strip().upper(),
                    wallet_address=wallet_address,
                )

                if ref_code:
                    referrer_account = (
                        Account.objects.select_for_update()
                        .select_related("user")
                        .filter(referral_code=ref_code)
                        .exclude(user_id=user.user_id)
                        .first()
                    )
                    if referrer_account:
                        reward = platform.referral_reward
                        referral = Referral.objects.create(
                            referrer=referrer_account.user,
                            referred=user,
                            reward=reward,
                        )
                        referrer_account.balance = F("balance") + reward
                        referrer_account.save(update_fields=["balance"])
                        Transaction.objects.create(
                            user=referrer_account.user,
                            tx_type="REFERRAL",
                            amount=reward,
                            status="COMPLETED",
                            related_id=referral.id,
                            description=f"Bonus for referring {username}",
                        )
                        messages.success(
                            request,
                            f"Welcome! {referrer_account.user.username} earned a referral bonus.",
                        )
        except IntegrityError:
            messages.error(request, "User with username already exists")
            return redirect("register")
        return redirect("login")

    return render(request, "register.html", {"platform": PlatformSettings.load()})


def logout_view(request):
    if not request.user.is_authenticated:
        return redirect("home")

    logout(request)
    return redirect("home")