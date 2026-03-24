from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import AdminUserChangeForm, AdminUserCreationForm
from .models import Listing, Offer, Transaction, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = AdminUserCreationForm
    form = AdminUserChangeForm
    model = User
    ordering = ("-date_joined",)
    list_display = ("phone_number", "email", "name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active", "is_superuser")
    search_fields = ("phone_number", "email", "name")

    fieldsets = (
        (None, {"fields": ("phone_number", "email", "name", "password")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone_number", "email", "name", "password1", "password2", "is_staff", "is_active"),
            },
        ),
    )


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "seller", "price", "status", "is_negotiable", "updated_at")
    list_filter = ("status", "is_negotiable", "category", "condition")
    search_fields = ("title", "seller__phone_number", "seller__email", "seller__name")
    autocomplete_fields = ("seller",)


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("listing", "buyer", "seller", "amount", "status", "expires_at")
    list_filter = ("status",)
    search_fields = ("listing__title", "buyer__phone_number", "buyer__email", "seller__phone_number")
    autocomplete_fields = ("listing", "buyer", "seller")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "listing",
        "buyer",
        "seller",
        "amount",
        "status",
        "payment_reference",
        "is_released",
        "updated_at",
    )
    list_filter = ("status", "is_released")
    search_fields = (
        "listing__title",
        "buyer__phone_number",
        "buyer__email",
        "seller__phone_number",
        "payment_reference",
    )
    autocomplete_fields = ("listing", "offer", "buyer", "seller")
