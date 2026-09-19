from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from core.models import Packages, Account
from django.contrib import messages
User = get_user_model()

# Create your views here.
def admin_dashboard(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    context = {
        "total_users" : User.objects.all().count(),
        "active_users" : User.objects.filter(is_active = True).count(),
        "active_packages" : Packages.objects.filter(is_active = True).count(),
        "recent_users" : Account.objects.all().order_by("-date_created")[:5],
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
        min_amount = form.get("min-amount")
        max_amount = form.get("max-amount")
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

        return redirect("admin_packages_list")


    
    return render(request, "admin-package-form.html")

def admin_toggle_package_active(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    package = Packages.objects.get(id = id)

    if package is not None:
        package.is_active = True if package.is_active == False else False
        package.save()
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
        min_amount = form.get("min-amount")
        max_amount = form.get("max-amount")
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
    package.delete()
    return redirect("admin_packages_list")

def admin_user_create(request):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")

    if request.method == "POST":
        form = request.POST

        full_name = form.get("full_name")
        full_name = full_name.split(" ")
        first_name = full_name[0]
        last_name = full_name[1]

        username = form.get("username")
        if User.objects.filter(username = username):
            messages.error(request, "User with username already exists")
            return redirect("admin_user_create")

        email = form.get("email")
        wallet_type = form.get("wallet-type")
        wallet_address = form.get("address")
        wallet_balance = form.get("balance")
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
        return redirect("admin_users_view")
    
    return render(request, "admin-user-form.html")

def admin_user_delete(request, id):
    if not request.user.is_authenticated or not request.user.is_superuser or not request.user.is_active:
        return redirect("home")
    user = User.objects.get(user_id = id)
    account = Account.objects.get(user = user)
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
        first_name = full_name[0]
        last_name = full_name[1]

        username = form.get("username")
        if User.objects.filter(username = username):
            messages.error(request, "User with username already exists")
            return redirect("admin_user_create")

        email = form.get("email")
        # wallet_type = form.get("wallet-type")
        # wallet_address = form.get("address")
        wallet_balance = form.get("balance")
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

        account.balance = wallet_balance

        user.save()
        account.save()
        return redirect("admin_users_view")

    context = {
        "user" : user,
        "account" : account,
        "edit" : True,
    }
    
    return render(request, "admin-user-form.html", context)

def admin_toggle_user_activity(request, id):
    user = User.objects.get(user_id = id)
    user.is_active = True if user.is_active == False else False
    user.save()
    return redirect("admin_users_view")