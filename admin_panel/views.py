from django.http import Http404
from django.views.decorators.http import require_POST
from django.core.exceptions import BadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from core.models import Packages, Account, Withdrawal, Support, Deposit, Transaction, AuditLog, PlatformSettings
from core.currency import get_rates
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
User = get_user_model()
MAX_FINANCIAL_AMOUNT = Decimal("9999999999999999.99")
MAX_REFERRAL_REWARD = Decimal("99999999.99")


def pending_financial_transaction(user, related_id, tx_type, amount):
    transactions = list(
        Transaction.objects.select_for_update()
        .filter(
            user=user,
            related_id=related_id,
            tx_type=tx_type,
            status="PENDING",
        )
        .order_by("id")
    )
    if len(transactions) != 1 or transactions[0].amount != amount:
        return None
    return transactions[0]


def add_audit_log(request, action, detail=""):
    AuditLog.objects.create(admin=request.user, action=action, detail=detail)


def valid_wallet_type(value, platform):
    return value.strip().upper() == platform.wallet_type.strip().upper()


def valid_tx_hash(value):
    return bool(re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", value.strip()))


def package_form_data(form):
    try:
        roi = Decimal(form.get("roi-cycle", "")).quantize(Decimal("0.01"))
        cycle = int(form.get("payout-cycle", ""))
        duration = int(form.get("duration", ""))
        interval = int(form.get("interval", ""))
        min_amount = Decimal(form.get("min-amount", "")).quantize(Decimal("0.01"))
        max_amount = Decimal(form.get("max-amount", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Enter valid package return and limit values")

    values = (roi, min_amount, max_amount)
    if not all(value.is_finite() for value in values):
        raise ValueError("Enter valid package return and limit values")
    if roi < 0 or roi > Decimal("999.99"):
        raise ValueError("Package limits and ROI must be positive and ordered")
    if min_amount <= 0 or max_amount < min_amount:
        raise ValueError("Package limits and ROI must be positive and ordered")
    if max_amount > MAX_FINANCIAL_AMOUNT:
        raise ValueError("Package limits and ROI must be positive and ordered")
    if (
        max_amount * roi / Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) > MAX_FINANCIAL_AMOUNT:
        raise ValueError("Package return exceeds the supported financial range")
    if cycle <= 0 or duration <= 0 or interval <= 0:
        raise ValueError("Package cycles, duration, and interval must be positive")

    name = form.get("package-name", "").strip()
    subtype = form.get("subtype", "").strip()
    description = form.get("package-description", "").strip()
    if not name or not subtype or not description:
        raise ValueError("Package name, subtype, and description are required")
    if len(name) > 50 or len(subtype) > 50:
        raise ValueError("Package name and subtype must be 50 characters or fewer")

    return {
        "name": name,
        "subtype": subtype,
        "description": description,
        "roi": roi,
        "cycle": cycle,
        "duration": duration,
        "interval": interval,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "is_featured": form.get("featured?") == "on",
    }


# Create your views here.
def admin_dashboard(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    pending_withdrawals = Withdrawal.objects.filter(status = "PENDING").select_related("user")
    pending_sum = pending_withdrawals.aggregate(total = Sum("amount"))["total"] or 0

    context = {
        "total_users" : User.objects.all().count(),
        "active_users" : User.objects.filter(is_active = True).count(),
        "active_packages" : Packages.objects.filter(is_active = True).count(),
        "recent_users" : Account.objects.all().order_by("-date_updated")[:5],
        "pending_count" : pending_withdrawals.count(),
        "pending_sum" : pending_sum,
        "pending_withdrawals" : pending_withdrawals[:5],
        "recent_support" : Support.objects.select_related("user__user").order_by("-date_sent")[:5],
    }

    return render(request, "admin.html", context)

def admin_users(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    accounts = Account.objects.all()

    context = {
        "accounts" : accounts,
        "prices" : get_rates(),
    }

    return render(request, "admin-users.html", context)

def admin_package_list(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    packages = Packages.objects.all()

    context = {
        "packages" : packages
    }

    return render(request, "admin-packages.html", context)

def admin_package_create(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    if request.method == "POST":
        try:
            values = package_form_data(request.POST)
        except ValueError as error:
            messages.error(request, str(error))
            return redirect("admin_package_create")

        with transaction.atomic():
            new_package = Packages.objects.create(**values)
            add_audit_log(request, "Created package", values["name"])

        return redirect("admin_packages_list")


    
    return render(request, "admin-package-form.html")

@require_POST
def admin_toggle_package_active(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    with transaction.atomic():
        package = Packages.objects.select_for_update().get(id=id)
        package.is_active = not package.is_active
        package.save(update_fields=["is_active"])
        add_audit_log(request, "Toggled package", f"{package.name} -> {'active' if package.is_active else 'disabled'}")

    return redirect("admin_packages_list")

def admin_package_edit(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")
    package = get_object_or_404(Packages, id=id)

    if request.method == "POST":
        try:
            values = package_form_data(request.POST)
        except ValueError as error:
            messages.error(request, str(error))
            return redirect("admin_package_edit", id=id)

        with transaction.atomic():
            package = Packages.objects.select_for_update().get(pk=package.pk)
            for field, value in values.items():
                setattr(package, field, value)
            package.save()
            add_audit_log(request, "Edited package", values["name"])

        return redirect("admin_packages_list")

    context = {
        "package" : package,
        "package_name" : package.name,
        "package_subtype" : package.subtype,
        "package_roi" : package.roi,
        "package_cycle" : package.cycle,
        "package_duration" : package.duration,
        "package_interval" : package.interval,
        "package_min_amount" : package.min_amount,
        "package_max_amount" : package.max_amount,
        "package_is_featured?" : package.is_featured,
    }

    return render(request, "admin-package-form.html", context)

@require_POST
def admin_package_delete(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")
    package = get_object_or_404(Packages, id=id)
    try:
        with transaction.atomic():
            package = Packages.objects.select_for_update().get(id=id)
            add_audit_log(request, "Deleted package", package.name)
            package.delete()
    except ProtectedError:
        messages.error(request, "Packages with investment history cannot be deleted; deactivate it instead.")
    return redirect("admin_packages_list")

def admin_user_create(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    if request.method == "POST":
        form = request.POST
        full_name = form.get("full_name", "").strip()
        name_parts = full_name.split()
        if len(name_parts) < 2:
            messages.error(request, "Please enter 2 names in the full name input box")
            return redirect("admin_user_create")
        if (
            len(name_parts[0]) > 150
            or len(" ".join(name_parts[1:])) > 150
        ):
            messages.error(request, "One or more account fields are too long")
            return redirect("admin_user_create")
        first_name = name_parts[0]
        last_name = " ".join(name_parts[1:])

        username = form.get("username", "").strip()
        email = form.get("email", "").strip()
        requested_wallet_type = form.get("wallet-type", "").strip().upper()
        platform = PlatformSettings.load()
        wallet_address = form.get("address", "").strip()
        raw_balance = form.get("balance", "0").strip()
        password = form.get("password", "")
        c_password = form.get("c_password", "")
        if not username or not email:
            messages.error(request, "Username and email are required")
            return redirect("admin_user_create")
        if len(username) > 150 or len(email) > 254:
            messages.error(request, "One or more account fields are too long")
            return redirect("admin_user_create")
        if requested_wallet_type != platform.wallet_type.strip().upper():
            messages.error(request, f"Accounts are currently limited to {platform.wallet_type}")
            return redirect("admin_user_create")
        if not wallet_address or len(wallet_address) > 150:
            messages.error(request, "A valid wallet address is required")
            return redirect("admin_user_create")
        try:
            wallet_balance = Decimal(raw_balance).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid account balance")
            return redirect("admin_user_create")
        if (
            not wallet_balance.is_finite()
            or wallet_balance < 0
            or wallet_balance > MAX_FINANCIAL_AMOUNT
        ):
            messages.error(request, "Enter a valid account balance")
            return redirect("admin_user_create")
        if not password:
            messages.error(request, "Password is required")
            return redirect("admin_user_create")
        if password != c_password:
            messages.error(request, "Passwords don't match try again")
            return redirect("admin_user_create")
        is_admin = form.get("role") == "admin"
        is_active = form.get("status") == "active"

        try:
            with transaction.atomic():
                platform = PlatformSettings.objects.select_for_update().get(pk=1)
                if requested_wallet_type != platform.wallet_type.strip().upper():
                    messages.error(request, f"Accounts are currently limited to {platform.wallet_type}")
                    return redirect("admin_user_create")
                user = User.objects.create_user(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    is_staff=is_admin,
                    is_superuser=is_admin,
                    is_active=is_active,
                )
                user.set_password(password)
                user.save(update_fields=["password"])
                Account.objects.create(
                    user=user,
                    account_type=platform.wallet_type.strip().upper(),
                    balance=wallet_balance,
                    wallet_address=wallet_address,
                )
                add_audit_log(request, "Created user", username)
        except IntegrityError:
            messages.error(request, "User with username already exists")
            return redirect("admin_user_create")
        return redirect("admin_users_view")
    
    return render(request, "admin-user-form.html", {"platform": PlatformSettings.load()})

@require_POST
def admin_user_delete(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    with transaction.atomic():
        user = User.objects.select_for_update().get(user_id=id)
        if user.user_id == request.user.user_id:
            messages.error(request, "You cannot deactivate your own account")
            return redirect("admin_users_view")
        user.is_active = False
        user.save(update_fields=["is_active"])
        add_audit_log(request, "Deactivated user", user.username)

    return redirect("admin_users_view")

def admin_user_edit(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    user = get_object_or_404(User, user_id=id)
    account = get_object_or_404(Account, user=user)

    if request.method == "POST":
        form = request.POST
        full_name = form.get("full_name", "").strip()
        name_parts = full_name.split()
        if len(name_parts) < 2:
            messages.error(request, "Please enter 2 names in the full name input box")
            return redirect("admin_user_edit", id=id)
        email = form.get("email", "").strip()
        if (
            len(name_parts[0]) > 150
            or len(" ".join(name_parts[1:])) > 150
            or len(email) > 254
        ):
            messages.error(request, "One or more account fields are too long")
            return redirect("admin_user_edit", id=id)
        try:
            wallet_balance = Decimal(form.get("balance", "").strip()).quantize(
                Decimal("0.01")
            )
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid account balance")
            return redirect("admin_user_edit", id=id)
        if (
            not wallet_balance.is_finite()
            or wallet_balance < 0
            or wallet_balance > MAX_FINANCIAL_AMOUNT
        ):
            messages.error(request, "Enter a valid account balance")
            return redirect("admin_user_edit", id=id)

        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            account = Account.objects.select_for_update().get(pk=account.pk)
            user.first_name = name_parts[0]
            user.last_name = " ".join(name_parts[1:])
            user.email = email
            user.save(update_fields=["first_name", "last_name", "email"])
            account.balance = wallet_balance
            account.save(update_fields=["balance"])
            add_audit_log(request, "Edited user", user.username)
        return redirect("admin_users_view")

    context = {
        "user" : user,
        "account" : account,
        "edit" : True,
    }

    return render(request, "admin-user-form.html", context)

@require_POST
def admin_toggle_user_activity(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")
    
    with transaction.atomic():
        user = User.objects.select_for_update().get(user_id=id)
        if user.user_id == request.user.user_id:
            messages.error(request, "You cannot deactivate your own account")
            return redirect("admin_users_view")
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        add_audit_log(request, "Toggled user activity", f"{user.username} -> {'active' if user.is_active else 'disabled'}")
    return redirect("admin_users_view")

def admin_withdrawals(request, status):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    if status == "all":
        withdrawals = Withdrawal.objects.all()
    elif status == "pending":
        withdrawals = Withdrawal.objects.filter(status = "PENDING")
    elif status == "approved":
        withdrawals = Withdrawal.objects.filter(status = "APPROVED")
    elif status == "rejected":
        withdrawals = Withdrawal.objects.filter(status = "REJECTED")
    else:
        raise BadRequest("Invalid status")

    context = {
        "withdrawals" : withdrawals,
        "pending_count" : Withdrawal.objects.filter(status = "PENDING").count(),
    }

    return render(request, "admin-withdrawals.html", context)

@require_POST
def approve_withdrawal(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    with transaction.atomic():
        withdrawal = (
            Withdrawal.objects.select_for_update()
            .select_related("user")
            .get(id=id)
        )
        PlatformSettings.load()
        platform = PlatformSettings.objects.select_for_update().get(pk=1)
        if withdrawal.status == "PENDING" and (
            not valid_wallet_type(withdrawal.wallet_type, platform)
            or not withdrawal.amount.is_finite()
            or withdrawal.amount <= 0
        ):
            messages.error(request, "Withdrawal network or amount is invalid")
            return redirect("admin_withdrawals", status="all")
        if withdrawal.status == "PENDING":
            pending_transaction = None
            if withdrawal.user_id:
                pending_transaction = pending_financial_transaction(
                    withdrawal.user,
                    withdrawal.id,
                    "WITHDRAWAL",
                    -withdrawal.amount,
                )
                if pending_transaction is None:
                    messages.error(request, "Withdrawal ledger record is missing or invalid")
                    return redirect("admin_withdrawals", status="all")
            withdrawal.status = "APPROVED"
            withdrawal.date_approved = timezone.now()
            withdrawal.save(update_fields=["status", "date_approved"])
            if pending_transaction is not None:
                pending_transaction.status = "COMPLETED"
                pending_transaction.save(update_fields=["status"])
            add_audit_log(
                request,
                "Approved withdrawal",
                f"{withdrawal.amount} for {withdrawal.user.username if withdrawal.user else 'unknown'}",
            )

    return redirect("admin_withdrawals", status="all")


@require_POST
def reject_withdrawal(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    with transaction.atomic():
        withdrawal = (
            Withdrawal.objects.select_for_update()
            .select_related("user")
            .get(id=id)
        )
        if withdrawal.status == "PENDING" and (
            not withdrawal.amount.is_finite() or withdrawal.amount <= 0
        ):
            messages.error(request, "Withdrawal amount is invalid")
            return redirect("admin_withdrawals", status="all")
        if withdrawal.status == "PENDING":
            pending_transaction = None
            account = None
            if withdrawal.user_id:
                pending_transaction = pending_financial_transaction(
                    withdrawal.user,
                    withdrawal.id,
                    "WITHDRAWAL",
                    -withdrawal.amount,
                )
                if pending_transaction is None:
                    messages.error(request, "Withdrawal ledger record is missing or invalid")
                    return redirect("admin_withdrawals", status="all")
                account = Account.objects.select_for_update().filter(
                    user=withdrawal.user
                ).first()
                if account is None:
                    messages.error(request, "Withdrawal account is missing")
                    return redirect("admin_withdrawals", status="all")
                account.balance = F("balance") + withdrawal.amount
                account.save(update_fields=["balance"])
                pending_transaction.status = "REJECTED"
                pending_transaction.save(update_fields=["status"])
            withdrawal.status = "REJECTED"
            withdrawal.date_approved = timezone.now()
            withdrawal.save(update_fields=["status", "date_approved"])
            add_audit_log(
                request,
                "Rejected withdrawal",
                f"{withdrawal.amount} for {withdrawal.user.username if withdrawal.user else 'unknown'}",
            )

    return redirect("admin_withdrawals", status="all")

def admin_support(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    support_messages = Support.objects.select_related("user__user").order_by("-date_sent")

    context = {
        "support_messages" : support_messages,
        "total_messages" : support_messages.count(),
        "topics" : support_messages.values_list("topic", flat=True).distinct(),
    }

    return render(request, "admin-support.html", context)

@require_POST
def mark_support_read(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    support = get_object_or_404(Support, id = id)
    if support.status == "UNREAD":
        support.status = "READ"
        support.save()
    add_audit_log(request, "Support marked read", f"{support.subject} from {support.user.user.username}")
    return redirect("admin_support")

@require_POST
def mark_support_replied(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    support = get_object_or_404(Support, id = id)
    support.status = "REPLIED"
    support.save()
    add_audit_log(request, "Support marked replied", f"{support.subject} from {support.user.user.username}")
    return redirect("admin_support")

def admin_deposits(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    deposits = Deposit.objects.select_related("user").order_by("-date_requested")
    pending_count = deposits.filter(status = "PENDING").count()

    context = {
        "deposits" : deposits,
        "pending_count" : pending_count,
    }

    return render(request, "admin-deposits.html", context)

@require_POST
def approve_deposit(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    with transaction.atomic():
        deposit = Deposit.objects.select_for_update().select_related("user").get(id=id)
        PlatformSettings.load()
        platform = PlatformSettings.objects.select_for_update().get(pk=1)
        normalized_hash = deposit.tx_hash.strip().upper()
        duplicate_hash = (
            Deposit.objects.filter(tx_hash_key=normalized_hash)
            .exclude(pk=deposit.pk)
            .exists()
            if normalized_hash
            else False
        )
        if deposit.status == "PENDING" and (
            not valid_wallet_type(deposit.wallet_type, platform)
            or not valid_tx_hash(deposit.tx_hash)
            or not deposit.amount.is_finite()
            or deposit.amount <= 0
            or duplicate_hash
        ):
            messages.error(request, "Deposit network, amount, or transaction hash is invalid")
            return redirect("admin_deposits")
        if deposit.status == "PENDING":
            account = Account.objects.select_for_update().get(user=deposit.user)
            pending_transaction = pending_financial_transaction(
                deposit.user,
                deposit.id,
                "DEPOSIT",
                deposit.amount,
            )
            if pending_transaction is None:
                messages.error(request, "Deposit ledger record is missing or invalid")
                return redirect("admin_deposits")
            account.balance = F("balance") + deposit.amount
            account.save(update_fields=["balance"])
            deposit.status = "APPROVED"
            deposit.date_resolved = timezone.now()
            deposit.tx_hash_key = normalized_hash
            deposit.save(update_fields=["status", "date_resolved", "tx_hash_key"])
            pending_transaction.status = "COMPLETED"
            pending_transaction.save(update_fields=["status"])
            add_audit_log(request, "Approved deposit", f"{deposit.amount} for {deposit.user.username}")

    return redirect("admin_deposits")


@require_POST
def reject_deposit(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    with transaction.atomic():
        deposit = Deposit.objects.select_for_update().select_related("user").get(id=id)
        if deposit.status == "PENDING":
            deposit.status = "REJECTED"
            deposit.date_resolved = timezone.now()
            deposit.save(update_fields=["status", "date_resolved"])
            Transaction.objects.filter(
                user=deposit.user,
                tx_type="DEPOSIT",
                related_id=deposit.id,
                status="PENDING",
            ).update(status="REJECTED")
            add_audit_log(request, "Rejected deposit", f"{deposit.amount} for {deposit.user.username}")

    return redirect("admin_deposits")

def admin_audit_logs(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    logs = AuditLog.objects.select_related("admin").order_by("-date")

    context = {
        "logs" : logs,
    }

    return render(request, "admin-logs.html", context)

def admin_settings(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    platform = PlatformSettings.load()

    if request.method == "POST":
        form = request.POST
        wallet_type = form.get("wallet-type", "").strip().upper()
        wallet_address = form.get("wallet-address", "").strip()
        raw_reward = form.get("referral-reward", "").strip()

        try:
            reward = Decimal(raw_reward).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError):
            messages.error(request, "Enter a valid referral reward")
            return redirect("admin_settings")
        if (
            not wallet_type
            or len(wallet_type) > 50
            or not wallet_address
            or len(wallet_address) > 150
        ):
            messages.error(request, "Wallet type and a valid wallet address are required")
            return redirect("admin_settings")
        if (
            not reward.is_finite()
            or reward < 0
            or reward > MAX_REFERRAL_REWARD
        ):
            messages.error(request, "Enter a valid referral reward")
            return redirect("admin_settings")

        with transaction.atomic():
            platform = PlatformSettings.objects.select_for_update().get(pk=1)
            current_wallet_type = platform.wallet_type.strip().upper()
            if (
                wallet_type != current_wallet_type
                and Account.objects.exclude(account_type__iexact=current_wallet_type).exists()
            ):
                messages.error(
                    request,
                    "Existing accounts use a different wallet type; update those accounts before changing platform settings",
                )
                return redirect("admin_settings")
            platform.wallet_type = wallet_type
            platform.wallet_address = wallet_address
            platform.referral_reward = reward
            platform.save(update_fields=["wallet_type", "wallet_address", "referral_reward", "date_updated"])
            add_audit_log(request, "Updated platform settings", f"{wallet_type} wallet, referral reward ${reward}")
        messages.success(request, "Platform settings saved")
        return redirect("admin_settings")

    context = {
        "platform" : platform,
    }

    return render(request, "admin-settings.html", context)