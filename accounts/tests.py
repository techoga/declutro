import json
import hmac
import hashlib
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .forms import ProfileUpdateForm
from .models import Listing, Offer, Transaction
from .services import SESEmailService, TermiiSMSService


User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class UserModelAndAuthTests(TestCase):
    def test_create_user_normalizes_fields(self):
        user = User.objects.create_user(
            phone_number="+2348012345678",
            email="Test@Example.com",
            password="StrongPass123!",
        )

        self.assertEqual(user.phone_number, "+2348012345678")
        self.assertEqual(user.email, "test@example.com")
        self.assertTrue(user.check_password("StrongPass123!"))

    def test_authenticate_with_phone_or_email(self):
        user = User.objects.create_user(
            phone_number="+2348012345678",
            email="founder@declutro.com",
            password="StrongPass123!",
        )

        self.assertEqual(
            authenticate(username="+2348012345678", password="StrongPass123!"),
            user,
        )
        self.assertEqual(
            authenticate(username="Founder@Declutro.com", password="StrongPass123!"),
            user,
        )

    def test_profile_form_requires_current_password_when_phone_changes(self):
        user = User.objects.create_user(
            phone_number="+2348012345678",
            email="hello@example.com",
            password="StrongPass123!",
        )
        form = ProfileUpdateForm(
            data={
                "name": "",
                "email": "hello@example.com",
                "phone_number": "+2348099999999",
                "current_password": "",
            },
            instance=user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("current_password", form.errors)


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class AuthFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            phone_number="+2348012345678",
            email="member@declutro.com",
            password="StrongPass123!",
            name="Declutro Member",
        )

    def test_signup_logs_user_in(self):
        response = self.client.post(
            reverse("auth_signup"),
            data={
                "phone_number": "+2348098765432",
                "email": "new@declutro.com",
                "password1": "AnotherPass123!",
                "password2": "AnotherPass123!",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("dashboard_home"))
        self.assertTrue(User.objects.filter(phone_number="+2348098765432").exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), User.objects.get(phone_number="+2348098765432").pk)

    def test_login_accepts_email(self):
        response = self.client.post(
            reverse("auth_login"),
            data={"identifier": "member@declutro.com", "password": "StrongPass123!"},
            follow=True,
        )

        self.assertRedirects(response, reverse("dashboard_home"))

    @patch("accounts.views.send_password_reset_notification")
    def test_forgot_password_redirects_to_notice_and_sends_reset(self, send_notification):
        response = self.client.post(
            reverse("auth_forgot_password"),
            data={"identifier": "member@declutro.com"},
        )

        self.assertRedirects(response, reverse("auth_reset_password_notice"))
        send_notification.assert_called_once()
        notice = self.client.session["password_reset_notice"]
        self.assertEqual(notice["channel"], "email")

    @patch("accounts.views.send_password_reset_notification")
    def test_forgot_password_returns_neutral_success_for_unknown_identifier(self, send_notification):
        response = self.client.post(
            reverse("auth_forgot_password"),
            data={"identifier": "+2348111111111"},
        )

        self.assertRedirects(response, reverse("auth_reset_password_notice"))
        send_notification.assert_not_called()

    def test_valid_reset_token_updates_password(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        response = self.client.post(
            reverse("auth_reset_password_confirm", kwargs={"uidb64": uidb64, "token": token}),
            data={
                "new_password1": "ResetPass123!",
                "new_password2": "ResetPass123!",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("auth_login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("ResetPass123!"))

    def test_invalid_reset_token_shows_invalid_state(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.get(
            reverse("auth_reset_password_confirm", kwargs={"uidb64": uidb64, "token": "invalid-token"})
        )

        self.assertContains(response, "Reset link expired", status_code=200)

    def test_dashboard_requires_authentication(self):
        response = self.client.get(reverse("dashboard_home"))
        self.assertRedirects(response, f"{reverse('auth_login')}?next={reverse('dashboard_home')}")

    def test_profile_update_and_password_change_keep_session_valid(self):
        self.client.force_login(self.user)

        profile_response = self.client.post(
            reverse("dashboard_profile"),
            data={
                "name": "Updated Name",
                "email": "updated@declutro.com",
                "phone_number": "+2348090000000",
                "current_password": "StrongPass123!",
            },
            follow=True,
        )
        self.assertRedirects(profile_response, reverse("dashboard_profile"))

        password_response = self.client.post(
            reverse("dashboard_update_password"),
            data={
                "current_password": "StrongPass123!",
                "new_password1": "UpdatedPass123!",
                "new_password2": "UpdatedPass123!",
            },
            follow=True,
        )

        self.assertRedirects(password_response, reverse("dashboard_update_password"))
        dashboard_response = self.client.get(reverse("dashboard_home"))
        self.assertEqual(dashboard_response.status_code, 200)

    def test_logout_requires_post_and_clears_session(self):
        self.client.force_login(self.user)
        get_response = self.client.get(reverse("auth_logout"))
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post(reverse("auth_logout"), follow=True)
        self.assertRedirects(post_response, reverse("auth_login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_key_templates_render_expected_content(self):
        self.assertContains(self.client.get(reverse("auth_login")), "Welcome back")
        self.assertContains(self.client.get(reverse("auth_signup")), "Create your account")
        self.assertContains(self.client.get(reverse("auth_forgot_password")), "Reset access")

        self.client.force_login(self.user)
        dashboard_response = self.client.get(reverse("dashboard_home"))
        self.assertContains(dashboard_response, "Action required")
        self.assertContains(dashboard_response, "Open transactions")
        self.assertContains(dashboard_response, "My listings")
        self.assertContains(dashboard_response, "Compliance and trust")
        self.assertContains(self.client.get(reverse("dashboard_profile")), "Profile settings")
        self.assertContains(self.client.get(reverse("dashboard_update_password")), "Update password")

    def test_sell_item_creates_listing(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dashboard_sell_item"),
            data={
                "title": "MacBook Air M2",
                "category": Listing.Category.LAPTOPS,
                "price": "950000",
                "condition": Listing.Condition.LIKE_NEW,
                "location": "Lagos",
                "image_url": "https://example.com/macbook-air.jpg",
                "gallery_image_urls": "",
                "is_negotiable": "on",
                "status": Listing.Status.ACTIVE,
                "description": "Clean condition with charger.",
                "defects": "",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("dashboard_listings"))
        self.assertTrue(Listing.objects.filter(seller=self.user, title="MacBook Air M2").exists())
        self.assertContains(response, "MacBook Air M2")


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    PAYSTACK_SECRET_KEY="sk_test_declutro",
)
class PublicMarketplaceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.seller = User.objects.create_user(
            phone_number="+2348011111111",
            email="seller@declutro.com",
            password="StrongPass123!",
            name="Verified Seller",
            is_email_verified=True,
            is_identity_verified=True,
        )
        self.buyer = User.objects.create_user(
            phone_number="+2348022222222",
            email="buyer@declutro.com",
            password="StrongPass123!",
            name="Ready Buyer",
        )

        now = timezone.now()
        self.phone_listing = Listing.objects.create(
            seller=self.seller,
            title="iPhone 13 128GB",
            category=Listing.Category.PHONES,
            condition=Listing.Condition.LIKE_NEW,
            location="Lagos",
            price="540000.00",
            is_negotiable=False,
            status=Listing.Status.ACTIVE,
            description="Face ID works perfectly and battery health is still strong.",
            created_at=now - timedelta(days=2),
        )
        self.laptop_listing = Listing.objects.create(
            seller=self.seller,
            title="MacBook Air M2",
            category=Listing.Category.LAPTOPS,
            condition=Listing.Condition.USED_GOOD,
            location="Abuja",
            price="850000.00",
            is_negotiable=True,
            is_hot=True,
            status=Listing.Status.ACTIVE,
            description="16GB RAM with a clean body and original charger.",
            defects="Minor wear on one corner.",
            created_at=now - timedelta(hours=3),
        )
        self.accessory_listing = Listing.objects.create(
            seller=self.seller,
            title="AirPods Pro Case",
            category=Listing.Category.ACCESSORIES,
            condition=Listing.Condition.NEW,
            location="Lagos",
            price="85000.00",
            is_negotiable=True,
            status=Listing.Status.ACTIVE,
            description="Unused replacement case.",
            created_at=now - timedelta(days=1),
        )

    def test_home_filters_listings_by_category_location_and_negotiable(self):
        response = self.client.get(
            reverse("home"),
            {
                "category": Listing.Category.ACCESSORIES,
                "location": "Lagos",
                "negotiable": "1",
                "sort": "price_desc",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AirPods Pro Case")
        self.assertNotContains(response, "iPhone 13 128GB")
        self.assertEqual(len(response.context["listings"]), 1)
        self.assertEqual(response.context["listings"][0]["title"], "AirPods Pro Case")

    def test_home_sorts_by_price_low_to_high(self):
        response = self.client.get(reverse("home"), {"sort": "price_asc"})

        self.assertEqual(response.status_code, 200)
        listing_titles = [item["title"] for item in response.context["listings"]]
        self.assertEqual(
            listing_titles,
            ["AirPods Pro Case", "iPhone 13 128GB", "MacBook Air M2"],
        )

    def test_listing_detail_shows_action_first_content(self):
        response = self.client.get(reverse("listing_detail", kwargs={"listing_id": self.laptop_listing.pk}))

        self.assertContains(response, "Buy Now")
        self.assertContains(response, "Make Offer")
        self.assertContains(response, "Pay now to reserve this item. Inspect before the seller gets paid.")
        self.assertContains(response, "Verified")

    def test_buy_now_requires_authentication(self):
        response = self.client.post(reverse("buy_now", kwargs={"listing_id": self.phone_listing.pk}))

        self.assertRedirects(
            response,
            f"{reverse('auth_login')}?next={reverse('buy_now', kwargs={'listing_id': self.phone_listing.pk})}",
            fetch_redirect_response=False,
        )

    @patch("accounts.transaction_engine.initialize_paystack_payment")
    def test_buy_now_creates_pending_payment_transaction_and_redirects_to_paystack(self, initialize_paystack):
        initialize_paystack.return_value = {
            "authorization_url": "https://paystack.example/authorize",
            "reference": "ref-123",
        }
        self.client.force_login(self.buyer)

        response = self.client.post(reverse("buy_now", kwargs={"listing_id": self.phone_listing.pk}))

        transaction = Transaction.objects.get(listing=self.phone_listing, buyer=self.buyer)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://paystack.example/authorize")
        self.assertEqual(transaction.status, Transaction.Status.PAYMENT_IN_PROGRESS)
        self.assertEqual(transaction.amount, Decimal("540000.00"))
        self.assertTrue(transaction.payment_reference)

    def test_make_offer_creates_pending_offer_without_transaction(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("create_offer", kwargs={"listing_id": self.laptop_listing.pk}),
            data={"amount": "790000"},
        )

        offer = Offer.objects.get(listing=self.laptop_listing, buyer=self.buyer)
        self.assertRedirects(response, reverse("listing_detail", kwargs={"listing_id": self.laptop_listing.pk}))
        self.assertEqual(offer.amount, Decimal("790000.00"))
        self.assertEqual(offer.status, Offer.Status.PENDING)
        self.assertFalse(Transaction.objects.filter(offer=offer).exists())

    def test_accept_offer_creates_buyer_payment_window(self):
        offer = Offer.objects.create(
            listing=self.laptop_listing,
            buyer=self.buyer,
            seller=self.seller,
            amount=Decimal("790000.00"),
            status=Offer.Status.PENDING,
            expires_at=timezone.now() + timedelta(hours=12),
        )

        self.client.force_login(self.seller)
        response = self.client.post(reverse("accept_offer", kwargs={"offer_id": offer.pk}), follow=True)

        offer.refresh_from_db()
        transaction = Transaction.objects.get(offer=offer)
        self.assertRedirects(response, reverse("dashboard_listings"))
        self.assertEqual(offer.status, Offer.Status.ACCEPTED)
        self.assertEqual(transaction.status, Transaction.Status.PENDING_PAYMENT)
        self.assertEqual(transaction.amount, Decimal("790000.00"))

    @patch("accounts.transaction_engine.verify_paystack_payment")
    def test_paystack_webhook_locks_listing_for_first_verified_payment(self, verify_payment):
        winner = Transaction.objects.create(
            listing=self.phone_listing,
            buyer=self.buyer,
            seller=self.seller,
            amount=Decimal("540000.00"),
            status=Transaction.Status.PAYMENT_IN_PROGRESS,
            payment_reference="declutro-win-123",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        losing_buyer = User.objects.create_user(
            phone_number="+2348033333333",
            email="latebuyer@declutro.com",
            password="StrongPass123!",
            name="Late Buyer",
        )
        loser = Transaction.objects.create(
            listing=self.phone_listing,
            buyer=losing_buyer,
            seller=self.seller,
            amount=Decimal("540000.00"),
            status=Transaction.Status.PAYMENT_IN_PROGRESS,
            payment_reference="declutro-lose-456",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        verify_payment.return_value = {
            "amount": 54000000,
            "metadata": {
                "transaction_id": winner.pk,
            },
        }
        payload = {
            "event": "charge.success",
            "data": {
                "reference": "declutro-win-123",
            },
        }
        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(
            b"sk_test_declutro",
            body,
            hashlib.sha512,
        ).hexdigest()

        response = self.client.post(
            reverse("paystack_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.phone_listing.refresh_from_db()
        winner.refresh_from_db()
        loser.refresh_from_db()
        self.assertEqual(self.phone_listing.status, Listing.Status.LOCKED)
        self.assertEqual(winner.status, Transaction.Status.AWAITING_MEETUP)
        self.assertEqual(loser.status, Transaction.Status.CANCELLED)

    def test_confirm_transaction_marks_listing_sold_and_released(self):
        transaction = Transaction.objects.create(
            listing=self.phone_listing,
            buyer=self.buyer,
            seller=self.seller,
            amount=Decimal("540000.00"),
            status=Transaction.Status.AWAITING_MEETUP,
        )
        self.phone_listing.status = Listing.Status.LOCKED
        self.phone_listing.save(update_fields=["status", "updated_at"])

        self.client.force_login(self.buyer)
        response = self.client.post(reverse("confirm_transaction", kwargs={"transaction_id": transaction.pk}), follow=True)

        transaction.refresh_from_db()
        self.phone_listing.refresh_from_db()
        self.assertRedirects(response, reverse("dashboard_transactions"))
        self.assertEqual(transaction.status, Transaction.Status.COMPLETED)
        self.assertTrue(transaction.is_released)
        self.assertEqual(self.phone_listing.status, Listing.Status.SOLD)


class NotificationServiceTests(TestCase):
    def test_ses_payload_contains_expected_fields(self):
        service = SESEmailService(
            access_key="key",
            secret_key="secret",
            region="us-east-1",
            from_email="noreply@declutro.com",
        )
        params = service.build_send_email_params(
            "user@example.com",
            "Reset your Declutro password",
            "Reset link",
        )

        self.assertEqual(params["Destination.ToAddresses.member.1"], "user@example.com")
        self.assertEqual(params["Source"], "noreply@declutro.com")
        self.assertEqual(params["Message.Subject.Data"], "Reset your Declutro password")

    def test_termii_payload_contains_expected_fields(self):
        service = TermiiSMSService(
            api_key="termii-key",
            sender_id="Declutro",
            base_url="https://api.ng.termii.com/api",
        )
        payload = json.loads(service.build_sms_payload("+2348012345678", "https://example.com/reset").decode("utf-8"))

        self.assertEqual(payload["api_key"], "termii-key")
        self.assertEqual(payload["to"], "+2348012345678")
        self.assertEqual(payload["from"], "Declutro")
        self.assertIn("https://example.com/reset", payload["sms"])
