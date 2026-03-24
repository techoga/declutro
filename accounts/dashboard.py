from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .models import Listing, Offer, Transaction, User


TRANSACTION_STATUS_TONES = {
    Transaction.Status.PENDING_PAYMENT: "warning",
    Transaction.Status.PAYMENT_IN_PROGRESS: "warning",
    Transaction.Status.PAYMENT_CONFIRMED: "info",
    Transaction.Status.LOCKED: "info",
    Transaction.Status.AWAITING_MEETUP: "info",
    Transaction.Status.AWAITING_CONFIRMATION: "success",
    Transaction.Status.COMPLETED: "success",
    Transaction.Status.CANCELLED: "danger",
    Transaction.Status.DISPUTED: "danger",
}

LISTING_STATUS_TONES = {
    Listing.Status.ACTIVE: "success",
    Listing.Status.LOCKED: "warning",
    Listing.Status.SOLD: "neutral",
    Listing.Status.INACTIVE: "danger",
    Listing.Status.DRAFT: "warning",
}


def build_dashboard_context(user):
    transactions = list(
        Transaction.objects.filter(Q(buyer=user) | Q(seller=user))
        .select_related("listing", "buyer", "seller", "offer")
        .order_by("-updated_at", "-created_at")
    )
    listings = list(
        Listing.objects.filter(seller=user)
        .annotate(offer_total=Count("offers"))
        .order_by("-updated_at", "-created_at")
    )
    pending_offers = list(
        Offer.objects.filter(seller=user, status=Offer.Status.PENDING)
        .select_related("listing", "buyer", "seller")
        .order_by("expires_at", "-created_at")
    )

    using_demo_data = not transactions and not listings and not pending_offers
    if using_demo_data:
        transactions, listings, pending_offers = _build_demo_dataset(user)

    open_transactions = [transaction for transaction in transactions if not transaction.is_closed]
    closed_transactions = [transaction for transaction in transactions if transaction.is_closed]

    buying_transactions = [
        _serialize_transaction(transaction, user)
        for transaction in open_transactions
        if transaction.role_for(user) == "buying"
    ]
    selling_transactions = [
        _serialize_transaction(transaction, user)
        for transaction in open_transactions
        if transaction.role_for(user) == "selling"
    ]

    listing_columns = {
        "active": {
            "title": "Active Listings",
            "items": [
                _serialize_listing(listing, using_demo_data)
                for listing in listings
                if listing.status == Listing.Status.ACTIVE
            ],
        },
        "locked": {
            "title": "Locked Listings",
            "items": [
                _serialize_listing(listing, using_demo_data)
                for listing in listings
                if listing.status == Listing.Status.LOCKED
            ],
        },
        "sold": {
            "title": "Sold Listings",
            "items": [
                _serialize_listing(listing, using_demo_data)
                for listing in listings
                if listing.status == Listing.Status.SOLD
            ],
        },
        "inactive": {
            "title": "Inactive / Draft",
            "items": [
                _serialize_listing(listing, using_demo_data)
                for listing in listings
                if listing.status in {Listing.Status.INACTIVE, Listing.Status.DRAFT}
            ],
        },
    }

    action_items = _build_action_items(user, open_transactions, pending_offers)
    verification_items, verification_cta = _build_verification_items(user)

    return {
        "using_demo_data": using_demo_data,
        "dashboard_metrics": [
            {
                "label": "Pending actions",
                "value": len(action_items),
                "caption": "Urgent tasks blocking live deals.",
            },
            {
                "label": "Buying now",
                "value": len(buying_transactions),
                "caption": "Purchases still in the controlled flow.",
            },
            {
                "label": "Selling now",
                "value": len(selling_transactions),
                "caption": "Sell-side deals waiting on payment or meetup steps.",
            },
            {
                "label": "Live listings",
                "value": len(listing_columns["active"]["items"]) + len(listing_columns["locked"]["items"]),
                "caption": "Inventory still in motion, including locked items awaiting confirmation.",
            },
        ],
        "action_items": action_items,
        "buying_transactions": buying_transactions,
        "selling_transactions": selling_transactions,
        "closed_transactions": [_serialize_closed_transaction(transaction) for transaction in closed_transactions],
        "listing_columns": listing_columns,
        "verification_items": verification_items,
        "verification_cta": verification_cta,
        "open_transactions_total": len(open_transactions),
        "transactions_total": len(open_transactions) + len(closed_transactions),
        "closed_transactions_total": len(closed_transactions),
        "listings_total": len(listings),
    }


