import re

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator


PHONE_NUMBER_RE = re.compile(r"^\+[1-9]\d{7,14}$")
validate_email_address = EmailValidator(message="Enter a valid email address.")


def normalize_email_address(value):
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def normalize_phone_number(value):
    if value is None:
        raise ValidationError("Phone number is required.")
    normalized = re.sub(r"\s+", "", str(value).strip())
    if not PHONE_NUMBER_RE.fullmatch(normalized):
        raise ValidationError("Enter a valid phone number in E.164 format, for example +2348012345678.")
    return normalized


def detect_identifier_kind(value):
    return "email" if "@" in value else "phone"


def validate_identifier(value):
    identifier = str(value).strip()
    kind = detect_identifier_kind(identifier)
    if kind == "email":
        validate_email_address(identifier)
        return kind, normalize_email_address(identifier)
    return kind, normalize_phone_number(identifier)


def mask_identifier(value, kind):
    text = str(value).strip()
    if kind == "email":
        local, _, domain = text.partition("@")
        if len(local) <= 2:
            masked_local = local[:1] + "*"
        else:
            masked_local = local[:2] + "*" * max(len(local) - 2, 1)
        return f"{masked_local}@{domain}"

    digits = text[-4:]
    prefix = text[:3]
    return f"{prefix}{'*' * max(len(text) - len(prefix) - len(digits), 4)}{digits}"
