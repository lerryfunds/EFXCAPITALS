from django.contrib import admin
from .models import PlatformSettings, PaymentRail, Wallet
# Register your models here.

@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(PaymentRail)
class PaymentRailAdmin(admin.ModelAdmin):
    list_display = ("label", "key", "is_active", "address", "date_updated")
    list_filter = ("is_active", "symbol")
    search_fields = ("key", "label", "address")
    readonly_fields = ("key", "symbol", "network", "display_order")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "asset", "balance", "is_active", "date_updated")
    list_filter = ("asset", "is_active")
    search_fields = ("user__username", "user__email", "address")
    readonly_fields = ("date_created", "date_updated")
