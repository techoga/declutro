import json
import logging
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST

from .dashboard import build_dashboard_context
from .forms import (
    ComplianceUpdateForm,
    ForgotPasswordForm,
    ListingForm,
    LoginForm,
    OfferSubmissionForm,
    PasswordUpdateForm,
    ProfileUpdateForm,
    ResetPasswordForm,
    SignupForm,
)
from .models import Listing, Offer, Transaction
from .paystack import PaystackError, verify_webhook_signature
from .services import NotificationError, send_password_reset_notification
from .transaction_engine import (
    ListingUnavailableError,
    OfferStateError,
    PaymentStateError,
    TransactionEngineError,
    accept_offer as accept_offer_flow,
    complete_transaction,
    create_or_refresh_buy_now_transaction,
    expire_stale_records,
    handle_successful_payment,
    offer_expiration_deadline,
    reject_offer as reject_offer_flow,
    start_checkout,
)
from .utils import mask_identifier


logger = logging.getLogger(__name__)
User = get_user_model()

PUBLIC_SORT_OPTIONS = {
    "newest": {
        "label": "Newest",
        "ordering": ["-created_at", "-updated_at"],
    },
    "price_asc": {
        "label": "Price: Low to High",
        "ordering": ["price", "-created_at"],
    },
    "price_desc": {
        "label": "Price: High to Low",
        "ordering": ["-price", "-created_at"],
    },
}

PUBLIC_PAGES = {
    "about": {
        "title": "About Declutro",
        "eyebrow": "Company",
        "headline": "Fast second-hand deals with less uncertainty.",
        "copy": (
            "Declutro is built for high-intent transactions. Buyers can pay to reserve items, "
            "inspect before the seller gets paid, and move from discovery to decision without the "
            "usual marketplace noise."
        ),
        "support_title": "What makes the experience different",
        "support_copy": "The product is designed around certainty, speed, and cleaner transaction handoffs.",
        "facts": [
            {
                "title": "Protected reservation",
                "copy": "Buyers can act fast without forcing the seller to rely on vague promises or endless chats.",
            },
            {
                "title": "Inspection-first release",
                "copy": "Funds stay protected until the buyer confirms the item matches what was listed.",
            },
            {
                "title": "High-intent inventory",
                "copy": "Listings are structured to move people from interest to commitment with less friction.",
            },
        ],
    },
    "contact": {
        "title": "Contact Declutro",
        "eyebrow": "Support",
        "headline": "Need help with a listing or live transaction?",
        "copy": (
            "Reach the Declutro team at hello@declutro.com for support, seller onboarding, or "
            "trust and safety questions."
        ),
        "support_title": "How support is organized",
        "support_copy": "The team focuses on trust, seller readiness, and live transaction resolution.",
        "facts": [
            {
                "title": "Trust and safety",
                "copy": "Report suspicious behavior, listing issues, or anything that puts a transaction at risk.",
            },
            {
                "title": "Seller onboarding",
                "copy": "Get help preparing listings that are clearer, faster to trust, and easier to close.",
            },
            {
                "title": "Live transaction help",
                "copy": "If a handoff or protected payment step feels unclear, support can help you move forward.",
            },
        ],
    },
    "privacy": {
        "title": "Privacy Policy",
        "eyebrow": "Legal",
        "headline": "Your data should support trust, not create friction.",
        "copy": (
            "Declutro uses account, transaction, and verification data to secure payments, prevent "
            "fraud, and keep item handoffs traceable."
        ),
        "support_title": "What the policy is designed to protect",
        "support_copy": "Privacy on Declutro exists to support safer transactions, not to create unnecessary drag.",
        "facts": [
            {
                "title": "Identity and account data",
                "copy": "Contact and profile details help keep accounts recoverable and buyers or sellers identifiable.",
            },
            {
                "title": "Payment and transaction data",
                "copy": "Payment references and transaction states help prove what happened and when it happened.",
            },
            {
                "title": "Operational notifications",
                "copy": "Reset links, security prompts, and critical flow updates are used to keep accounts safe.",
            },
        ],
    },
    "terms": {
        "title": "Terms of Service",
        "eyebrow": "Legal",
        "headline": "Clear rules for buyers, sellers, and protected payments.",
        "copy": (
            "Listings must be accurate, meetups must reflect the agreed handoff, and payment holds "
            "remain conditional until inspection is confirmed."
        ),
        "support_title": "Principles behind the rules",
        "support_copy": "The terms are built to keep listings accurate, payments protected, and handoffs accountable.",
        "facts": [
            {
                "title": "Accurate listing information",
                "copy": "Sellers must describe products honestly, including defects, so buyers can decide with confidence.",
            },
            {
                "title": "Protected payment flow",
                "copy": "Payment reservations are designed to secure the item without releasing funds too early.",
            },
            {
                "title": "Confirmed completion",
                "copy": "Transactions close only after the buyer verifies the handoff or the platform can resolve the state.",
            },
        ],
    },
}

