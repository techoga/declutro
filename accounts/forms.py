from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Listing, ListingMedia
from .utils import normalize_email_address, normalize_phone_number, validate_identifier


User = get_user_model()

INPUT_CLASS = "form-input"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv")


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if not data:
            return []
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        return [single_file_clean(data, initial)]


class StyledFormMixin:
    def apply_styles(self):
        for name, field in self.fields.items():
            widget = field.widget
            css_class = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = f"{css_class} checkbox-input".strip()
                continue
            if getattr(widget, "input_type", "") == "file":
                widget.attrs["class"] = f"{css_class} {INPUT_CLASS} form-input-file".strip()
                widget.attrs.pop("placeholder", None)
                widget.attrs.pop("autocapitalize", None)
                continue
            widget.attrs["class"] = f"{css_class} {INPUT_CLASS}".strip()
            widget.attrs.setdefault("placeholder", field.label)
            widget.attrs.setdefault("autocapitalize", "none")
            if isinstance(widget, forms.PasswordInput):
                widget.attrs.setdefault("autocomplete", "current-password")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class LoginForm(StyledFormMixin, forms.Form):
    identifier = forms.CharField(
        label="Phone number or Email",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter phone number or email",
                "autocomplete": "username",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your password",
                "autocomplete": "current-password",
            }
        ),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean_identifier(self):
        value = self.cleaned_data["identifier"]
        kind, normalized = validate_identifier(value)
        self.cleaned_data["identifier_kind"] = kind
        return normalized

    def clean(self):
        cleaned_data = super().clean()
        identifier = cleaned_data.get("identifier")
        password = cleaned_data.get("password")
        if identifier and password:
            self.user = authenticate(self.request, username=identifier, password=password)
            if self.user is None:
                raise ValidationError("We couldn't sign you in with those credentials.")
        return cleaned_data

    def get_user(self):
        return self.user


class SignupForm(StyledFormMixin, forms.Form):
    phone_number = forms.CharField(
        label="Phone number",
        widget=forms.TextInput(
            attrs={
                "placeholder": "+2348012345678",
                "autocomplete": "tel",
            }
        ),
    )
    email = forms.EmailField(
        label="Email address",
        required=False,
        widget=forms.EmailInput(
            attrs={
                "placeholder": "you@example.com",
                "autocomplete": "email",
            }
        ),
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Create a password",
                "autocomplete": "new-password",
            }
        ),
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirm your password",
                "autocomplete": "new-password",
            }
        ),
    )

    def clean_phone_number(self):
        phone_number = normalize_phone_number(self.cleaned_data["phone_number"])
        if User.objects.filter(phone_number=phone_number).exists():
            raise ValidationError("An account with this phone number already exists.")
        return phone_number

    def clean_email(self):
        email = normalize_email_address(self.cleaned_data.get("email"))
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords do not match.")

        if password1:
            candidate = User(
                phone_number=cleaned_data.get("phone_number") or "+10000000000",
                email=cleaned_data.get("email"),
            )
            validate_password(password1, user=candidate)
        return cleaned_data

    def save(self):
        return User.objects.create_user(
            phone_number=self.cleaned_data["phone_number"],
            email=self.cleaned_data.get("email"),
            password=self.cleaned_data["password1"],
        )


class ForgotPasswordForm(StyledFormMixin, forms.Form):
    identifier = forms.CharField(
        label="Phone number or Email",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter phone number or email",
                "autocomplete": "username",
            }
        ),
    )

    def clean_identifier(self):
        kind, identifier = validate_identifier(self.cleaned_data["identifier"])
        self.cleaned_data["identifier_kind"] = kind
        return identifier


class ResetPasswordForm(StyledFormMixin, forms.Form):
    new_password1 = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Create a new password",
                "autocomplete": "new-password",
            }
        ),
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirm your new password",
                "autocomplete": "new-password",
            }
        ),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("new_password1")
        password2 = cleaned_data.get("new_password2")
        if password1 and password2 and password1 != password2:
            self.add_error("new_password2", "Passwords do not match.")
        if password1:
            validate_password(password1, user=self.user)
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data["new_password1"])
        self.user.save(update_fields=["password"])
        return self.user


