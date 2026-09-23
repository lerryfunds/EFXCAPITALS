from django.shortcuts import render, redirect, get_object_or_404, get_list_or_404
from core.models import Withdrawal, Account, Packages, userPackage, Support, Transaction, Deposit, Referral, PlatformSettings
from core.currency import get_rates, to_coin
from django.contrib import messages
from django.db.models import Sum
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone, timedelta
import json

def prices_json(rates):
    return json.dumps({k: float(v) if v else None for k, v in rates.items()})

# Create your views here.
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

def withdraw(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)

    if request.method == "POST":
        form = request.POST

        wallet_type = form.get("wallet_type", "").strip()
        raw_amount = form.get("amount", "").strip()
        address = form.get("address", "").strip()
        description = form.get("description", "").strip()

        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            messages.error(request, "Enter a valid withdrawal amount")
            return redirect("withdraw")

        if amount < Decimal("20.00"):
            messages.error(request, "Minimum withdrawal is $20.00")
            return redirect("withdraw")

        if amount > account.balance:
            messages.error(request, "ERROR: INSUFFICIENT FUNDS")
            return redirect("withdraw")

        Withdrawal.objects.create(
            user = request.user,
            wallet_type = wallet_type,
            address = address,
            amount = amount,
            description = description
        )

        account.balance -= amount
        account.save()

        withdrawal = Withdrawal.objects.filter(user = request.user).order_by("-date_requested").first()
        Transaction.objects.create(
            user = request.user,
            tx_type = "WITHDRAWAL",
            amount = -amount,
            status = "PENDING",
            related_id = withdrawal.id if withdrawal else None,
            description = f"{wallet_type} withdrawal requested"
        )
        messages.success(request, "Withdrawal request submitted, funds are on hold pending admin review.")
        return redirect("withdraw")

    prices = get_rates()
    context = {
        "account" : account,
        "prices" : prices,
        "prices_json" : prices_json(prices),
    }

    return render(request, "withdraw.html", context)

def update_user_investments(packages):
    for package in packages:
        perCycle = package.amount * package.package.roi
        # print(package.days)
        # print(package.package.roi)
        # print(package.amount)
        # print(perCycle)
        # print((datetime.now(timezone.utc) - package.date_activated).days)
        # print(package.user.balance)
        # timedelta.days
        if (datetime.now(timezone.utc) - package.date_activated).days > package.days and package.days < package.package.cycle:
            # print("yes")
            un_updated = (datetime.now(timezone.utc) - package.date_activated).days - package.days
            accrued = un_updated * perCycle
            package.user.balance += accrued
            package.days = (datetime.now(timezone.utc) - package.date_activated).days
            package.save()
            package.user.save()
            Transaction.objects.create(
                user = package.user.user,
                tx_type = "ROI",
                amount = accrued,
                status = "COMPLETED",
                related_id = package.id,
                description = f"{package.package.name} cycle payout ({un_updated} cycle{'s' if un_updated > 1 else ''})"
            )
        elif package.days >= package.package.cycle:
            Transaction.objects.create(
                user = package.user.user,
                tx_type = "PRINCIPAL",
                amount = package.amount,
                status = "COMPLETED",
                related_id = package.id,
                description = f"{package.package.name} principal return"
            )
            package.user.balance += package.amount
            package.is_active = False
            package.user.save()
            package.save()
    


def investments(request):
    if not request.user.is_authenticated:
        return redirect("home")


    account = get_object_or_404(Account, user = request.user)


    userpackages = userPackage.objects.filter(user = account, is_active = True)

    update_user_investments(userpackages)

    context = {
        "userpackages" : userpackages,
    }

    
    return render(request, "investments.html", context)

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

def deposit(request):
    if not request.user.is_authenticated:
        return redirect("home")

    account = get_object_or_404(Account, user = request.user)
    platform = PlatformSettings.load()

    if request.method == "POST":
        form = request.POST

        wallet_type = form.get("wallet_type", "USDT").strip()
        tx_hash = form.get("tx_hash", "").strip()
        raw_amount = form.get("amount", "").strip()

        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            messages.error(request, "Enter a valid deposit amount")
            return redirect("deposit")

        if amount <= 0:
            messages.error(request, "Enter a valid deposit amount")
            return redirect("deposit")

        deposit = Deposit.objects.create(
            user = request.user,
            amount = amount,
            wallet_type = wallet_type,
            tx_hash = tx_hash,
        )

        Transaction.objects.create(
            user = request.user,
            tx_type = "DEPOSIT",
            amount = amount,
            status = "PENDING",
            related_id = deposit.id,
            description = f"{wallet_type} deposit of ${amount}"
        )
        messages.success(request, "Deposit submitted, admin will credit your wallet after verification.")
        return redirect("deposit")

    prices = get_rates()
    context = {
        "account" : account,
        "platform_address" : platform.wallet_address,
        "deposits" : Deposit.objects.filter(user = request.user).order_by("-date_requested")[:10],
        "prices" : prices,
        "prices_json" : prices_json(prices),
    }

    return render(request, "deposit.html", context)

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

def settings(request):
    if not request.user.is_authenticated:
        return redirect("home")
    
    account = get_object_or_404(Account, user = request.user)

    if request.method == "POST":
        form = request.POST
        print("hjvfknd")

        full_name = form.get("fullname")
        full_name = full_name.split(" ")
        if len(full_name) < 2:
            messages.error(request, "Please enter 2 names in the full name input box")
            return redirect("settings")
        first_name = full_name[0]
        last_name = full_name[1]

        phone_number = form.get("phone_number", "").strip()

        request.user.first_name = first_name
        request.user.last_name = last_name
        if  not phone_number == "":
            print("phone number")
            request.user.phone_number = phone_number

        request.user.save()

        if form.get("old_password", "").strip() != "" and form.get("new_password", "").strip() != "":
            print("vnfjjnhkiskcjdsbjhk")
            if request.user.check_password(form.get("old_password")):
                request.user.set_password(form.get("new_password"))
                request.user.save()
            else:
                messages.error(request, "Incorrect password")
                return redirect("settings")


    context = {
        "account" : account,
    }

    return render(request, "settings.html", context)

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

def activate(request, id):
    if not request.user.is_authenticated:
        return redirect("home")
    
    account = get_object_or_404(Account, user = request.user)
    package = get_object_or_404(Packages, id = id)

    if request.method == "POST":
        form = request.POST

        amount = form.get("amount")
        if Decimal(amount) > package.max_amount or Decimal(amount) < package.min_amount:
            messages.error(request, "amount must be greater or equal to the package min amount and lesser than package max amount")
            return redirect("package-activate", id=package.id)

        if Decimal(amount) > account.balance:
            messages.error(request, "insufficient funds!!")
            return redirect("package-activate", id=package.id)

        userpackage = userPackage.objects.create(
            user = account,
            amount = amount,
            package = package,
        )

        account.balance -= Decimal(userpackage.amount)
        account.save()
        userpackage.save()

        Transaction.objects.create(
            user = request.user,
            tx_type = "INVESTMENT",
            amount = -Decimal(userpackage.amount),
            status = "COMPLETED",
            related_id = userpackage.id,
            description = f"Activated {package.name}"
        )
        messages.success(request, "Package created successfully")
        return redirect("investments")

    context = {
        "package" : package,
        "account" : account,
    }

    return render(request, "activate.html", context)

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

