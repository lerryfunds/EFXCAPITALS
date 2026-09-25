from functools import wraps
from django.contrib.auth import logout, update_session_auth_hash
from django.shortcuts import render, redirect, get_object_or_404
from core.models import User, Withdrawal, Account, Packages, userPackage, InvestmentPayout, Support, Transaction, Deposit, Referral, PlatformSettings
from core.currency import get_rates, to_coin
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import timedelta
from django.utils import timezone
import json
import re

MAX_FINANCIAL_AMOUNT = Decimal("9999999999999999.99")


def prices_json(rates):
    return json.dumps({k: float(v) if v else None for k, v in rates.items()})

def normalized_wallet_type(value):
    return value.strip().upper()

def normalized_tx_hash(value):
    return value.strip().upper()


def active_login_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("home")
        if not request.user.is_active:
            logout(request)
            return redirect("home")
        return view(request, *args, **kwargs)

    return wrapped

# Create your views here.
@active_login_required
def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect("home")  

    account = get_object_or_404(Account, user = request.user)

    pending_withdrawals = Withdrawal.objects.filter(user = request.user, status = "PENDING")
    active_investments = userPackage.objects.filter(user = account, is_active = True)

    context = {
        "account" : account,
        "prices" : get_rates(),
        "balance_coin" : to_coin(account.account_type, account.balance),
        "pending_count" : pending_withdrawals.count(),
        "pending_sum" : pending_withdrawals.aggregate(total = Sum("amount"))["total"] or 0,
        "active_investment_count" : active_investments.count(),
        "invested_sum" : active_investments.aggregate(total = Sum("amount"))["total"] or 0,
    }
     
    return render(request, "dashboard.html", context)

