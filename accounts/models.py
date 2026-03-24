from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .utils import normalize_email_address, normalize_phone_number


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
    phone_number = models.CharField(max_length=16, unique=True, db_index=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    name = models.CharField(max_length=150, blank=True)
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
        if self.image_url:
            urls.append(self.image_url.strip())
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
    def is_new_arrival(self):
        return self.created_at >= timezone.now() - timedelta(days=5)


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