PUBLIC_NAV_ITEMS = (
    {
        "key": "home",
        "label": "Marketplace",
        "href_name": "home",
    },
    {
        "key": "about",
        "label": "About",
        "href_name": "about_page",
    },
    {
        "key": "contact",
        "label": "Support",
        "href_name": "contact_page",
    },
)

DASHBOARD_NAV_ITEMS = (
    {
        "key": "dashboard",
        "label": "Overview",
        "href_name": "dashboard_home",
        "icon": "overview",
    },
    {
        "key": "transactions",
        "label": "Transactions",
        "href_name": "dashboard_transactions",
        "icon": "transactions",
    },
    {
        "key": "listings",
        "label": "Listings",
        "href_name": "dashboard_listings",
        "icon": "listings",
    },
)


def _public_shell_context(active_nav, *, public_search_value="", show_public_search=True):
    nav_items = []
    for item in PUBLIC_NAV_ITEMS:
        nav_items.append(
            {
                "key": item["key"],
                "label": item["label"],
                "href": reverse(item["href_name"]),
                "is_active": item["key"] == active_nav,
            }
        )

    return {
        "public_nav_items": nav_items,
        "public_show_search": show_public_search,
        "public_search_value": public_search_value,
        "sell_href": reverse("dashboard_sell_item"),
    }


def _dashboard_shell_context(
    active_nav,
    *,
    page_title,
    page_eyebrow,
    page_heading,
    page_description,
    page_variant="section",
    page_action=None,
):
    nav_items = []
    for item in DASHBOARD_NAV_ITEMS:
        nav_items.append(
            {
                "key": item["key"],
                "label": item["label"],
                "href": reverse(item["href_name"]),
                "icon": item["icon"],
                "is_active": item["key"] == active_nav,
            }
        )

    return {
        "page_title": page_title,
        "active_nav": active_nav,
        "page_variant": page_variant,
        "page_eyebrow": page_eyebrow,
        "page_heading": page_heading,
        "page_description": page_description,
        "page_action": page_action,
        "dashboard_nav_items": nav_items,
    }


