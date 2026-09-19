from django.shortcuts import render, redirect

# Create your views here.
def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect("home")   
    return render(request, "dashboard.html")