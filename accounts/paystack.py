import hashlib
import hmac
import json
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from django.conf import settings


class PaystackError(Exception):
    """Raised when Paystack rejects a request or returns an unusable payload."""


def _get_paystack_secret_key():
    secret_key = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
    if not secret_key:
        raise PaystackError("Paystack is not configured.")
    return secret_key


def _paystack_request(path, *, payload=None, method="GET"):
    secret_key = _get_paystack_secret_key()
    url = urljoin(f"{settings.PAYSTACK_BASE_URL.rstrip('/')}/", path.lstrip("/"))
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PaystackError(detail or "Paystack request failed.") from exc
    except URLError as exc:
        raise PaystackError("Unable to reach Paystack.") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PaystackError("Paystack returned invalid JSON.") from exc

    if not payload.get("status"):
        raise PaystackError(payload.get("message") or "Paystack request failed.")
    return payload.get("data") or {}


def amount_to_kobo(amount):
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def initialize_paystack_payment(*, amount, email, reference, callback_url, metadata):
    payload = {
        "amount": amount_to_kobo(amount),
        "email": email,
        "reference": reference,
        "callback_url": callback_url,
        "metadata": metadata,
        "currency": getattr(settings, "PAYSTACK_CURRENCY", "NGN"),
    }
    channels = list(getattr(settings, "PAYSTACK_CHANNELS", []) or [])
    if channels:
        payload["channels"] = channels

    return _paystack_request(
        "/transaction/initialize",
        method="POST",
        payload=payload,
    )


def verify_paystack_payment(reference):
    return _paystack_request(f"/transaction/verify/{quote(reference)}")


def verify_webhook_signature(payload, signature):
    secret_key = _get_paystack_secret_key()
    if not signature:
        return False
    expected_signature = hmac.new(
        secret_key.encode("utf-8"),
        payload,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)
