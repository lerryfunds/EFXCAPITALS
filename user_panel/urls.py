from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name="dashboard"),
    path('withdraw/', views.withdraw, name="withdraw"),
    path('investments/', views.investments, name="investments"),
    path('transactions/', views.transactions, name="transactions"),
    path('deposit/', views.deposit, name="deposit"),
    path('referrals/', views.referrals, name="referrals"),
    path('settings/', views.settings, name="settings"),
    path('support/', views.support, name="support"),
    path('packages/', views.packages, name="packages"),
    path('package/activate/<uuid:id>/', views.activate, name="package-activate")
]
