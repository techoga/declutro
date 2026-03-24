from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone

from .models import Listing, Offer, Transaction
from .paystack import initialize_paystack_payment, verify_paystack_payment


OPEN_TRANSACTION_STATUSES = frozenset(
    {
        Transaction.Status.PENDING_PAYMENT,
        Transaction.Status.PAYMENT_IN_PROGRESS,
        Transaction.Status.PAYMENT_CONFIRMED,
        Transaction.Status.LOCKED,
        Transaction.Status.AWAITING_MEETUP,
        Transaction.Status.AWAITING_CONFIRMATION,
    }
)
PAYMENT_PENDING_STATUSES = frozenset(
    {
        Transaction.Status.PENDING_PAYMENT,
        Transaction.Status.PAYMENT_IN_PROGRESS,
    }
)
LOCKED_TRANSACTION_STATUSES = frozenset(
    {
        Transaction.Status.PAYMENT_CONFIRMED,
        Transaction.Status.LOCKED,
        Transaction.Status.AWAITING_MEETUP,
        Transaction.Status.AWAITING_CONFIRMATION,
        Transaction.Status.COMPLETED,
    }
)


class TransactionEngineError(Exception):
    """Domain error raised when a transaction action cannot continue."""


class ListingUnavailableError(TransactionEngineError):
    """Raised when a listing cannot accept another payment flow."""


class OfferStateError(TransactionEngineError):
    """Raised when an offer action is invalid for the current state."""


class PaymentStateError(TransactionEngineError):
    """Raised when a payment or verification action is invalid."""


@dataclass
class CheckoutSession:
    transaction: Transaction
    authorization_url: str
    reference: str


def _payment_window_hours():
    return int(getattr(settings, "DECLUTRO_PAYMENT_WINDOW_HOURS", 1) or 1)


def _accepted_offer_payment_window_hours():
    return int(getattr(settings, "DECLUTRO_ACCEPTED_OFFER_PAYMENT_WINDOW_HOURS", 2) or 2)


def _accepted_offer_expiration_hours():
    return int(getattr(settings, "DECLUTRO_OFFER_EXPIRATION_HOURS", 24) or 24)


def _generate_payment_reference(transaction):
    return f"declutro-{transaction.pk}-{uuid4().hex[:12]}"


def _has_locked_winner(listing_id, *, exclude_transaction_id=None):
    queryset = Transaction.objects.filter(
        listing_id=listing_id,
        status__in=LOCKED_TRANSACTION_STATUSES,
    )
    if exclude_transaction_id is not None:
        queryset = queryset.exclude(pk=exclude_transaction_id)
    return queryset.exists()


def expire_stale_records(now=None):
    now = now or timezone.now()

    pending_offer_queryset = Offer.objects.filter(
        status=Offer.Status.PENDING,
        expires_at__isnull=False,
        expires_at__lte=now,
    )
    pending_offer_count = pending_offer_queryset.update(
        status=Offer.Status.EXPIRED,
        responded_at=now,
    )

    accepted_offer_queryset = Offer.objects.filter(
        status=Offer.Status.ACCEPTED,
        expires_at__isnull=False,
        expires_at__lte=now,
    )
    accepted_offer_count = accepted_offer_queryset.update(
        status=Offer.Status.EXPIRED,
        responded_at=now,
    )

    stale_transaction_count = Transaction.objects.filter(
        status__in=PAYMENT_PENDING_STATUSES,
        expires_at__isnull=False,
        expires_at__lte=now,
    ).update(
        status=Transaction.Status.CANCELLED,
        closed_at=now,
    )

    auto_release_days = int(getattr(settings, "DECLUTRO_AUTO_RELEASE_DAYS", 0) or 0)
    auto_release_count = 0
    if auto_release_days > 0:
        auto_release_before = now - timedelta(days=auto_release_days)
        due_transactions = list(
            Transaction.objects.filter(
                status=Transaction.Status.AWAITING_CONFIRMATION,
                is_released=False,
                updated_at__lte=auto_release_before,
            ).select_related("listing")
        )
        for transaction in due_transactions:
            complete_transaction(transaction.pk, actor=transaction.buyer, auto_release=True)
        auto_release_count = len(due_transactions)

    return {
        "pending_offers": pending_offer_count,
        "accepted_offers": accepted_offer_count,
        "transactions": stale_transaction_count,
        "auto_released": auto_release_count,
    }


