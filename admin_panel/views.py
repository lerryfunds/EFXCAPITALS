from django.http import Http404
from django.core.exceptions import BadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from core.models import Packages, Account, Withdrawal, Support, Deposit, Transaction, AuditLog, PlatformSettings
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from decimal import Decimal, InvalidOperation
User = get_user_model()

def add_audit_log(request, action, detail=""):
    AuditLog.objects.create(admin=request.user, action=action, detail=detail)

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
        form = request.POST

        package_name = form.get("package-name")
        subtype = form.get("subtype")
        description = form.get("package-description")
        roi = form.get("roi-cycle")
        payout_cycle = form.get("payout-cycle")
        duration =  form.get("duration")
        interval = form.get("interval")
        min_amount = Decimal(form.get("min-amount"))
        max_amount = Decimal(form.get("max-amount"))
        is_featured = form.get("featured?")

        if is_featured == "on":
            is_featured = True
        else:
            is_featured = False

        new_package = Packages.objects.create(
            name = package_name, 
            subtype = subtype,
            description = description,
            roi = roi,
            cycle = payout_cycle,
            duration = duration,
            interval = interval,
            min_amount = min_amount,
            max_amount = max_amount,
            is_featured = is_featured
            )
        new_package.save()
        add_audit_log(request, "Created package", package_name)

        return redirect("admin_packages_list")


    
    return render(request, "admin-package-form.html")

