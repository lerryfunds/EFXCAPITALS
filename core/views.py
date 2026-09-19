from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.contrib import messages
User = get_user_model()
from .models import Account, Packages

# Create your views here.
def home_view(request):
    packages = Packages.objects.filter(is_active = True).order_by("-is_featured")
    context = {
        "is_logged_in" : request.user.is_authenticated,
        "is_admin" : request.user.is_superuser,
        "active_packages" : packages[:5]
    }
    return render(request, "index.html", context)

def privacy_view(request):
    return render(request, "privacy.html")

def login_view(request):
    if request.user.is_authenticated:
        return redirect("dasboard")

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
            print("error")

    
    return render(request, "login.html")

def register_view(request):
    if request.method == "POST":
        form = request.POST

        full_name = form.get("full_name")
        full_name = full_name.split(" ")
        if len(full_name) < 2:
            messages.error(request, "Please enter 2 names in the full name input box")
            return redirect("register")
        first_name = full_name[0]
        last_name = full_name[1]

        username = form.get("username")
        if User.objects.filter(username = username):
            messages.error(request, "User with username already exists")
            return redirect("register")

        email = form.get("email")
        wallet_type = form.get("wallet-type")
        wallet_address = form.get("address")
        password = form.get("password")
        c_password = form.get("c_password")
        if password != c_password:
            messages.error(request, "Passwords don't match try again")
            return redirect("register")

        user = User.objects.create_user(
            username = username,
            first_name = first_name,
            last_name = last_name,
            email = email,
        )

        user.set_password(password)

        account = Account.objects.create(
            user = user,
            account_type = wallet_type,
            wallet_address = wallet_address,
        )

        user.save()
        account.save()
        return redirect("login")
    
    return render(request, "register.html")



def logout_view(request):
    if not request.user.is_authenticated:
        return redirect("home")

    logout(request)
    return redirect("home")