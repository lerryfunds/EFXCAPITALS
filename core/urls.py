from django.urls import path
from . import views

urlpatterns = [
    # AUTH URLS
    path('login/', views.login_view, name="login"),
    path('register/', views.register_view, name="register"),

    # LANDING URLS
    path('', views.home_view, name="home"),
    path('privacy/', views.privacy_view, name="privacy"),

    # LOGOUT URL
    path('logout/', views.logout_view, name="logout")
]