def _build_action_items(user, transactions, pending_offers):
    now = timezone.now()
    items = []

    for transaction in transactions:
        role = transaction.role_for(user)
        primary_action = _transaction_primary_action(transaction, role)
        timer_label = _transaction_timer_label(transaction)

        if role == "buying" and transaction.status in {
            Transaction.Status.PENDING_PAYMENT,
            Transaction.Status.PAYMENT_IN_PROGRESS,
        }:
            items.append(
                {
                    "title": "Complete payment",
                    "description": f"First verified payment wins and locks {transaction.listing.title}.",
                    "status": timer_label or transaction.get_status_display(),
                    "cta_label": primary_action["label"],
                    "cta_kind": primary_action["kind"],
                    "cta_href": primary_action.get("href"),
                    "cta_action": primary_action.get("action"),
                    "tone": "warning",
                    "priority": 1,
                    "sort_at": transaction.expires_at or transaction.updated_at or now,
                }
            )
        elif role == "buying" and transaction.status in {
            Transaction.Status.AWAITING_MEETUP,
            Transaction.Status.AWAITING_CONFIRMATION,
        }:
            items.append(
                {
                    "title": "Confirm item",
                    "description": f"Inspect {transaction.listing.title}, then confirm so funds can be released.",
                    "status": timer_label or transaction.get_status_display(),
                    "cta_label": primary_action["label"],
                    "cta_kind": primary_action["kind"],
                    "cta_href": primary_action.get("href"),
                    "cta_action": primary_action.get("action"),
                    "tone": "success",
                    "priority": 2,
                    "sort_at": transaction.updated_at or now,
                }
            )
        elif role == "selling" and transaction.status in {
            Transaction.Status.PAYMENT_CONFIRMED,
            Transaction.Status.LOCKED,
            Transaction.Status.AWAITING_MEETUP,
        }:
            items.append(
                {
                    "title": "Prepare for meetup",
                    "description": f"{transaction.listing.title} has a winning payment. Coordinate the handoff.",
                    "status": timer_label or transaction.get_status_display(),
                    "cta_label": "View Details",
                    "cta_kind": "link",
                    "cta_href": _transaction_href(transaction),
                    "tone": "info",
                    "priority": 3,
                    "sort_at": transaction.updated_at or now,
                }
            )

    for offer in pending_offers:
        items.append(
            {
                "title": "Respond to buyer offer",
                "description": f"{offer.buyer.display_name} offered {_format_money(offer.amount)} for {offer.listing.title}.",
                "status": _relative_deadline(offer.expires_at) or offer.get_status_display(),
                "cta_label": "Accept Offer",
                "cta_kind": "form",
                "cta_action": reverse("accept_offer", kwargs={"offer_id": offer.pk}),
                "secondary_cta_label": "Reject",
                "secondary_cta_kind": "form",
                "secondary_cta_action": reverse("reject_offer", kwargs={"offer_id": offer.pk}),
                "tone": "warning",
                "priority": 2,
                "sort_at": offer.expires_at or offer.created_at or now,
            }
        )

    items.sort(key=lambda item: (item["priority"], item["sort_at"] is None, item["sort_at"]))
    for item in items:
        item.pop("priority", None)
        item.pop("sort_at", None)
    return items


def _serialize_transaction(transaction, user):
    role = transaction.role_for(user)
    counterparty = transaction.counterparty_for(user)
    primary_action = _transaction_primary_action(transaction, role)
    meta_bits = [role.title()]
    timer_label = _transaction_timer_label(transaction)

    if timer_label:
        meta_bits.append(timer_label)
    elif transaction.meetup_at:
        meta_bits.append(_meetup_label(transaction.meetup_at))
    else:
        meta_bits.append(_date_label(transaction.updated_at or transaction.created_at))

    return {
        "id": _object_key(transaction, "transaction"),
        "item_name": transaction.listing.title,
        "price_display": _format_money(transaction.amount),
        "counterparty_label": "Seller" if role == "buying" else "Buyer",
        "counterparty_name": counterparty.display_name,
        "status_key": transaction.status,
        "status_label": transaction.get_status_display(),
        "status_tone": TRANSACTION_STATUS_TONES.get(transaction.status, "neutral"),
        "next_step": _transaction_next_step(transaction, role),
        "next_action": primary_action["label"],
        "timer_label": timer_label,
        "timer_deadline": _transaction_timer_deadline(transaction),
        "cta_label": primary_action["label"],
        "cta_kind": primary_action["kind"],
        "cta_href": primary_action.get("href"),
        "cta_action": primary_action.get("action"),
        "detail_href": _transaction_href(transaction),
        "meta_line": " · ".join(meta_bits),
    }


