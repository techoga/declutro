import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib import error, parse, request

from django.conf import settings


class NotificationError(Exception):
    pass


class SESEmailService:
    service = "ses"

    def __init__(
        self,
        access_key=None,
        secret_key=None,
        region=None,
        from_email=None,
        session_token=None,
    ):
        self.access_key = access_key or settings.AWS_ACCESS_KEY_ID
        self.secret_key = secret_key or settings.AWS_SECRET_ACCESS_KEY
        self.session_token = session_token or settings.AWS_SESSION_TOKEN
        self.region = region or settings.AWS_REGION
        self.from_email = from_email or settings.AWS_SES_FROM_EMAIL

    def send_password_reset(self, to_email, reset_url):
        self._assert_configured()
        subject = "Reset your Declutro password"
        body_text = (
            "A password reset was requested for your Declutro account.\n\n"
            f"Use this secure link to set a new password:\n{reset_url}\n\n"
            "If you did not request this, you can ignore this message."
        )
        payload = parse.urlencode(self.build_send_email_params(to_email, subject, body_text)).encode("utf-8")
        self._signed_post(
            host=f"email.{self.region}.amazonaws.com",
            path="/",
            payload=payload,
            content_type="application/x-www-form-urlencoded; charset=utf-8",
        )

    def build_send_email_params(self, to_email, subject, body_text):
        return {
            "Action": "SendEmail",
            "Version": "2010-12-01",
            "Source": self.from_email,
            "Destination.ToAddresses.member.1": to_email,
            "Message.Subject.Data": subject,
            "Message.Body.Text.Data": body_text,
        }

    def _assert_configured(self):
        if not all([self.access_key, self.secret_key, self.region, self.from_email]):
            raise NotificationError("AWS SES is not fully configured.")

    def _signed_post(self, host, path, payload, content_type):
        method = "POST"
        canonical_querystring = ""
        endpoint = f"https://{host}{path}"
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(payload).hexdigest()

        headers = {
            "content-type": content_type,
            "host": host,
            "x-amz-date": amz_date,
        }
        if self.session_token:
            headers["x-amz-security-token"] = self.session_token

        signed_headers = ";".join(sorted(headers.keys()))
        canonical_headers = "".join(f"{key}:{headers[key]}\n" for key in sorted(headers.keys()))
        canonical_request = "\n".join(
            [
                method,
                path,
                canonical_querystring,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self.region}/{self.service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = self._get_signature_key(date_stamp)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        auth_header = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        request_headers = {
            "Content-Type": content_type,
            "Host": host,
            "X-Amz-Date": amz_date,
            "Authorization": auth_header,
        }
        if self.session_token:
            request_headers["X-Amz-Security-Token"] = self.session_token

        self._open_request(endpoint, payload, request_headers)

    def _get_signature_key(self, date_stamp):
        k_date = hmac.new(("AWS4" + self.secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
        k_region = hmac.new(k_date, self.region.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_region, self.service.encode("utf-8"), hashlib.sha256).digest()
        return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()

    def _open_request(self, endpoint, payload, headers):
        req = request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=10) as response:
                response.read()
        except error.HTTPError as exc:
            raise NotificationError(f"SES request failed with status {exc.code}.") from exc
        except error.URLError as exc:
            raise NotificationError("SES request failed.") from exc


class TermiiSMSService:
    def __init__(self, api_key=None, sender_id=None, base_url=None):
        self.api_key = api_key or settings.TERMII_API_KEY
        self.sender_id = sender_id or settings.TERMII_SENDER_ID
        self.base_url = (base_url or settings.TERMII_BASE_URL).rstrip("/")

    def send_password_reset(self, phone_number, reset_url):
        self._assert_configured()
        payload = self.build_sms_payload(phone_number, reset_url)
        headers = {"Content-Type": "application/json"}
        endpoint = f"{self.base_url}/sms/send"
        req = request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=10) as response:
                response.read()
        except error.HTTPError as exc:
            raise NotificationError(f"Termii request failed with status {exc.code}.") from exc
        except error.URLError as exc:
            raise NotificationError("Termii request failed.") from exc

    def build_sms_payload(self, phone_number, reset_url):
        payload = {
            "api_key": self.api_key,
            "to": phone_number,
            "from": self.sender_id,
            "sms": (
                "Declutro password reset requested. "
                f"Use this secure link to continue: {reset_url}"
            ),
            "type": "plain",
            "channel": "generic",
        }
        return json.dumps(payload).encode("utf-8")

    def _assert_configured(self):
        if not all([self.api_key, self.sender_id, self.base_url]):
            raise NotificationError("Termii SMS is not fully configured.")


def send_password_reset_notification(*, user, channel, reset_url):
    if channel == "email":
        SESEmailService().send_password_reset(user.email, reset_url)
        return
    if channel == "phone":
        TermiiSMSService().send_password_reset(user.phone_number, reset_url)
        return
    raise NotificationError(f"Unsupported password reset channel: {channel}")