def home_view(request):
    expire_stale_records()
    listings = Listing.objects.filter(status=Listing.Status.ACTIVE).select_related("seller")
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    location = request.GET.get("location", "").strip()
    sort = request.GET.get("sort", "newest").strip()
    negotiable_only = request.GET.get("negotiable") in {"1", "true", "on"}

    if q:
        listings = listings.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q)
        )
    if category in Listing.Category.values:
        listings = listings.filter(category=category)
    else:
        category = ""
    if location:
        listings = listings.filter(location__iexact=location)
    if negotiable_only:
        listings = listings.filter(is_negotiable=True)

    sort_config = PUBLIC_SORT_OPTIONS.get(sort, PUBLIC_SORT_OPTIONS["newest"])
    if sort not in PUBLIC_SORT_OPTIONS:
        sort = "newest"
    listings = listings.order_by(*sort_config["ordering"])

    active_listings = Listing.objects.filter(status=Listing.Status.ACTIVE)
    distinct_sellers = (
        active_listings.filter(Q(seller__is_identity_verified=True) | Q(seller__is_email_verified=True))
        .values("seller_id")
        .distinct()
        .count()
    )

    active_listing_count = active_listings.count()
    negotiable_listing_count = active_listings.filter(is_negotiable=True).count()

    return render(
        request,
        "home.html",
        {
            "page_title": "Secure second-hand deals",
            "listings": [_serialize_public_listing(listing) for listing in listings],
            "categories": [{"value": value, "label": label} for value, label in Listing.Category.choices],
            "locations": list(
                active_listings.exclude(location="")
                .order_by("location")
                .values_list("location", flat=True)
                .distinct()
            ),
            "sort_options": [
                {"value": value, "label": config["label"]}
                for value, config in PUBLIC_SORT_OPTIONS.items()
            ],
            "selected_filters": {
                "q": q,
                "category": category,
                "location": location,
                "sort": sort,
                "negotiable": negotiable_only,
            },
            "listing_count": active_listing_count,
            "verified_seller_count": distinct_sellers,
            "market_stats": [
                {
                    "value": active_listing_count,
                    "label": "Live listings",
                    "caption": "Fresh inventory ready for protected checkout.",
                },
                {
                    "value": distinct_sellers,
                    "label": "Verified sellers",
                    "caption": "Seller signals that reduce uncertainty before you commit.",
                },
                {
                    "value": negotiable_listing_count,
                    "label": "Offer-enabled items",
                    "caption": "Inventory that still leaves room for price flexibility.",
                },
            ],
            "market_promises": [
                "Reserve high-demand items with a protected payment hold.",
                "Inspect before seller funds are released.",
                "Use cleaner listing context to decide faster with less noise.",
            ],
            **_public_shell_context("home", public_search_value=q, show_public_search=True),
        },
    )


def info_page_view(request, slug):
    page = PUBLIC_PAGES.get(slug)
    if page is None:
        raise Http404

    return render(
        request,
        "info_page.html",
        {
            "page_title": page["title"],
            "page_data": page,
            **_public_shell_context(
                "about" if slug == "about" else "contact" if slug == "contact" else "",
                public_search_value="",
                show_public_search=False,
            ),
        },
    )


def listing_detail_view(request, listing_id):
    expire_stale_records()
    listing = get_object_or_404(
        Listing.objects.select_related("seller"),
        pk=listing_id,
        status=Listing.Status.ACTIVE,
    )
    return render(request, "listing_detail.html", _build_listing_detail_context(request, listing))


def _paystack_callback_url(request):
    configured_url = (getattr(settings, "PAYSTACK_CALLBACK_URL", "") or "").strip()
    if configured_url:
        return configured_url
    return request.build_absolute_uri(reverse("dashboard_transactions"))


@login_required
@require_POST
def buy_now(request, listing_id):
    expire_stale_records()
    listing = get_object_or_404(Listing.objects.select_related("seller"), pk=listing_id)

    try:
        transaction = create_or_refresh_buy_now_transaction(listing=listing, buyer=request.user)
        checkout_session = start_checkout(transaction=transaction, callback_url=_paystack_callback_url(request))
    except (TransactionEngineError, PaystackError) as exc:
        messages.error(request, str(exc))
        return redirect("listing_detail", listing_id=listing.pk)

    if not checkout_session.authorization_url:
        messages.error(request, "Unable to start payment right now.")
        return redirect("listing_detail", listing_id=listing.pk)

    messages.info(request, f"Redirecting you to Paystack to complete payment for {listing.title}.")
    return redirect(checkout_session.authorization_url)