def _serialize_closed_transaction(transaction):
    closed_at = transaction.closed_at or transaction.updated_at or transaction.created_at
    return {
        "id": _object_key(transaction, "transaction"),
        "item_name": transaction.listing.title,
        "price_display": _format_money(transaction.amount),
        "status_label": transaction.get_status_display(),
        "status_tone": TRANSACTION_STATUS_TONES.get(transaction.status, "neutral"),
        "date_label": _date_label(closed_at),
    }


def _serialize_listing(listing, using_demo_data):
    offer_total = int(getattr(listing, "offer_total", 0) or 0)
    key = _object_key(listing, "listing")

    return {
        "id": key,
        "image_url": listing.primary_image_url or _placeholder_image(listing.title),
        "title": listing.title,
        "price_display": _format_money(listing.price),
        "status_label": listing.get_status_display(),
        "status_tone": LISTING_STATUS_TONES.get(listing.status, "neutral"),
        "offer_total": offer_total,
        "offer_label": "No active offers" if offer_total == 0 else f"{offer_total} offer{'s' if offer_total != 1 else ''}",
        "detail_href": f"{reverse('dashboard_listings')}#listing-{key}",
        "edit_href": reverse("dashboard_sell_item")
        if using_demo_data or not listing.pk
        else reverse("dashboard_listing_edit", kwargs={"listing_id": listing.pk}),
        "deactivate_href": None
        if using_demo_data or not listing.pk or listing.status != Listing.Status.ACTIVE
        else reverse("dashboard_listing_deactivate", kwargs={"listing_id": listing.pk}),
        "can_deactivate": bool(listing.pk and listing.status == Listing.Status.ACTIVE and not using_demo_data),
    }


def _build_verification_items(user):
    phone_verified = bool(user.phone_number and user.is_phone_verified)
    email_verified = bool(user.email and user.is_email_verified)
    identity_verified = bool(user.is_identity_verified)

    items = [
        {
            "label": "Phone verified",
            "value": "Verified" if phone_verified else "Pending",
            "tone": "success" if phone_verified else "warning",
            "description": user.phone_number if phone_verified else "Add verification to unlock higher trust.",
        },
        {
            "label": "Email verified",
            "value": "Verified" if email_verified else "Pending",
            "tone": "success" if email_verified else "neutral",
            "description": user.email if email_verified else "Required for payment receipts and recovery.",
        },
        {
            "label": "Identity verification",
            "value": "Ready" if identity_verified else "Future-ready",
            "tone": "success" if identity_verified else "neutral",
            "description": "Reserved for higher-trust transactions and dispute handling.",
        },
    ]

    incomplete = [item for item in items[:2] if item["value"] != "Verified"]
    verification_cta = None
    if incomplete:
        verification_cta = {
            "label": "Complete verification to increase trust",
            "href": reverse("dashboard_profile"),
        }

    return items, verification_cta


def _transaction_primary_action(transaction, role):
    if role == "buying" and transaction.status in {
        Transaction.Status.PENDING_PAYMENT,
        Transaction.Status.PAYMENT_IN_PROGRESS,
    }:
        return {
            "label": "Pay Now",
            "kind": "form",
            "action": reverse("buy_now", kwargs={"listing_id": transaction.listing_id}),
        }
    if role == "buying" and transaction.status in {
        Transaction.Status.AWAITING_MEETUP,
        Transaction.Status.AWAITING_CONFIRMATION,
    }:
        return {
            "label": "Confirm Item",
            "kind": "form",
            "action": reverse("confirm_transaction", kwargs={"transaction_id": transaction.pk}),
        }
    return {
        "label": "View Details",
        "kind": "link",
        "href": _transaction_href(transaction),
    }