@active_login_required
def withdraw(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)
    platform = PlatformSettings.load()

    if request.method == "POST":
        form = request.POST

        wallet_type = normalized_wallet_type(form.get("wallet_type", ""))
        raw_amount = form.get("amount", "").strip()
        address = form.get("address", "").strip()
        description = form.get("description", "").strip()

        if wallet_type != normalized_wallet_type(platform.wallet_type):
            messages.error(request, f"Withdrawals are only available in {platform.wallet_type}")
            return redirect("withdraw")
        if normalized_wallet_type(account.account_type) != normalized_wallet_type(platform.wallet_type):
            messages.error(request, "Your account wallet type needs administrator review")
            return redirect("withdraw")

        if not address:
            messages.error(request, "Enter a wallet address")
            return redirect("withdraw")
        if len(address) > 150:
            messages.error(request, "Wallet address is too long")
            return redirect("withdraw")

        try:
            amount = Decimal(raw_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid withdrawal amount")
            return redirect("withdraw")

        if (
            not amount.is_finite()
            or amount < Decimal("20.00")
            or amount > MAX_FINANCIAL_AMOUNT
        ):
            messages.error(request, "Enter a valid withdrawal amount")
            return redirect("withdraw")

        with transaction.atomic():
            platform = PlatformSettings.objects.select_for_update().get(pk=1)
            if wallet_type != normalized_wallet_type(platform.wallet_type):
                messages.error(request, "Withdrawal settings changed; please try again")
                return redirect("withdraw")
            locked_account = Account.objects.select_for_update().get(pk=account.pk)
            if normalized_wallet_type(locked_account.account_type) != wallet_type:
                messages.error(request, "Your account wallet type needs administrator review")
                return redirect("withdraw")
            if amount > locked_account.balance:
                messages.error(request, "ERROR: INSUFFICIENT FUNDS")
                return redirect("withdraw")

            withdrawal = Withdrawal.objects.create(
                user=request.user,
                wallet_type=wallet_type,
                address=address,
                amount=amount,
                description=description,
            )
            Transaction.objects.create(
                user=request.user,
                tx_type="WITHDRAWAL",
                amount=-amount,
                status="PENDING",
                related_id=withdrawal.id,
                description=f"{wallet_type} withdrawal requested",
            )
            locked_account.balance = F("balance") - amount
            locked_account.save(update_fields=["balance"])

        messages.success(request, "Withdrawal request submitted, funds are on hold pending admin review.")
        return redirect("withdraw")

    prices = get_rates()
    context = {
        "account" : account,
        "prices" : prices,
        "prices_json" : prices_json(prices),
        "platform_wallet_type": platform.wallet_type,
    }

    return render(request, "withdraw.html", context)

def update_user_investments(packages):
    investment_ids = [investment.pk for investment in packages]
    if not investment_ids:
        return

    with transaction.atomic():
        account_ids = set(
            userPackage.objects.filter(pk__in=investment_ids).values_list(
                "user_id", flat=True
            )
        )
        accounts = {
            account.pk: account
            for account in Account.objects.select_for_update()
            .order_by("pk")
            .filter(pk__in=account_ids)
        }
        investments = (
            userPackage.objects.select_for_update(of=("self",))
            .select_related("package", "user")
            .filter(pk__in=investment_ids, is_active=True)
            .order_by("pk")
        )
        account_credits = {
            account_id: Decimal("0.00") for account_id in accounts
        }
        now = timezone.now()

        for investment in investments:
            package = investment.package
            package_name = package.name if package else "Investment"

            cycle = investment.effective_cycle()
            interval = investment.effective_interval()
            if cycle <= 0 or interval <= 0:
                continue
            if investment.user_id not in accounts:
                continue

            elapsed = max(now - investment.date_activated, timedelta())
            try:
                elapsed_cycles = elapsed // timedelta(hours=interval)
            except (OverflowError, TypeError, ValueError):
                continue
            completed_cycles = min(elapsed_cycles, cycle)
            previously_completed = min(max(investment.days, 0), cycle)
            changed = False

            per_cycle = (
                investment.amount * investment.effective_roi() / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if (
                not investment.amount.is_finite()
                or investment.amount < 0
                or investment.amount > MAX_FINANCIAL_AMOUNT
                or not per_cycle.is_finite()
                or per_cycle < 0
                or per_cycle > MAX_FINANCIAL_AMOUNT
            ):
                continue

            for cycle_number in range(previously_completed + 1, completed_cycles + 1):
                if InvestmentPayout.objects.filter(
                    investment=investment,
                    kind=InvestmentPayout.Kind.ROI,
                    cycle_number=cycle_number,
                ).exists():
                    continue

                transaction_record = Transaction.objects.create(
                    user_id=investment.user.user_id,
                    tx_type="ROI",
                    amount=per_cycle,
                    status="COMPLETED",
                    related_id=investment.id,
                    description=(
                        f"{package_name} cycle {cycle_number} payout"
                    ),
                )
                InvestmentPayout.objects.create(
                    investment=investment,
                    transaction=transaction_record,
                    kind=InvestmentPayout.Kind.ROI,
                    cycle_number=cycle_number,
                    amount=per_cycle,
                )
                account_credits[investment.user_id] += per_cycle
                changed = True

            if investment.days != completed_cycles:
                investment.days = completed_cycles
                changed = True

            if completed_cycles >= cycle:
                principal_exists = InvestmentPayout.objects.filter(
                    investment=investment,
                    kind=InvestmentPayout.Kind.PRINCIPAL,
                ).exists()
                if not principal_exists:
                    account_credits[investment.user_id] += investment.amount
                    principal_transaction = Transaction.objects.create(
                        user_id=investment.user.user_id,
                        tx_type="PRINCIPAL",
                        amount=investment.amount,
                        status="COMPLETED",
                        related_id=investment.id,
                        description=f"{package_name} principal return",
                    )
                    InvestmentPayout.objects.create(
                        investment=investment,
                        transaction=principal_transaction,
                        kind=InvestmentPayout.Kind.PRINCIPAL,
                        cycle_number=0,
                        amount=investment.amount,
                    )
                if investment.days != cycle or investment.is_active:
                    investment.days = cycle
                    investment.is_active = False
                    changed = True

            if changed:
                investment.save(update_fields=["days", "is_active"])

        for account in accounts.values():
            credit = account_credits[account.pk]
            if credit:
                account.balance = F("balance") + credit
                account.save(update_fields=["balance"])


@active_login_required
def investments(request):
    if not request.user.is_authenticated:
        return redirect("home")


    account = get_object_or_404(Account, user = request.user)


    userpackages = userPackage.objects.filter(user=account, is_active=True)

    update_user_investments(userpackages)

    userpackages = userPackage.objects.filter(user=account, is_active=True).select_related(
        "package"
    )
    context = {
        "userpackages" : userpackages,
    }

    
    return render(request, "investments.html", context)

@active_login_required
def transactions(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)

    txs = Transaction.objects.filter(user = request.user).order_by("-date")
    completed = txs.filter(status = "COMPLETED")
    total_in = sum(t.amount for t in completed if t.amount > 0)
    total_out = abs(sum(t.amount for t in completed if t.amount < 0))
    pending_sum = abs(sum(t.amount for t in txs if t.status == "PENDING"))

    context = {
        "account" : account,
        "transactions" : txs,
        "total_in" : total_in,
        "total_out" : total_out,
        "pending_sum" : pending_sum,
        "pending_count" : txs.filter(status = "PENDING").count(),
    }

    return render(request, "transactions.html", context)

@active_login_required
def deposit(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)
    platform = PlatformSettings.load()

    if request.method == "POST":
        form = request.POST

        wallet_type = normalized_wallet_type(form.get("wallet_type", ""))
        tx_hash = normalized_tx_hash(form.get("tx_hash", ""))
        raw_amount = form.get("amount", "").strip()

        if wallet_type != normalized_wallet_type(platform.wallet_type):
            messages.error(request, f"Deposits are only accepted in {platform.wallet_type}")
            return redirect("deposit")
        if normalized_wallet_type(account.account_type) != normalized_wallet_type(platform.wallet_type):
            messages.error(request, "Your account wallet type needs administrator review")
            return redirect("deposit")

        if not platform.wallet_address:
            messages.error(request, "Deposits are temporarily unavailable")
            return redirect("deposit")

        if not re.fullmatch(r"(?:0x)?[0-9A-F]{64}", tx_hash, flags=re.IGNORECASE):
            messages.error(request, "Enter a valid transaction hash")
            return redirect("deposit")

        try:
            amount = Decimal(raw_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid deposit amount")
            return redirect("deposit")

        if (
            not amount.is_finite()
            or amount <= 0
            or amount > MAX_FINANCIAL_AMOUNT
        ):
            messages.error(request, "Enter a valid deposit amount")
            return redirect("deposit")

        try:
            with transaction.atomic():
                platform = PlatformSettings.objects.select_for_update().get(pk=1)
                if (
                    wallet_type != normalized_wallet_type(platform.wallet_type)
                    or not platform.wallet_address
                ):
                    messages.error(request, "Deposit settings changed; please try again")
                    return redirect("deposit")
                locked_user = User.objects.select_for_update().get(pk=request.user.pk)
                locked_account = Account.objects.select_for_update().get(
                    pk=account.pk,
                    user=locked_user,
                )
                if normalized_wallet_type(locked_account.account_type) != wallet_type:
                    messages.error(request, "Your account wallet type needs administrator review")
                    return redirect("deposit")
                deposit = Deposit.objects.create(
                    user=locked_user,
                    amount=amount,
                    wallet_type=wallet_type,
                    tx_hash=tx_hash,
                    tx_hash_key=tx_hash,
                )
                Transaction.objects.create(
                    user=locked_user,
                    tx_type="DEPOSIT",
                    amount=amount,
                    status="PENDING",
                    related_id=deposit.id,
                    description=f"{wallet_type} deposit of ${amount}",
                )
        except IntegrityError:
            messages.error(request, "This transaction has already been submitted")
            return redirect("deposit")

        messages.success(request, "Deposit submitted, admin will credit your wallet after verification.")
        return redirect("deposit")

    prices = get_rates()
    context = {
        "account" : account,
        "platform_address" : platform.wallet_address,
        "platform_wallet_type": platform.wallet_type,
        "deposits" : Deposit.objects.filter(user = request.user).order_by("-date_requested")[:10],
        "prices" : prices,
        "prices_json" : prices_json(prices),
    }

    return render(request, "deposit.html", context)

@active_login_required
def referrals(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)

    referrals = Referral.objects.filter(referrer = request.user).select_related("referred").order_by("-date")
    total_earned = sum(r.reward for r in referrals)

    context = {
        "account" : account,
        "reward" : PlatformSettings.load().referral_reward,
        "referral_code" : account.referral_code,
        "referral_link" : f"{request.scheme}://{request.get_host()}/register/?ref={account.referral_code}",
        "referrals" : referrals,
        "total_earned" : total_earned,
        "total_invites" : referrals.count(),
    }

    return render(request, "referrals.html", context)

@active_login_required
def settings(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user=request.user)

    if request.method == "POST":
        form = request.POST
        full_name = form.get("fullname", "").strip()
        name_parts = full_name.split()
        if len(name_parts) < 2:
            messages.error(request, "Please enter 2 names in the full name input box")
            return redirect("settings")
        first_name = name_parts[0]
        last_name = " ".join(name_parts[1:])
        phone_number = form.get("phone_number", "").strip()
        if len(first_name) > 150 or len(last_name) > 150 or len(phone_number) > 30:
            messages.error(request, "One or more account fields are too long")
            return redirect("settings")
        old_password = form.get("old_password", "")
        new_password = form.get("new_password", "")
        if bool(old_password) != bool(new_password):
            messages.error(request, "Enter both old and new passwords")
            return redirect("settings")

        password_changed = False
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if old_password and not user.check_password(old_password):
                messages.error(request, "Incorrect password")
                return redirect("settings")
            if not user.is_active:
                messages.error(request, "Your account is inactive")
                return redirect("settings")
            user.first_name = first_name
            user.last_name = last_name
            user.phone_number = phone_number or None
            update_fields = ["first_name", "last_name", "phone_number"]
            if new_password:
                user.set_password(new_password)
                update_fields.append("password")
                password_changed = True
            user.save(update_fields=update_fields)
        if password_changed:
            update_session_auth_hash(request, user)
        request.user = user
        messages.success(request, "Settings updated")
        return redirect("settings")

    context = {
        "account" : account,
    }

    return render(request, "settings.html", context)

@active_login_required
def support(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)

    if request.method == "POST":
        form = request.POST

        topic = form.get("topic", "").strip()
        subject = form.get("subject", "").strip()
        message = form.get("message", "").strip()

        Support.objects.create(
            user = account,
            topic = topic,
            subject = subject,
            message = message
        )

        messages.success(request, "Support Message sent successfully, our team will get back to you as soon as possible!!")
        return redirect("support")

    return render(request, "support.html")

@active_login_required
def activate(request, id):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)
    package = get_object_or_404(Packages, id = id)

    if request.method == "POST":
        raw_amount = request.POST.get("amount", "").strip()
        try:
            amount = Decimal(raw_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid investment amount")
            return redirect("package-activate", id=package.id)

        if (
            not amount.is_finite()
            or amount <= 0
            or amount > MAX_FINANCIAL_AMOUNT
        ):
            messages.error(request, "Enter a valid investment amount")
            return redirect("package-activate", id=package.id)

        try:
            with transaction.atomic():
                locked_account = Account.objects.select_for_update().get(
                    pk=account.pk
                )
                locked_package = Packages.objects.select_for_update().get(
                    pk=package.pk,
                    is_active=True,
                )
                projected_payout = (
                    amount * locked_package.roi / Decimal("100")
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if (
                    not locked_package.roi.is_finite()
                    or locked_package.roi < 0
                    or locked_package.cycle <= 0
                    or locked_package.duration <= 0
                    or locked_package.interval <= 0
                    or not locked_package.min_amount.is_finite()
                    or not locked_package.max_amount.is_finite()
                    or locked_package.min_amount <= 0
                    or locked_package.max_amount < locked_package.min_amount
                    or locked_package.max_amount > MAX_FINANCIAL_AMOUNT
                    or projected_payout > MAX_FINANCIAL_AMOUNT
                    or amount < locked_package.min_amount
                    or amount > locked_package.max_amount
                ):
                    messages.error(
                        request,
                        "amount must be greater or equal to the package min amount and lesser than package max amount",
                    )
                    return redirect("package-activate", id=package.id)

                if amount > locked_account.balance:
                    messages.error(request, "insufficient funds!!")
                    return redirect("package-activate", id=package.id)

                userpackage = userPackage.objects.create(
                    user=locked_account,
                    amount=amount,
                    package=locked_package,
                    roi=locked_package.roi,
                    cycle=locked_package.cycle,
                    duration=locked_package.duration,
                    interval=locked_package.interval,
                )
                Transaction.objects.create(
                    user=request.user,
                    tx_type="INVESTMENT",
                    amount=-amount,
                    status="COMPLETED",
                    related_id=userpackage.id,
                    description=f"Activated {locked_package.name}",
                )
                locked_account.balance = F("balance") - amount
                locked_account.save(update_fields=["balance"])
        except Packages.DoesNotExist:
            messages.error(request, "This package is no longer available")
            return redirect("package-activate", id=package.id)

        messages.success(request, "Package created successfully")
        return redirect("investments")

    context = {
        "package" : package,
        "account" : account,
    }

    return render(request, "activate.html", context)

@active_login_required
def packages(request):

    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)

    packages = Packages.objects.filter(is_active = True).order_by("-is_featured")

    context = {
        "packages" : packages,
        "account" : account
    }
    
    return render(request, "packages.html", context)