def create_or_refresh_buy_now_transaction(*, listing, buyer):
    now = timezone.now()

    with db_transaction.atomic():
        listing = Listing.objects.select_for_update().select_related("seller").get(pk=listing.pk)

        if buyer.pk == listing.seller_id:
            raise TransactionEngineError("You cannot buy your own listing.")
        if listing.status != Listing.Status.ACTIVE:
            raise ListingUnavailableError("This listing is no longer available.")
        if _has_locked_winner(listing.pk):
            raise ListingUnavailableError("This listing has already been locked by another verified payment.")

        accepted_offer = (
            Offer.objects.select_for_update()
            .filter(
                listing=listing,
                buyer=buyer,
                status=Offer.Status.ACCEPTED,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .order_by("-responded_at", "-created_at")
            .first()
        )

        amount = accepted_offer.amount if accepted_offer else listing.price
        payment_window_hours = (
            _accepted_offer_payment_window_hours() if accepted_offer else _payment_window_hours()
        )
        expires_at = now + timedelta(hours=payment_window_hours)

        transaction = (
            Transaction.objects.select_for_update()
            .filter(
                listing=listing,
                buyer=buyer,
                seller=listing.seller,
                status__in=PAYMENT_PENDING_STATUSES,
            )
            .order_by("-updated_at", "-created_at")
            .first()
        )

        if transaction is None:
            transaction = Transaction.objects.create(
                listing=listing,
                offer=accepted_offer,
                buyer=buyer,
                seller=listing.seller,
                amount=amount,
                status=Transaction.Status.PENDING_PAYMENT,
                expires_at=expires_at,
            )
        else:
            transaction.offer = accepted_offer
            transaction.amount = amount
            transaction.status = Transaction.Status.PENDING_PAYMENT
            transaction.expires_at = expires_at
            transaction.closed_at = None
            transaction.is_released = False
            transaction.save(
                update_fields=[
                    "offer",
                    "amount",
                    "status",
                    "expires_at",
                    "closed_at",
                    "is_released",
                    "updated_at",
                ]
            )

        return transaction


def start_checkout(*, transaction, callback_url):
    now = timezone.now()

    with db_transaction.atomic():
        transaction = (
            Transaction.objects.select_for_update()
            .select_related("listing", "buyer")
            .get(pk=transaction.pk)
        )

        if transaction.listing.status != Listing.Status.ACTIVE:
            raise ListingUnavailableError("This listing is no longer active for payment.")
        if transaction.status not in PAYMENT_PENDING_STATUSES:
            raise PaymentStateError("This transaction is no longer waiting for payment.")
        if transaction.expires_at and transaction.expires_at <= now:
            transaction.status = Transaction.Status.CANCELLED
            transaction.closed_at = now
            transaction.save(update_fields=["status", "closed_at", "updated_at"])
            raise PaymentStateError("This payment window has expired.")
        if _has_locked_winner(transaction.listing_id, exclude_transaction_id=transaction.pk):
            transaction.status = Transaction.Status.CANCELLED
            transaction.closed_at = now
            transaction.save(update_fields=["status", "closed_at", "updated_at"])
            raise ListingUnavailableError("Another buyer has already locked this listing.")

        if not transaction.buyer.email:
            raise PaymentStateError("Add an email address to your profile before starting payment.")

        reference = _generate_payment_reference(transaction)
        response = initialize_paystack_payment(
            amount=transaction.amount,
            email=transaction.buyer.email,
            reference=reference,
            callback_url=callback_url,
            metadata={
                "transaction_id": transaction.pk,
                "listing_id": transaction.listing_id,
                "buyer_id": transaction.buyer_id,
            },
        )

        transaction.payment_reference = reference
        transaction.status = Transaction.Status.PAYMENT_IN_PROGRESS
        transaction.save(update_fields=["payment_reference", "status", "updated_at"])

    return CheckoutSession(
        transaction=transaction,
        authorization_url=response.get("authorization_url", ""),
        reference=reference,
    )


def handle_successful_payment(*, reference):
    verification = verify_paystack_payment(reference)
    metadata = verification.get("metadata") or {}
    transaction_id = metadata.get("transaction_id")
    if not transaction_id:
        raise PaymentStateError("Paystack metadata is missing a transaction id.")

    paid_amount = int(verification.get("amount") or 0)
    now = timezone.now()

    with db_transaction.atomic():
        transaction = (
            Transaction.objects.select_for_update()
            .select_related("listing", "offer", "buyer", "seller")
            .get(pk=transaction_id)
        )
        listing = Listing.objects.select_for_update().get(pk=transaction.listing_id)

        if transaction.payment_reference and transaction.payment_reference != reference:
            raise PaymentStateError("Payment reference does not match this transaction.")
        if transaction.payment_reference in {None, ""}:
            transaction.payment_reference = reference

        expected_amount = int((Decimal(transaction.amount) * 100).quantize(Decimal("1")))
        if paid_amount != expected_amount:
            transaction.status = Transaction.Status.CANCELLED
            transaction.closed_at = now
            transaction.save(update_fields=["payment_reference", "status", "closed_at", "updated_at"])
            raise PaymentStateError("Verified payment amount does not match the transaction amount.")

        if transaction.status in {
            Transaction.Status.AWAITING_MEETUP,
            Transaction.Status.AWAITING_CONFIRMATION,
            Transaction.Status.COMPLETED,
        }:
            return transaction

        if listing.status != Listing.Status.ACTIVE or _has_locked_winner(
            listing.pk,
            exclude_transaction_id=transaction.pk,
        ):
            transaction.status = Transaction.Status.CANCELLED
            transaction.closed_at = now
            transaction.save(update_fields=["payment_reference", "status", "closed_at", "updated_at"])
            raise ListingUnavailableError("Another verified payment already locked this listing.")

        # Payment verification is the gate that wins the race and locks the listing.
        transaction.status = Transaction.Status.AWAITING_MEETUP
        transaction.expires_at = None
        transaction.closed_at = None
        transaction.save(
            update_fields=["payment_reference", "status", "expires_at", "closed_at", "updated_at"]
        )

        listing.status = Listing.Status.LOCKED
        listing.save(update_fields=["status", "updated_at"])

        if transaction.offer_id:
            transaction.offer.status = Offer.Status.ACCEPTED
            transaction.offer.expires_at = None
            transaction.offer.responded_at = transaction.offer.responded_at or now
            transaction.offer.save(update_fields=["status", "expires_at", "responded_at"])

        Transaction.objects.filter(
            listing_id=listing.pk,
            status__in=OPEN_TRANSACTION_STATUSES,
        ).exclude(pk=transaction.pk).update(
            status=Transaction.Status.CANCELLED,
            closed_at=now,
        )
        Offer.objects.filter(
            listing_id=listing.pk,
            status__in=[Offer.Status.PENDING, Offer.Status.ACCEPTED],
        ).exclude(pk=transaction.offer_id).update(
            status=Offer.Status.EXPIRED,
            responded_at=now,
        )

        return transaction


def accept_offer(*, offer, seller):
    now = timezone.now()

    with db_transaction.atomic():
        offer = (
            Offer.objects.select_for_update()
            .select_related("listing", "buyer", "seller")
            .get(pk=offer.pk)
        )
        listing = Listing.objects.select_for_update().get(pk=offer.listing_id)

        if offer.seller_id != seller.pk:
            raise PermissionDenied("Only the seller can accept this offer.")
        if offer.status != Offer.Status.PENDING:
            raise OfferStateError("This offer is no longer pending.")
        if offer.expires_at and offer.expires_at <= now:
            offer.status = Offer.Status.EXPIRED
            offer.responded_at = now
            offer.save(update_fields=["status", "responded_at"])
            raise OfferStateError("This offer has already expired.")
        if listing.status != Listing.Status.ACTIVE:
            raise ListingUnavailableError("Only active listings can accept offers.")
        if _has_locked_winner(listing.pk):
            raise ListingUnavailableError("This listing is already locked by a verified payment.")
        if (
            Offer.objects.select_for_update()
            .filter(
                listing_id=listing.pk,
                status=Offer.Status.ACCEPTED,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .exclude(pk=offer.pk)
            .exists()
        ):
            raise OfferStateError("Another accepted offer is still within its payment window.")

        payment_deadline = now + timedelta(hours=_accepted_offer_payment_window_hours())
        offer.status = Offer.Status.ACCEPTED
        offer.expires_at = payment_deadline
        offer.responded_at = now
        offer.save(update_fields=["status", "expires_at", "responded_at"])

        Offer.objects.filter(
            listing_id=listing.pk,
            status=Offer.Status.PENDING,
        ).exclude(pk=offer.pk).update(
            status=Offer.Status.REJECTED,
            responded_at=now,
        )

        transaction = (
            Transaction.objects.select_for_update()
            .filter(
                listing_id=listing.pk,
                buyer_id=offer.buyer_id,
                seller_id=offer.seller_id,
                status__in=PAYMENT_PENDING_STATUSES | {Transaction.Status.CANCELLED},
            )
            .order_by("-updated_at", "-created_at")
            .first()
        )
        if transaction is None:
            transaction = Transaction.objects.create(
                listing=listing,
                offer=offer,
                buyer=offer.buyer,
                seller=offer.seller,
                amount=offer.amount,
                status=Transaction.Status.PENDING_PAYMENT,
                expires_at=payment_deadline,
            )
        else:
            transaction.offer = offer
            transaction.amount = offer.amount
            transaction.status = Transaction.Status.PENDING_PAYMENT
            transaction.expires_at = payment_deadline
            transaction.closed_at = None
            transaction.is_released = False
            transaction.save(
                update_fields=[
                    "offer",
                    "amount",
                    "status",
                    "expires_at",
                    "closed_at",
                    "is_released",
                    "updated_at",
                ]
            )

        return transaction


def reject_offer(*, offer, seller):
    now = timezone.now()

    with db_transaction.atomic():
        offer = (
            Offer.objects.select_for_update()
            .select_related("listing", "buyer", "seller")
            .get(pk=offer.pk)
        )

        if offer.seller_id != seller.pk:
            raise PermissionDenied("Only the seller can reject this offer.")
        if offer.status != Offer.Status.PENDING:
            raise OfferStateError("This offer is no longer pending.")

        offer.status = Offer.Status.REJECTED
        offer.responded_at = now
        offer.save(update_fields=["status", "responded_at"])

        Transaction.objects.filter(
            offer=offer,
            status__in=PAYMENT_PENDING_STATUSES,
        ).update(
            status=Transaction.Status.CANCELLED,
            closed_at=now,
        )

        return offer


def trigger_payout_stub(transaction):
    """Escrow release is simulated for MVP; real transfer wiring stays out of scope."""
    return {
        "transaction_id": transaction.pk,
        "amount": str(transaction.amount),
        "released": transaction.is_released,
    }


def complete_transaction(transaction_id, *, actor, auto_release=False):
    now = timezone.now()

    with db_transaction.atomic():
        transaction = (
            Transaction.objects.select_for_update()
            .select_related("listing", "buyer", "seller")
            .get(pk=transaction_id)
        )
        listing = Listing.objects.select_for_update().get(pk=transaction.listing_id)

        if transaction.buyer_id != actor.pk:
            raise PermissionDenied("Only the buyer can confirm this transaction.")
        if transaction.status == Transaction.Status.COMPLETED:
            return transaction
        if transaction.status not in {
            Transaction.Status.AWAITING_MEETUP,
            Transaction.Status.AWAITING_CONFIRMATION,
        }:
            raise TransactionEngineError("This transaction cannot be confirmed yet.")

        transaction.status = Transaction.Status.COMPLETED
        transaction.is_released = True
        transaction.closed_at = now
        if auto_release and transaction.meetup_at is None:
            transaction.meetup_at = now
        transaction.save(
            update_fields=["status", "is_released", "closed_at", "meetup_at", "updated_at"]
        )

        listing.status = Listing.Status.SOLD
        listing.save(update_fields=["status", "updated_at"])

        trigger_payout_stub(transaction)
        return transaction


def offer_expiration_deadline():
    return timezone.now() + timedelta(hours=_accepted_offer_expiration_hours())
