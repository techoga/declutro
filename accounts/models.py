from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .utils import normalize_email_address, normalize_phone_number


def _listing_upload_path(prefix, filename):
    extension = Path(filename or "").suffix.lower()
    return f"listings/{prefix}/{uuid4().hex}{extension}"


def listing_primary_image_upload_to(instance, filename):
    return _listing_upload_path("primary", filename)


def listing_media_upload_to(instance, filename):
    folder = "videos" if instance.asset_type == ListingMedia.AssetType.VIDEO else "gallery"
    return _listing_upload_path(folder, filename)


def user_compliance_upload_to(instance, filename):
    extension = Path(filename or "").suffix.lower()
    return f"users/compliance/{uuid4().hex}{extension}"


def user_identity_upload_to(instance, filename):
    extension = Path(filename or "").suffix.lower()
    return f"users/identity/{uuid4().hex}{extension}"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone_number, password, **extra_fields):
        if not phone_number:
            raise ValueError("A phone number is required.")
        if not password:
            raise ValueError("A password is required.")

        email = normalize_email_address(extra_fields.get("email"))
        extra_fields["email"] = email
        user = self.model(
            phone_number=normalize_phone_number(phone_number),
            **extra_fields,
        )
        user.set_password(password)
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_user(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone_number, password, **extra_fields)

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(phone_number, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class AccountType(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        BUSINESS = "business", "Business"

    class IdentityDocumentType(models.TextChoices):
        NIN = "nin", "NIN"
        NATIONAL_ID = "national_id", "National ID"
        VOTERS_CARD = "voters_card", "Voter's Card"
        DRIVERS_LICENSE = "drivers_license", "Driver's License"

    phone_number = models.CharField(max_length=16, unique=True, db_index=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    name = models.CharField(max_length=150, blank=True)
    account_type = models.CharField(
        max_length=16,
        choices=AccountType.choices,
        default=AccountType.INDIVIDUAL,
    )
    business_name = models.CharField(max_length=180, blank=True)
    social_handle = models.CharField(max_length=120, blank=True)
    identity_document_type = models.CharField(
        max_length=24,
        choices=IdentityDocumentType.choices,
        blank=True,
    )
    nin_number = models.CharField(max_length=16, blank=True)
    identity_document = models.FileField(upload_to=user_identity_upload_to, blank=True)
    cac_certificate = models.FileField(upload_to=user_compliance_upload_to, blank=True)
    is_phone_verified = models.BooleanField(default=True)
    is_email_verified = models.BooleanField(default=False)
    is_identity_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["-date_joined"]

    def clean(self):
        super().clean()
        self.phone_number = normalize_phone_number(self.phone_number)
        self.email = normalize_email_address(self.email)

    def save(self, *args, **kwargs):
        self.phone_number = normalize_phone_number(self.phone_number)
        self.email = normalize_email_address(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.name or self.email or self.phone_number

    @property
    def initials(self):
        source = (self.name or self.email or self.phone_number).strip()
        bits = [bit for bit in source.replace("@", " ").replace(".", " ").split() if bit]
        if len(bits) >= 2:
            return (bits[0][0] + bits[1][0]).upper()
        return source[:2].upper()

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name or self.phone_number

    @property
    def social_handle_display(self):
        handle = (self.social_handle or "").strip()
        if handle and not handle.startswith("@") and "://" not in handle:
            return f"@{handle}"
        return handle

    @property
    def has_business_documents(self):
        return bool(self.cac_certificate)

    @property
    def normalized_nin_number(self):
        return "".join(character for character in (self.nin_number or "") if character.isdigit())

    @property
    def masked_nin_number(self):
        digits = self.normalized_nin_number
        if not digits:
            return ""
        tail = digits[-4:]
        return f"{'•' * max(len(digits) - 4, 0)}{tail}"

    @property
    def has_identity_submission(self):
        return bool(self.identity_document or self.normalized_nin_number)

    @property
    def identity_document_label(self):
        if self.identity_document_type:
            return self.get_identity_document_type_display()
        if self.normalized_nin_number:
            return "NIN"
        return ""

    @property
    def private_identity_summary(self):
        if self.identity_document_type == self.IdentityDocumentType.NIN and self.masked_nin_number:
            return f"NIN {self.masked_nin_number} is on file."
        if self.identity_document_label and self.identity_document:
            return f"{self.identity_document_label} is on file for private review."
        if self.masked_nin_number:
            return f"NIN {self.masked_nin_number} is on file."
        return "No identity document or NIN has been submitted yet."

    @property
    def trust_score(self):
        score = 0
        if self.phone_number and self.is_phone_verified:
            score += 20
        if self.email:
            score += 10
        if self.email and self.is_email_verified:
            score += 20
        if self.is_identity_verified or self.has_identity_submission:
            score += 20
        if self.social_handle:
            score += 10
        if self.account_type == self.AccountType.BUSINESS and self.business_name:
            score += 10
        if self.account_type == self.AccountType.BUSINESS and self.cac_certificate:
            score += 10
        return min(score, 100)

    @property
    def trust_level(self):
        score = self.trust_score
        if score >= 80:
            return "high"
        if score >= 60:
            return "trusted"
        if score >= 40:
            return "standard"
        return "new"

    @property
    def trust_level_label(self):
        return {
            "high": "High trust",
            "trusted": "Trusted seller",
            "standard": "Standard trust",
            "new": "New seller",
        }[self.trust_level]

    @property
    def trust_tone(self):
        return {
            "high": "success",
            "trusted": "info",
            "standard": "warning",
            "new": "neutral",
        }[self.trust_level]


class Listing(models.Model):
    class Category(models.TextChoices):
        PHONES = "phones", "Phones"
        LAPTOPS = "laptops", "Laptops"
        ACCESSORIES = "accessories", "Accessories"
        TABLETS = "tablets", "Tablets"
        AUDIO = "audio", "Audio"
        GAMING = "gaming", "Gaming"
        HOME_OFFICE = "home_office", "Home Office"
        OTHER = "other", "Other"

    class Condition(models.TextChoices):
        NEW = "new", "New"
        LIKE_NEW = "like_new", "Like New"
        USED_GOOD = "used_good", "Used - Good"
        USED_FAIR = "used_fair", "Used - Fair"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        LOCKED = "locked", "Locked"
        SOLD = "sold", "Sold"
        INACTIVE = "inactive", "Inactive"
        DRAFT = "draft", "Draft"

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="listings",
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.OTHER)
    condition = models.CharField(max_length=32, choices=Condition.choices, default=Condition.USED_GOOD)
    location = models.CharField(max_length=120, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    primary_image = models.FileField(upload_to=listing_primary_image_upload_to, blank=True)
    image_url = models.CharField(max_length=500, blank=True)
    gallery_image_urls = models.TextField(blank=True)
    defects = models.TextField(blank=True)
    is_negotiable = models.BooleanField(default=False)
    is_hot = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def image_gallery(self):
        urls = []
        if self.primary_image:
            urls.append(self.primary_image.url)
        elif self.image_url:
            urls.append(self.image_url.strip())
        if self.pk:
            for asset in self.media_assets.filter(asset_type=ListingMedia.AssetType.IMAGE).order_by("position", "pk"):
                asset_url = asset.file.url if asset.file else ""
                if asset_url and asset_url not in urls:
                    urls.append(asset_url)
        for value in self.gallery_image_urls.splitlines():
            normalized = value.strip()
            if normalized and normalized not in urls:
                urls.append(normalized)
        return urls

    @property
    def primary_image_url(self):
        gallery = self.image_gallery
        return gallery[0] if gallery else ""

    @property
    def video_gallery(self):
        if not self.pk:
            return []
        urls = []
        for asset in self.media_assets.filter(asset_type=ListingMedia.AssetType.VIDEO).order_by("position", "pk"):
            asset_url = asset.file.url if asset.file else ""
            if asset_url and asset_url not in urls:
                urls.append(asset_url)
        return urls

    @property
    def is_new_arrival(self):
        return self.created_at >= timezone.now() - timedelta(days=5)


class ListingMedia(models.Model):
    class AssetType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="media_assets")
    asset_type = models.CharField(max_length=16, choices=AssetType.choices)
    file = models.FileField(upload_to=listing_media_upload_to)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["position", "created_at", "pk"]

    def __str__(self):
        return f"{self.listing.title} {self.asset_type}"


class Offer(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting response"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="offers")
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="offers_made",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="offers_received",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    responded_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.listing.title} offer"


class Transaction(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        PAYMENT_IN_PROGRESS = "payment_in_progress", "Payment in progress"
        PAYMENT_CONFIRMED = "payment_confirmed", "Payment confirmed"
        LOCKED = "locked", "Locked"
        AWAITING_MEETUP = "awaiting_meetup", "Awaiting meetup"
        AWAITING_CONFIRMATION = "awaiting_confirmation", "Awaiting confirmation"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        DISPUTED = "disputed", "Disputed"

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="transactions")
    offer = models.ForeignKey(
        Offer,
        on_delete=models.SET_NULL,
        related_name="transactions",
        blank=True,
        null=True,
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="buy_transactions",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sell_transactions",
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING_PAYMENT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_reference = models.CharField(max_length=120, blank=True, null=True)
    is_released = models.BooleanField(default=False)
    expires_at = models.DateTimeField(blank=True, null=True)
    meetup_at = models.DateTimeField(blank=True, null=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment_reference"],
                condition=Q(payment_reference__isnull=False) & ~Q(payment_reference=""),
                name="accounts_transaction_unique_payment_reference",
            ),
        ]

    def __str__(self):
        return f"{self.listing.title} transaction"

    @property
    def is_closed(self):
        return self.status in {
            self.Status.COMPLETED,
            self.Status.CANCELLED,
            self.Status.DISPUTED,
        }

    def role_for(self, user):
        if user and self.buyer_id == user.id:
            return "buying"
        return "selling"

    def counterparty_for(self, user):
        if user and self.buyer_id == user.id:
            return self.seller
        return self.buyer

    @property
    def price(self):
        return self.amount

    @property
    def auto_release_at(self):
        auto_release_days = int(getattr(settings, "DECLUTRO_AUTO_RELEASE_DAYS", 0) or 0)
        if auto_release_days <= 0 or self.status != self.Status.AWAITING_CONFIRMATION:
            return None
        anchor = self.meetup_at or self.updated_at or self.created_at
        return anchor + timedelta(days=auto_release_days)
