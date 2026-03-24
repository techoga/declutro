from django.urls import path

from . import views


urlpatterns = [
    path("", views.home_view, name="home"),
    path("about/", views.info_page_view, {"slug": "about"}, name="about_page"),
    path("contact/", views.info_page_view, {"slug": "contact"}, name="contact_page"),
    path("privacy/", views.info_page_view, {"slug": "privacy"}, name="privacy_page"),
    path("terms/", views.info_page_view, {"slug": "terms"}, name="terms_page"),
    path("listings/<int:listing_id>/", views.listing_detail_view, name="listing_detail"),
    path("listings/<int:listing_id>/buy-now/", views.buy_now, name="buy_now"),
    path("listings/<int:listing_id>/make-offer/", views.create_offer, name="create_offer"),
    path("offers/<int:offer_id>/accept/", views.accept_offer, name="accept_offer"),
    path("offers/<int:offer_id>/reject/", views.reject_offer, name="reject_offer"),
    path(
        "transactions/<int:transaction_id>/confirm/",
        views.confirm_transaction,
        name="confirm_transaction",
    ),
    path("payments/paystack/webhook/", views.paystack_webhook, name="paystack_webhook"),
    path("auth/login/", views.login_view, name="auth_login"),
    path("auth/signup/", views.signup_view, name="auth_signup"),
    path("auth/forgot-password/", views.forgot_password_view, name="auth_forgot_password"),
    path("auth/reset-password/", views.reset_password_notice_view, name="auth_reset_password_notice"),
    path(
        "auth/reset-password/<uidb64>/<token>/",
        views.reset_password_confirm_view,
        name="auth_reset_password_confirm",
    ),
    path("auth/logout/", views.logout_view, name="auth_logout"),
    path("dashboard/", views.dashboard_view, name="dashboard_home"),
    path("dashboard/transactions/", views.transactions_view, name="dashboard_transactions"),
    path("dashboard/listings/", views.listings_view, name="dashboard_listings"),
    path("dashboard/listings/new/", views.sell_item_view, name="dashboard_sell_item"),
    path("dashboard/listings/<int:listing_id>/edit/", views.edit_listing_view, name="dashboard_listing_edit"),
    path(
        "dashboard/listings/<int:listing_id>/deactivate/",
        views.deactivate_listing_view,
        name="dashboard_listing_deactivate",
    ),
    path("dashboard/profile/", views.profile_view, name="dashboard_profile"),
    path("dashboard/compliance/", views.compliance_view, name="dashboard_compliance"),
    path("dashboard/update-password/", views.update_password_view, name="dashboard_update_password"),
]