class ProfileUpdateForm(StyledFormMixin, forms.ModelForm):
    current_password = forms.CharField(
        label="Current password",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter current password to confirm phone change",
                "autocomplete": "current-password",
            }
        ),
        help_text="Only required if you change your phone number.",
    )

    class Meta:
        model = User
        fields = ["name", "email", "phone_number"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Your name",
                    "autocomplete": "name",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "placeholder": "you@example.com",
                    "autocomplete": "email",
                }
            ),
            "phone_number": forms.TextInput(
                attrs={
                    "placeholder": "+2348012345678",
                    "autocomplete": "tel",
                }
            ),
        }

    def clean_phone_number(self):
        phone_number = normalize_phone_number(self.cleaned_data["phone_number"])
        qs = User.objects.exclude(pk=self.instance.pk).filter(phone_number=phone_number)
        if qs.exists():
            raise ValidationError("This phone number is already in use.")
        return phone_number

    def clean_email(self):
        email = normalize_email_address(self.cleaned_data.get("email"))
        if email:
            qs = User.objects.exclude(pk=self.instance.pk).filter(email__iexact=email)
            if qs.exists():
                raise ValidationError("This email address is already in use.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        new_phone_number = cleaned_data.get("phone_number")
        current_password = cleaned_data.get("current_password")
        if new_phone_number and new_phone_number != self.instance.phone_number:
            if not current_password:
                self.add_error("current_password", "Enter your current password to change your phone number.")
            elif not self.instance.check_password(current_password):
                self.add_error("current_password", "Current password is incorrect.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.email = self.cleaned_data.get("email")
        if commit:
            instance.save()
        return instance


class ListingForm(StyledFormMixin, forms.ModelForm):
    SELLER_EDITABLE_STATUSES = (
        Listing.Status.DRAFT,
        Listing.Status.ACTIVE,
        Listing.Status.INACTIVE,
    )
    primary_image_upload = forms.FileField(
        label="Cover image",
        required=False,
        help_text="Upload the main product photo shown across the marketplace.",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": "image/*",
            }
        ),
    )
    gallery_uploads = MultipleFileField(
        label="Gallery images",
        required=False,
        help_text="Optional. Add extra product photos for the detail gallery.",
        widget=MultipleFileInput(
            attrs={
                "accept": "image/*",
            }
        ),
    )
    video_uploads = MultipleFileField(
        label="Product videos",
        required=False,
        help_text="Optional. Upload short MP4, MOV, or WebM clips that show the item better.",
        widget=MultipleFileInput(
            attrs={
                "accept": "video/mp4,video/webm,video/quicktime,video/x-m4v,video/x-msvideo,video/x-matroska",
            }
        ),
    )

    class Meta:
        model = Listing
        fields = [
            "title",
            "category",
            "price",
            "condition",
            "location",
            "is_negotiable",
            "status",
            "description",
            "defects",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "placeholder": "Apple iPhone 11 128GB",
                    "autocomplete": "off",
                }
            ),
            "price": forms.NumberInput(
                attrs={
                    "placeholder": "250000",
                    "step": "0.01",
                    "min": "0",
                    "inputmode": "decimal",
                }
            ),
            "location": forms.TextInput(
                attrs={
                    "placeholder": "Lagos",
                    "autocomplete": "address-level2",
                }
            ),
            "is_negotiable": forms.CheckboxInput(),
            "status": forms.Select(),
            "description": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Condition, accessories, pickup notes, and what buyers should know.",
                }
            ),
            "defects": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Scratches on the frame, slight battery wear, or leave blank if none.",
                }
            ),
        }
        help_texts = {
            "is_negotiable": "Enable this if buyers can submit an offer on the public item page.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        status_field = self.fields["status"]
        self.fields["primary_image_upload"].widget.attrs["data-dashboard-primary-upload"] = "true"
        self.fields["gallery_uploads"].widget.attrs["data-dashboard-gallery-upload"] = "true"
        self.fields["video_uploads"].widget.attrs["data-dashboard-video-upload"] = "true"
        allowed_choices = [
            choice for choice in status_field.choices if choice[0] in self.SELLER_EDITABLE_STATUSES
        ]
        current_status = getattr(self.instance, "status", "")
        if current_status and current_status not in self.SELLER_EDITABLE_STATUSES:
            allowed_choices.append((current_status, self.instance.get_status_display()))
            status_field.help_text = (
                "Locked and sold states are controlled by the transaction engine and cannot be set manually."
            )
        status_field.choices = allowed_choices

    def clean_status(self):
        status = self.cleaned_data["status"]
        if status in {Listing.Status.LOCKED, Listing.Status.SOLD}:
            raise ValidationError("Locked and sold listings are controlled by the transaction flow.")
        return status

    def clean_primary_image_upload(self):
        uploaded_file = self.cleaned_data.get("primary_image_upload")
        if uploaded_file:
            self._validate_image_file(uploaded_file, "Cover image")
        return uploaded_file

    def clean_gallery_uploads(self):
        uploads = self.cleaned_data.get("gallery_uploads") or []
        for uploaded_file in uploads:
            self._validate_image_file(uploaded_file, "Gallery image")
        return uploads

    def clean_video_uploads(self):
        uploads = self.cleaned_data.get("video_uploads") or []
        for uploaded_file in uploads:
            self._validate_video_file(uploaded_file, "Product video")
        return uploads

    def save(self, commit=True):
        listing = super().save(commit=False)
        primary_image = self.cleaned_data.get("primary_image_upload")
        if primary_image:
            if listing.pk and listing.primary_image and listing.primary_image.name:
                listing.primary_image.delete(save=False)
            listing.primary_image = primary_image
            listing.image_url = ""

        if commit:
            listing.save()
            self.save_media(listing)
        return listing

    def save_media(self, listing=None):
        listing = listing or self.instance
        if not listing.pk:
            raise ValueError("Listing must be saved before media assets can be attached.")

        clear_legacy_image = bool(listing.primary_image)
        clear_legacy_gallery = bool(
            (self.cleaned_data.get("gallery_uploads") or []) or (self.cleaned_data.get("video_uploads") or [])
        )

        next_position = (
            listing.media_assets.order_by("-position").values_list("position", flat=True).first() or 0
        ) + 1

        for uploaded_file in self.cleaned_data.get("gallery_uploads") or []:
            ListingMedia.objects.create(
                listing=listing,
                asset_type=ListingMedia.AssetType.IMAGE,
                file=uploaded_file,
                position=next_position,
            )
            next_position += 1

        for uploaded_file in self.cleaned_data.get("video_uploads") or []:
            ListingMedia.objects.create(
                listing=listing,
                asset_type=ListingMedia.AssetType.VIDEO,
                file=uploaded_file,
                position=next_position,
            )
            next_position += 1

        update_fields = []
        if clear_legacy_image and listing.image_url:
            listing.image_url = ""
            update_fields.append("image_url")
        if clear_legacy_gallery and listing.gallery_image_urls:
            listing.gallery_image_urls = ""
            update_fields.append("gallery_image_urls")
        if update_fields:
            update_fields.append("updated_at")
            listing.save(update_fields=update_fields)

    def _validate_image_file(self, uploaded_file, label):
        self._validate_uploaded_file(
            uploaded_file,
            label,
            allowed_prefix="image/",
            allowed_extensions=IMAGE_EXTENSIONS,
            max_size=12 * 1024 * 1024,
            size_message="must be 12MB or smaller.",
        )

    def _validate_video_file(self, uploaded_file, label):
        self._validate_uploaded_file(
            uploaded_file,
            label,
            allowed_prefix="video/",
            allowed_extensions=VIDEO_EXTENSIONS,
            max_size=120 * 1024 * 1024,
            size_message="must be 120MB or smaller.",
        )

    def _validate_uploaded_file(
        self,
        uploaded_file,
        label,
        *,
        allowed_prefix,
        allowed_extensions,
        max_size,
        size_message,
    ):
        file_name = (uploaded_file.name or "").lower()
        content_type = getattr(uploaded_file, "content_type", "") or ""
        if not content_type.startswith(allowed_prefix) and not file_name.endswith(allowed_extensions):
            raise ValidationError(f"{label} must be a supported {allowed_prefix.rstrip('/')} file.")
        if uploaded_file.size > max_size:
            raise ValidationError(f"{label} {size_message}")


class OfferSubmissionForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(
        label="Your offer",
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={
                "placeholder": "Enter your offer",
                "step": "0.01",
                "min": "0",
                "inputmode": "decimal",
            }
        ),
    )

    def __init__(self, listing, *args, **kwargs):
        self.listing = listing
        super().__init__(*args, **kwargs)

    def clean_amount(self):
        value = self.cleaned_data["amount"]
        if value <= 0:
            raise ValidationError("Offer amount must be greater than zero.")
        return value


class PasswordUpdateForm(StyledFormMixin, forms.Form):
    current_password = forms.CharField(
        label="Current password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your current password",
                "autocomplete": "current-password",
            }
        ),
    )
    new_password1 = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Create a new password",
                "autocomplete": "new-password",
            }
        ),
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Confirm your new password",
                "autocomplete": "new-password",
            }
        ),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        value = self.cleaned_data["current_password"]
        if not self.user.check_password(value):
            raise ValidationError("Current password is incorrect.")
        return value

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("new_password1")
        password2 = cleaned_data.get("new_password2")
        if password1 and password2 and password1 != password2:
            self.add_error("new_password2", "Passwords do not match.")
        if password1:
            validate_password(password1, user=self.user)
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data["new_password1"])
        self.user.save(update_fields=["password"])
        return self.user


class AdminUserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("phone_number", "email", "name")

    def clean_phone_number(self):
        return normalize_phone_number(self.cleaned_data["phone_number"])

    def clean_email(self):
        return normalize_email_address(self.cleaned_data.get("email"))

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("password1") != cleaned_data.get("password2"):
            self.add_error("password2", "Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class AdminUserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField()

    class Meta:
        model = User
        fields = ("phone_number", "email", "name", "password", "is_active", "is_staff", "is_superuser")

    def clean_email(self):
        return normalize_email_address(self.cleaned_data.get("email"))

    def clean_phone_number(self):
        return normalize_phone_number(self.cleaned_data["phone_number"])

    def clean_password(self):
        return self.initial["password"]
