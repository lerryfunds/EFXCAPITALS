from django.urls import path
from . import views

urlpatterns = [
    path('', views.admin_dashboard, name="admin_dashboard"),
    path('users/', views.admin_users, name="admin_users_view"),
    path('user/create/', views.admin_user_create, name="admin_user_create"),
    path('user/delete/<uuid:id>/', views.admin_user_delete, name="user_delete"),
    path('user/edit/<uuid:id>/', views.admin_user_edit, name="user_edit"),
    path('user/toggle_activity/<uuid:id>/', views.admin_toggle_user_activity, name="user_toggle_activity"),
    path('packages/', views.admin_package_list, name="admin_packages_list"),
    path('package/create/', views.admin_package_create, name="package_create"),
    path('package/edit/<uuid:id>', views.admin_package_edit, name="package_edit"),
    path('package/delete/<uuid:id>', views.admin_package_delete, name="package_delete"),
    path('package/toggle/is_active/<uuid:id>/', views.admin_toggle_package_active, name="toggle_package_active"),
]