def _transaction_next_step(transaction, role):
    if role == "buying" and transaction.status in {
        Transaction.Status.PENDING_PAYMENT,
        Transaction.Status.PAYMENT_IN_PROGRESS,
    }:
        return "Complete full payment. The first verified payment is the only one that can lock the listing."
    if role == "buying" and transaction.status in {
        Transaction.Status.PAYMENT_CONFIRMED,
        Transaction.Status.LOCKED,
        Transaction.Status.AWAITING_MEETUP,
    }:
        return "Payment succeeded. Coordinate meetup with the seller, inspect the item, then confirm."
    if role == "buying" and transaction.status == Transaction.Status.AWAITING_CONFIRMATION:
        return "Inspection is done. Confirm the item so the seller can be paid."
    if role == "selling" and transaction.status in {
        Transaction.Status.PENDING_PAYMENT,
        Transaction.Status.PAYMENT_IN_PROGRESS,
    }:
        return "Waiting for the buyer's verified payment. No lock exists until that payment is confirmed."
    if role == "selling" and transaction.status in {
        Transaction.Status.PAYMENT_CONFIRMED,
        Transaction.Status.LOCKED,
        Transaction.Status.AWAITING_MEETUP,
    }:
        return "Item is locked to the winning buyer. Prepare for meetup and inspection."
    if role == "selling" and transaction.status == Transaction.Status.AWAITING_CONFIRMATION:
        return "Buyer needs to confirm the item before funds can be released."
    return "This transaction is closed."


def _transaction_timer_deadline(transaction):
    if transaction.status in {
        Transaction.Status.PENDING_PAYMENT,
        Transaction.Status.PAYMENT_IN_PROGRESS,
    }:
        return transaction.expires_at
    if transaction.status == Transaction.Status.AWAITING_CONFIRMATION:
        return transaction.auto_release_at
    return None


def _transaction_timer_label(transaction):
    deadline = _transaction_timer_deadline(transaction)
    if not deadline:
        return ""

    label = _relative_deadline(deadline)
    if not label:
        return ""
    if transaction.status == Transaction.Status.AWAITING_CONFIRMATION and transaction.auto_release_at:
        return label.replace("Expires", "Auto-release")
    return label


def _transaction_href(transaction):
    return f"{reverse('dashboard_transactions')}#transaction-{_object_key(transaction, 'transaction')}"


def _object_key(obj, prefix):
    return getattr(obj, "pk", None) or getattr(obj, "id", None) or f"demo-{prefix}"


def _format_money(amount):
    value = Decimal(amount)
    if value == value.quantize(Decimal("1")):
        return f"NGN {int(value):,}"
    return f"NGN {value:,.2f}"


def _relative_deadline(value):
    if not value:
        return ""

    delta = value - timezone.now()
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "Expired"

    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    days = hours // 24

    if days >= 1:
        return f"Expires in {days}d"
    if hours >= 1:
        return f"Expires in {hours}h"
    return f"Expires in {max(minutes, 1)}m"


def _meetup_label(value):
    if not value:
        return ""
    return f"Meetup {timezone.localtime(value).strftime('%b %d · %I:%M %p')}"


def _date_label(value):
    if not value:
        return ""
    return timezone.localtime(value).strftime("%b %d, %Y")


def _placeholder_image(title):
    label = title[:36]
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='240' viewBox='0 0 320 240'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0%' stop-color='#0f172a'/>"
        "<stop offset='100%' stop-color='#1d4ed8'/></linearGradient></defs>"
        "<rect width='320' height='240' rx='28' fill='url(#g)'/>"
        "<circle cx='248' cy='56' r='56' fill='rgba(255,255,255,0.12)'/>"
        "<circle cx='40' cy='208' r='96' fill='rgba(255,255,255,0.08)'/>"
        "<text x='28' y='196' fill='#f8fafc' font-size='24' font-family='Arial, sans-serif'>"
        f"{label}"
        "</text></svg>"
    )
    return f"data:image/svg+xml,{quote(svg)}"