def admin_toggle_package_active(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    package = Packages.objects.get(id = id)

    if package is not None:
        package.is_active = True if package.is_active == False else False
        package.save()
        add_audit_log(request, "Toggled package", f"{package.name} -> {'active' if package.is_active else 'disabled'}")
    else:
        messages.error(request, "package not found")

    return redirect("admin_packages_list")

def admin_package_edit(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")
    package = Packages.objects.get(id = id)

    if request.method == "POST":
        form = request.POST
        
        package_name = form.get("package-name")
        subtype = form.get("subtype")
        description = form.get("description")
        roi = form.get("roi-cycle")
        payout_cycle = form.get("payout-cycle")
        duration =  form.get("duration")
        interval = form.get("interval")
        min_amount = Decimal(form.get("min-amount"))
        max_amount = Decimal(form.get("max-amount"))
        is_featured = form.get("featured?")

        if is_featured == "on":
            is_featured = True
        else:
            is_featured = False

        package.name = package_name
        package.subtype = subtype
        package.description = description
        package.roi = roi
        package.cycle = payout_cycle
        package.duration = duration
        package.interval = interval
        package.min_amount = min_amount
        package.max_amount = max_amount
        package.is_featured = is_featured
        package.save()
        add_audit_log(request, "Edited package", package_name)

        return redirect("admin_packages_list")

    context = {
        "package" : package,
        "package_name" : package.name,
        "package_subtype" : package.subtype,
        "package_roi" : package.roi,
        "package_cycle" : package.cycle,
        "package_duration" : package.duration,
        "package_intervals" : package.interval,
        "package_min_amount" : package.min_amount,
        "package_max_amount" : package.max_amount,
        "package_is_featured?" : package.is_featured,
    }

    return render(request, "admin-package-form.html", context)

def admin_package_delete(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")
    package = Packages.objects.get(id = id)
    add_audit_log(request, "Deleted package", package.name)
    package.delete()
    return redirect("admin_packages_list")

def admin_user_create(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    if request.method == "POST":
        form = request.POST

        full_name = form.get("full_name")
        full_name = full_name.split(" ")
        if len(full_name) < 2:
            messages.error(request, "Please enter 2 names in the full name input box")
            return redirect("admin_user_create")
        first_name = full_name[0]
        last_name = full_name[1]

        username = form.get("username")
        if username and User.objects.filter(username = username).exists():
            messages.error(request, "User with username already exists")
            return redirect("admin_user_create")

        email = form.get("email")
        wallet_type = form.get("wallet-type")
        wallet_address = form.get("address")
        wallet_balance = Decimal(form.get("balance"))
        password = form.get("password")
        c_password = form.get("c_password")
        if password != c_password:
            messages.error(request, "Passwords don't match try again")
            return redirect("admin_user_create")
        is_admin = True if form.get("role") == "admin" else False
        is_active = True if form.get("status") == "active" else False

        user = User.objects.create_user(
            username = username,
            first_name = first_name,
            last_name = last_name,
            email = email,
            is_superuser = is_admin,
            is_active = is_active
        )

        user.set_password(password)

        account = Account.objects.create(
            user = user,
            account_type = wallet_type,
            balance = wallet_balance,
            wallet_address = wallet_address,
        )

        user.save()
        account.save()
        add_audit_log(request, "Created user", username)
        return redirect("admin_users_view")
    
    return render(request, "admin-user-form.html")

def admin_user_delete(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")
    user = User.objects.get(user_id = id)
    account = Account.objects.get(user = user)
    add_audit_log(request, "Deleted user", user.username)
    user.delete()
    account.delete()
    return redirect("admin_users_view")

def admin_user_edit(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    user = User.objects.get(user_id = id)
    account = Account.objects.get(user = user)

    if request.method == "POST":
        form = request.POST

        full_name = form.get("full_name")
        full_name = full_name.split(" ")
        if len(full_name) < 2:
            messages.error(request, "Please enter 2 names in the full name input box")
            return redirect("admin_user_edit", id = id)
        first_name = full_name[0]
        last_name = full_name[1]

        username = form.get("username")
        if username and User.objects.filter(username = username).exclude(user_id = user.user_id).exists():
            messages.error(request, "User with username already exists")
            return redirect("admin_user_edit", id = id)

        email = form.get("email")
        # wallet_type = form.get("wallet-type")
        # wallet_address = form.get("address")
        wallet_balance = Decimal(form.get("balance"))
        # password = form.get("password")
        # c_password = form.get("c_password")
        # if password != c_password:
        #     messages.error(request, "Passwords don't match try again")
            # return redirect("admin_user_create")
        is_admin = True if form.get("role") == "admin" else False
        is_active = True if form.get("status") == "active" else False

        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        # user.username = username
        # user.is_active = is_active
        # user.is_superuser = is_admin

        # user.set_password(password)

        account = Account.objects.get(user = user)
        print(type(wallet_balance))
        account.balance = wallet_balance

        user.save()
        account.save()
        add_audit_log(request, "Edited user", user.username)
        return redirect("admin_users_view")

    context = {
        "user" : user,
        "account" : account,
        "edit" : True,
    }
    
    return render(request, "admin-user-form.html", context)

def admin_toggle_user_activity(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")
    
    user = User.objects.get(user_id = id)
    user.is_active = True if user.is_active == False else False
    user.save()
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

def approve_withdrawal(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    withdrawal = get_object_or_404(Withdrawal, id = id)
    withdrawal.status = "APPROVED"
    withdrawal.save()
    if withdrawal.user_id:
        Transaction.objects.filter(user = withdrawal.user, tx_type = "WITHDRAWAL", related_id = withdrawal.id, status = "PENDING").update(status = "COMPLETED")
    add_audit_log(request, "Approved withdrawal", f"{withdrawal.amount} for {withdrawal.user.username if withdrawal.user else 'unknown'}")
    return redirect("admin_withdrawals", status="all")

def reject_withdrawal(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    withdrawal = get_object_or_404(Withdrawal, id = id)
    if withdrawal.status == "PENDING" and withdrawal.user_id:
        account = Account.objects.filter(user = withdrawal.user).first()
        if account:
            account.balance += withdrawal.amount
            account.save()
        Transaction.objects.filter(user = withdrawal.user, tx_type = "WITHDRAWAL", related_id = withdrawal.id, status = "PENDING").update(status = "REJECTED")

    withdrawal.status = "REJECTED"
    withdrawal.save()
    add_audit_log(request, "Rejected withdrawal", f"{withdrawal.amount} for {withdrawal.user.username if withdrawal.user else 'unknown'}")
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

def mark_support_read(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    support = get_object_or_404(Support, id = id)
    if support.status == "UNREAD":
        support.status = "READ"
        support.save()
    add_audit_log(request, "Support marked read", f"{support.subject} from {support.user.user.username}")
    return redirect("admin_support")

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

def approve_deposit(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    deposit = get_object_or_404(Deposit, id = id)
    if deposit.status == "PENDING":
        account = get_object_or_404(Account, user = deposit.user)
        account.balance += deposit.amount
        account.save()
        deposit.status = "APPROVED"
        deposit.date_resolved = timezone.now()
        deposit.save()
        Transaction.objects.filter(user = deposit.user, tx_type = "DEPOSIT", related_id = deposit.id, status = "PENDING").update(status = "COMPLETED")
        add_audit_log(request, "Approved deposit", f"{deposit.amount} for {deposit.user.username}")

    return redirect("admin_deposits")

def reject_deposit(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    deposit = get_object_or_404(Deposit, id = id)
    if deposit.status == "PENDING":
        deposit.status = "REJECTED"
        deposit.date_resolved = timezone.now()
        deposit.save()
        Transaction.objects.filter(user = deposit.user, tx_type = "DEPOSIT", related_id = deposit.id, status = "PENDING").update(status = "REJECTED")
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

        wallet_type = form.get("wallet-type", "").strip()
        wallet_address = form.get("wallet-address", "").strip()
        raw_reward = form.get("referral-reward", "").strip()

        if wallet_type and wallet_address:
            platform.wallet_type = wallet_type
            platform.wallet_address = wallet_address
            try:
                reward = Decimal(raw_reward)
                if reward >= 0:
                    platform.referral_reward = reward
            except InvalidOperation:
                pass
            platform.save()
            add_audit_log(request, "Updated platform settings", f"{wallet_type} wallet, referral reward ${platform.referral_reward}")
            messages.success(request, "Platform settings saved")
        else:
            messages.error(request, "Wallet type and wallet address are required")
        return redirect("admin_settings")

    context = {
        "platform" : platform,
    }

    return render(request, "admin-settings.html", context)