@login_required
@require_POST
def create_offer(request, listing_id):
    expire_stale_records()
    listing = get_object_or_404(Listing.objects.select_related("seller"), pk=listing_id)
    accepted_offer = (
        Offer.objects.filter(
            listing=listing,
            buyer=request.user,
            status=Offer.Status.ACCEPTED,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .first()
    )

    if request.user.pk == listing.seller_id:
        messages.error(request, "You cannot send an offer on your own listing.")
        return redirect("listing_detail", listing_id=listing.pk)
    if listing.status != Listing.Status.ACTIVE:
        messages.error(request, "This listing is no longer available for offers.")
        return redirect("home")
    if accepted_offer is not None:
        messages.info(request, "Your offer is already accepted. Complete payment before the window expires.")
        return redirect("dashboard_transactions")
    if not listing.is_negotiable:
        messages.error(request, "Offers are disabled for this listing.")
        return redirect("listing_detail", listing_id=listing.pk)

    form = OfferSubmissionForm(listing, request.POST)
    if not form.is_valid():
        context = _build_listing_detail_context(request, listing, offer_form=form, offer_modal_open=True)
        return render(request, "listing_detail.html", context, status=400)

    expires_at = offer_expiration_deadline()
    offer = Offer.objects.filter(
        listing=listing,
        buyer=request.user,
        seller=listing.seller,
        status=Offer.Status.PENDING,
    ).first()
    if offer is None:
        Offer.objects.create(
            listing=listing,
            buyer=request.user,
            seller=listing.seller,
            amount=form.cleaned_data["amount"],
            status=Offer.Status.PENDING,
            expires_at=expires_at,
        )
    else:
        offer.amount = form.cleaned_data["amount"]
        offer.expires_at = expires_at
        offer.responded_at = None
        offer.save(update_fields=["amount", "expires_at", "responded_at"])

    messages.success(request, f"Offer sent for {listing.title}. The seller can accept or reject it.")
    return redirect("listing_detail", listing_id=listing.pk)


@login_required
@require_POST
def accept_offer(request, offer_id):
    expire_stale_records()
    offer = get_object_or_404(Offer.objects.select_related("listing", "buyer", "seller"), pk=offer_id)

    try:
        transaction = accept_offer_flow(offer=offer, seller=request.user)
    except (OfferStateError, ListingUnavailableError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Offer accepted. {transaction.buyer.display_name} now has a limited payment window to pay.",
        )
    return redirect("dashboard_listings")


@login_required
@require_POST
def reject_offer(request, offer_id):
    expire_stale_records()
    offer = get_object_or_404(Offer.objects.select_related("listing", "buyer", "seller"), pk=offer_id)

    try:
        reject_offer_flow(offer=offer, seller=request.user)
    except (OfferStateError, TransactionEngineError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    else:
        messages.info(request, "Offer rejected.")
    return redirect("dashboard_listings")


@login_required
@require_POST
def confirm_transaction(request, transaction_id):
    expire_stale_records()
    transaction = get_object_or_404(
        Transaction.objects.select_related("listing", "buyer", "seller"),
        pk=transaction_id,
    )

    try:
        complete_transaction(transaction.pk, actor=request.user)
    except (TransactionEngineError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Item confirmed. Funds are now marked for release to the seller.")
    return redirect("dashboard_transactions")


@csrf_exempt
@require_POST
def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature", "")
    if not verify_webhook_signature(request.body, signature):
        return JsonResponse({"ok": False, "detail": "Invalid webhook signature."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON payload."}, status=400)

    if payload.get("event") != "charge.success":
        return JsonResponse({"ok": True, "ignored": True})

    reference = (payload.get("data") or {}).get("reference")
    if not reference:
        return JsonResponse({"ok": False, "detail": "Missing payment reference."}, status=400)

    try:
        transaction = handle_successful_payment(reference=reference)
    except (ListingUnavailableError, PaymentStateError, TransactionEngineError) as exc:
        logger.warning("Paystack webhook processed with a non-winning outcome for %s: %s", reference, exc)
        return JsonResponse({"ok": True, "detail": str(exc)})
    except Transaction.DoesNotExist:
        return JsonResponse({"ok": False, "detail": "Transaction not found."}, status=404)
    except PaystackError as exc:
        logger.exception("Paystack verification failed for %s", reference)
        return JsonResponse({"ok": False, "detail": str(exc)}, status=502)

    return JsonResponse(
        {
            "ok": True,
            "transaction_id": transaction.pk,
            "status": transaction.status,
        }
    )


def _safe_redirect(request, fallback):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return reverse(fallback)


def _get_user_from_uid(uidb64):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        return User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


def _find_user_for_reset(identifier, kind):
    if kind == "email":
        return User.objects.filter(email__iexact=identifier, is_active=True).first()
    return User.objects.filter(phone_number=identifier, is_active=True).first()


def _format_money(amount):
    value = Decimal(amount)
    if value == value.quantize(Decimal("1")):
        return f"NGN {int(value):,}"
    return f"NGN {value:,.2f}"


def _placeholder_image(title):
    label = title[:36]
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='960' height='720' viewBox='0 0 960 720'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0%' stop-color='#0f172a'/>"
        "<stop offset='55%' stop-color='#154084'/>"
        "<stop offset='100%' stop-color='#ca6a1d'/></linearGradient></defs>"
        "<rect width='960' height='720' rx='56' fill='url(#g)'/>"
        "<circle cx='794' cy='128' r='128' fill='rgba(255,255,255,0.12)'/>"
        "<circle cx='150' cy='620' r='240' fill='rgba(255,255,255,0.09)'/>"
        "<text x='80' y='580' fill='#f8fafc' font-size='72' font-family='Arial, sans-serif'>"
        f"{label}"
        "</text></svg>"
    )
    return f"data:image/svg+xml,{quote(svg)}"


def _listing_badges(listing):
    badges = []
    if listing.is_hot:
        badges.append("Hot")
    if listing.is_new_arrival:
        badges.append("New")
    if listing.is_negotiable:
        badges.append("Negotiable")
    return badges


def _seller_is_verified(seller):
    return seller.trust_score >= 60


def _seller_trust_summary(user):
    level = user.trust_level
    next_step = {
        "high": "Your seller profile already carries strong trust signals across identity, contact, and business details.",
        "trusted": "One more strong signal, like identity or business documentation, will push this profile into high trust.",
        "standard": "Complete one or two more trust signals so buyers can commit with less hesitation.",
        "new": "Add stronger trust signals so buyers can move from browsing to payment with more confidence.",
    }[level]
    return {
        "score": user.trust_score,
        "level": level,
        "level_label": user.trust_level_label,
        "tone": user.trust_tone,
        "account_type_label": user.get_account_type_display(),
        "business_name": user.business_name,
        "social_handle": user.social_handle_display,
        "next_step": next_step,
    }


def _listing_form_preview(listing=None):
    if not listing:
        return {
            "cover_url": "",
            "gallery_items": [],
            "video_items": [],
        }

    image_gallery = list(listing.image_gallery)
    return {
        "cover_url": image_gallery[0] if image_gallery else "",
        "gallery_items": [
            {
                "url": url,
                "label": f"Gallery image {index}",
            }
            for index, url in enumerate(image_gallery[1:], start=1)
        ],
        "video_items": [
            {
                "url": url,
                "label": f"Product video {index}",
            }
            for index, url in enumerate(listing.video_gallery, start=1)
        ],
    }
 

def _listing_media_gallery(listing):
    image_urls = list(listing.image_gallery)
    video_urls = list(listing.video_gallery)

    media_items = [
        {
            "kind": "image",
            "url": url,
            "poster_url": url,
            "thumb_url": url,
            "label": f"{listing.title} image {index}",
        }
        for index, url in enumerate(image_urls, start=1)
    ]
    media_items.extend(
        {
            "kind": "video",
            "url": url,
            "poster_url": image_urls[0] if image_urls else "",
            "thumb_url": image_urls[0] if image_urls else "",
            "label": f"{listing.title} video {index}",
        }
        for index, url in enumerate(video_urls, start=1)
    )

    if not media_items:
        fallback_url = _placeholder_image(listing.title)
        media_items.append(
            {
                "kind": "image",
                "url": fallback_url,
                "poster_url": fallback_url,
                "thumb_url": fallback_url,
                "label": f"{listing.title} image 1",
            }
        )

    return media_items


def _serialize_public_listing(listing):
    trust_summary = _seller_trust_summary(listing.seller)
    return {
        "id": listing.pk,
        "title": listing.title,
        "price_display": _format_money(listing.price),
        "category_label": listing.get_category_display(),
        "condition_label": listing.get_condition_display(),
        "location": listing.location or "Location on request",
        "image_url": listing.primary_image_url or _placeholder_image(listing.title),
        "detail_url": reverse("listing_detail", kwargs={"listing_id": listing.pk}),
        "badges": _listing_badges(listing),
        "seller_signal": trust_summary["level_label"],
        "seller_trust_tone": trust_summary["tone"],
        "action_label": "Buy now or make offer" if listing.is_negotiable else "Buy now available",
        "is_negotiable": listing.is_negotiable,
    }


def _build_listing_detail_context(request, listing, offer_form=None, offer_modal_open=False):
    detail_url = reverse("listing_detail", kwargs={"listing_id": listing.pk})
    media_gallery = _listing_media_gallery(listing)
    is_owner = request.user.is_authenticated and request.user.pk == listing.seller_id
    offer_form = offer_form or OfferSubmissionForm(listing, initial={"amount": listing.price})
    trust_summary = _seller_trust_summary(listing.seller)

    return {
        "page_title": listing.title,
        "listing": {
            "id": listing.pk,
            "title": listing.title,
            "description": listing.description or "Seller has not added extra notes yet.",
            "price_display": _format_money(listing.price),
            "condition_label": listing.get_condition_display(),
            "category_label": listing.get_category_display(),
            "location": listing.location or "Location on request",
            "defects": listing.defects,
            "badges": _listing_badges(listing),
            "gallery": media_gallery,
            "primary_media": media_gallery[0],
            "primary_image_url": listing.primary_image_url or media_gallery[0]["poster_url"],
            "seller_name": listing.seller.display_name,
            "seller_initials": listing.seller.initials,
            "seller_trust_label": trust_summary["level_label"],
            "seller_trust_score": trust_summary["score"],
            "seller_trust_tone": trust_summary["tone"],
            "seller_social_handle": listing.seller.social_handle_display,
            "seller_account_type": listing.seller.get_account_type_display(),
            "is_negotiable": listing.is_negotiable,
            "buy_now_url": reverse("buy_now", kwargs={"listing_id": listing.pk}),
            "make_offer_url": reverse("create_offer", kwargs={"listing_id": listing.pk}),
            "edit_url": reverse("dashboard_listing_edit", kwargs={"listing_id": listing.pk}) if listing.pk else "",
            "summary_items": [
                {"label": "Category", "value": listing.get_category_display()},
                {"label": "Condition", "value": listing.get_condition_display()},
                {"label": "Location", "value": listing.location or "Location on request"},
                {"label": "Pricing", "value": "Offers enabled" if listing.is_negotiable else "Fixed-price listing"},
            ],
            "trust_items": [
                {"label": "Seller trust", "value": f"{trust_summary['level_label']} · {trust_summary['score']}/100"},
                {"label": "Account type", "value": listing.seller.get_account_type_display()},
                {"label": "Social presence", "value": listing.seller.social_handle_display or "Not shared yet"},
                {"label": "Checkout model", "value": "Protected reservation"},
                {"label": "Release rule", "value": "After buyer confirmation"},
                {
                    "label": "Business docs",
                    "value": "CAC on file" if listing.seller.has_business_documents else "No CAC submitted",
                },
            ],
            "journey_steps": [
                "Reserve the item by starting checkout before someone else does.",
                "Inspect the item during the agreed handoff.",
                "Confirm the item so seller funds can be released.",
            ],
        },
        "is_owner": is_owner,
        "offer_form": offer_form,
        "offer_modal_open": offer_modal_open,
        "login_href": f"{reverse('auth_login')}?next={detail_url}",
        "signup_href": f"{reverse('auth_signup')}?next={detail_url}",
        **_public_shell_context("home", public_search_value="", show_public_search=True),
    }


@csrf_protect
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard_home")

    form = LoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        messages.success(request, "Welcome back to Declutro.")
        return redirect(_safe_redirect(request, "dashboard_home"))

    return render(
        request,
        "auth/login.html",
        {
            "form": form,
            "page_title": "Login",
        },
    )


@csrf_protect
def signup_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard_home")

    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="accounts.auth_backends.PhoneOrEmailBackend")
        messages.success(request, "Your account is ready. Welcome to Declutro.")
        return redirect("dashboard_home")

    return render(
        request,
        "auth/signup.html",
        {
            "form": form,
            "page_title": "Create account",
        },
    )


@csrf_protect
def forgot_password_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard_home")

    form = ForgotPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        identifier = form.cleaned_data["identifier"]
        kind = form.cleaned_data["identifier_kind"]
        user = _find_user_for_reset(identifier, kind)

        if user:
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = request.build_absolute_uri(
                reverse("auth_reset_password_confirm", kwargs={"uidb64": uidb64, "token": token})
            )
            try:
                send_password_reset_notification(user=user, channel=kind, reset_url=reset_url)
            except NotificationError:
                logger.exception("Failed to send password reset notification for user %s", user.pk)

        request.session["password_reset_notice"] = {
            "identifier": mask_identifier(identifier, kind),
            "channel": kind,
        }
        return redirect("auth_reset_password_notice")

    return render(
        request,
        "auth/forgot_password.html",
        {
            "form": form,
            "page_title": "Forgot password",
        },
    )


def reset_password_notice_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard_home")

    notice = request.session.get("password_reset_notice", {})
    return render(
        request,
        "auth/reset_password.html",
        {
            "mode": "notice",
            "notice": notice,
            "page_title": "Reset password",
        },
    )


@csrf_protect
def reset_password_confirm_view(request, uidb64, token):
    if request.user.is_authenticated:
        return redirect("dashboard_home")

    user = _get_user_from_uid(uidb64)
    valid_link = bool(user and default_token_generator.check_token(user, token))
    form = ResetPasswordForm(user, request.POST or None) if valid_link else None

    if request.method == "POST":
        if not valid_link:
            return HttpResponseNotAllowed(["GET"])
        if form.is_valid():
            form.save()
            messages.success(request, "Your password has been updated. Sign in with your new password.")
            return redirect("auth_login")

    return render(
        request,
        "auth/reset_password.html",
        {
            "mode": "form" if valid_link else "invalid",
            "form": form,
            "page_title": "Reset password",
        },
    )


@login_required
def dashboard_view(request):
    expire_stale_records()
    context = build_dashboard_context(request.user)
    context.update(
        _dashboard_shell_context(
            "dashboard",
            page_title="Dashboard",
            page_eyebrow="Overview",
            page_heading="Move every live deal forward.",
            page_description=(
                "Track listings, payments, trust readiness, and next actions from one cleaner workspace."
            ),
            page_variant="overview",
            page_action={
                "label": "Create listing",
                "href": reverse("dashboard_sell_item"),
                "kind": "primary",
            },
        )
    )
    return render(
        request,
        "dashboard/dashboard.html",
        context,
    )


@login_required
@csrf_protect
def profile_view(request):
    form = ProfileUpdateForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect("dashboard_profile")

    context = build_dashboard_context(request.user)
    context.update(
        {
            "form": form,
            **_dashboard_shell_context(
                "profile",
                page_title="Profile",
                page_eyebrow="Account",
                page_heading="Profile settings",
                page_description=(
                    "Keep your identity, recovery email, and sign-in number accurate without mixing it with trust documentation."
                ),
                page_variant="form",
                page_action={
                    "label": "Compliance",
                    "href": reverse("dashboard_compliance"),
                    "kind": "secondary",
                },
            ),
        }
    )
    return render(
        request,
        "dashboard/profile.html",
        context,
    )


@login_required
@csrf_protect
def compliance_view(request):
    form = ComplianceUpdateForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Compliance details updated.")
        return redirect("dashboard_compliance")

    context = build_dashboard_context(request.user)
    context.update(
        {
            "form": form,
            **_dashboard_shell_context(
                "compliance",
                page_title="Compliance",
                page_eyebrow="Trust",
                page_heading="Seller trust and compliance",
                page_description=(
                    "Surface the signals buyers rely on: contact readiness, social presence, and optional business documentation."
                ),
                page_variant="form",
                page_action={
                    "label": "Profile",
                    "href": reverse("dashboard_profile"),
                    "kind": "secondary",
                },
            ),
        }
    )
    return render(request, "dashboard/compliance.html", context)


@login_required
@csrf_protect
def update_password_view(request):
    form = PasswordUpdateForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Your password has been updated.")
        return redirect("dashboard_update_password")

    context = build_dashboard_context(request.user)
    context.update(
        {
            "form": form,
            **_dashboard_shell_context(
                "settings",
                page_title="Update password",
                page_eyebrow="Security",
                page_heading="Password and access",
                page_description=(
                    "Refresh your password without interrupting the rest of your current session."
                ),
                page_variant="form",
                page_action={
                    "label": "Compliance",
                    "href": reverse("dashboard_compliance"),
                    "kind": "secondary",
                },
            ),
        }
    )
    return render(
        request,
        "dashboard/update_password.html",
        context,
    )


@login_required
def transactions_view(request):
    expire_stale_records()
    context = build_dashboard_context(request.user)
    context.update(
        _dashboard_shell_context(
            "transactions",
            page_title="Transactions",
            page_eyebrow="Live activity",
            page_heading="Track every buying and selling deal with less noise.",
            page_description=(
                "Open transactions stay action-ready, while completed and cancelled history remains "
                "easy to scan when you need context."
            ),
            page_variant="section",
        )
    )
    return render(request, "dashboard/transactions.html", context)


@login_required
def listings_view(request):
    expire_stale_records()
    context = build_dashboard_context(request.user)
    context.update(
        _dashboard_shell_context(
            "listings",
            page_title="Listings",
            page_eyebrow="Seller workspace",
            page_heading="Keep inventory sharp, visible, and ready to convert.",
            page_description=(
                "Review what is live, what is locked, what is sold, and what still needs attention "
                "before it goes back into market."
            ),
            page_variant="section",
        )
    )
    return render(request, "dashboard/listings.html", context)


@login_required
@csrf_protect
def sell_item_view(request):
    form = ListingForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        listing = form.save(commit=False)
        listing.seller = request.user
        listing.save()
        form.save_media(listing)
        messages.success(request, "Your listing is live in Declutro.")
        return redirect("dashboard_listings")

    context = build_dashboard_context(request.user)
    context.update(
        {
            "form": form,
            "submit_label": "Create listing",
            "listing_media_preview": _listing_form_preview(),
            **_dashboard_shell_context(
                "listings",
                page_title="Sell item",
                page_eyebrow="Listing workspace",
                page_heading="Create a transaction-ready listing",
                page_description=(
                    "Add the product details, pricing, and imagery buyers need so offers and "
                    "payment can happen without extra back-and-forth."
                ),
                page_variant="form",
            ),
        }
    )
    return render(
        request,
        "dashboard/listing_form.html",
        context,
    )


@login_required
@csrf_protect
def edit_listing_view(request, listing_id):
    listing = get_object_or_404(Listing, pk=listing_id, seller=request.user)
    form = ListingForm(request.POST or None, request.FILES or None, instance=listing)
    if request.method == "POST" and form.is_valid():
        listing = form.save(commit=False)
        listing.save()
        form.save_media(listing)
        messages.success(request, "Listing updated.")
        return redirect("dashboard_listings")

    context = build_dashboard_context(request.user)
    context.update(
        {
            "form": form,
            "listing": listing,
            "listing_media_preview": _listing_form_preview(listing),
            "submit_label": "Save listing",
            **_dashboard_shell_context(
                "listings",
                page_title="Edit listing",
                page_eyebrow="Listing update",
                page_heading=f"Edit {listing.title}",
                page_description=(
                    "Refine pricing, status, imagery, and notes without leaving the seller "
                    "workspace."
                ),
                page_variant="form",
            ),
        }
    )
    return render(
        request,
        "dashboard/listing_form.html",
        context,
    )


@require_POST
@login_required
def deactivate_listing_view(request, listing_id):
    listing = get_object_or_404(Listing, pk=listing_id, seller=request.user)
    listing.status = Listing.Status.INACTIVE
    listing.save(update_fields=["status", "updated_at"])
    messages.success(request, "Listing moved to inactive.")
    return redirect("dashboard_listings")


@require_POST
@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("auth_login")