def _build_demo_dataset(user):
    now = timezone.now()
    buyer = user
    seller_a = User(name="Amina Sellers", phone_number="+2348000000001", email="amina@declutro.demo")
    seller_b = User(name="Lekan Devices", phone_number="+2348000000002", email="lekan@declutro.demo")
    buyer_a = User(name="Bola Ade", phone_number="+2348000000003", email="bola@declutro.demo")
    buyer_b = User(name="Mira Studio", phone_number="+2348000000004", email="mira@declutro.demo")

    iphone = Listing(
        id=101,
        seller=seller_a,
        title="iPhone 11 Pro 256GB",
        description="Battery 87%, boxed, and available for same-day pickup.",
        price=Decimal("395000.00"),
        image_url=_placeholder_image("iPhone 11 Pro"),
        status=Listing.Status.ACTIVE,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(hours=2),
    )
    iphone.offer_total = 0

    sony = Listing(
        id=102,
        seller=seller_b,
        title="Sony WH-1000XM5",
        description="Clean condition with original case and charger.",
        price=Decimal("215000.00"),
        image_url=_placeholder_image("Sony XM5"),
        status=Listing.Status.LOCKED,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(hours=5),
    )
    sony.offer_total = 1

    chair = Listing(
        id=103,
        seller=user,
        title="Herman Miller Sayl",
        description="Home-office chair in excellent condition.",
        price=Decimal("285000.00"),
        image_url=_placeholder_image("Sayl Chair"),
        status=Listing.Status.LOCKED,
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(hours=3),
    )
    chair.offer_total = 1

    camera = Listing(
        id=104,
        seller=user,
        title="Canon EOS M50 Kit",
        description="Mirrorless camera with lens, strap, and spare battery.",
        price=Decimal("325000.00"),
        image_url=_placeholder_image("Canon EOS M50"),
        status=Listing.Status.SOLD,
        created_at=now - timedelta(days=8),
        updated_at=now - timedelta(days=1),
    )
    camera.offer_total = 0

    desk = Listing(
        id=105,
        seller=user,
        title="Standing Desk 140cm",
        description="Draft listing pending new photos and final measurements.",
        price=Decimal("180000.00"),
        image_url=_placeholder_image("Standing Desk"),
        status=Listing.Status.DRAFT,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(hours=8),
    )
    desk.offer_total = 0

    pending_offer = Offer(
        id=201,
        listing=chair,
        buyer=buyer_a,
        seller=user,
        amount=Decimal("260000.00"),
        status=Offer.Status.PENDING,
        expires_at=now + timedelta(hours=5),
        created_at=now - timedelta(hours=2),
    )

    open_transactions = [
        Transaction(
            id=301,
            listing=iphone,
            buyer=buyer,
            seller=seller_a,
            status=Transaction.Status.PENDING_PAYMENT,
            amount=Decimal("395000.00"),
            expires_at=now + timedelta(hours=1),
            created_at=now - timedelta(hours=6),
            updated_at=now - timedelta(minutes=20),
        ),
        Transaction(
            id=302,
            listing=sony,
            buyer=buyer,
            seller=seller_b,
            status=Transaction.Status.AWAITING_CONFIRMATION,
            amount=Decimal("215000.00"),
            meetup_at=now - timedelta(hours=2),
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(minutes=50),
        ),
        Transaction(
            id=303,
            listing=chair,
            buyer=buyer_b,
            seller=user,
            status=Transaction.Status.AWAITING_MEETUP,
            amount=Decimal("285000.00"),
            meetup_at=now + timedelta(days=1, hours=2),
            created_at=now - timedelta(hours=10),
            updated_at=now - timedelta(minutes=35),
        ),
        Transaction(
            id=304,
            listing=chair,
            buyer=buyer_b,
            seller=user,
            status=Transaction.Status.PAYMENT_IN_PROGRESS,
            amount=Decimal("285000.00"),
            expires_at=now + timedelta(minutes=40),
            created_at=now - timedelta(hours=8),
            updated_at=now - timedelta(minutes=25),
        ),
    ]

    closed_transactions = [
        Transaction(
            id=305,
            listing=camera,
            buyer=buyer_a,
            seller=user,
            status=Transaction.Status.COMPLETED,
            amount=Decimal("325000.00"),
            is_released=True,
            closed_at=now - timedelta(days=1),
            created_at=now - timedelta(days=6),
            updated_at=now - timedelta(days=1),
        ),
        Transaction(
            id=306,
            listing=desk,
            buyer=buyer,
            seller=seller_b,
            status=Transaction.Status.CANCELLED,
            amount=Decimal("180000.00"),
            closed_at=now - timedelta(days=4),
            created_at=now - timedelta(days=5),
            updated_at=now - timedelta(days=4),
        ),
        Transaction(
            id=307,
            listing=iphone,
            buyer=buyer,
            seller=seller_a,
            status=Transaction.Status.DISPUTED,
            amount=Decimal("410000.00"),
            closed_at=now - timedelta(days=9),
            created_at=now - timedelta(days=11),
            updated_at=now - timedelta(days=9),
        ),
    ]

    return open_transactions + closed_transactions, [chair, camera, desk, sony], [pending_offer]
