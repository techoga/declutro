from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Listing


class Command(BaseCommand):
    help = "Seed Declutro with premium public demo listings."

    def handle(self, *args, **options):
        User = get_user_model()

        seller, _ = User.objects.get_or_create(
            phone_number="+2348030000001",
            defaults={
                "email": "seller.one@declutro.demo",
                "name": "Amina Devices",
                "is_email_verified": True,
                "is_identity_verified": True,
            },
        )
        seller.set_password("DeclutroDemo123!")
        seller.save(update_fields=["password"])

        second_seller, _ = User.objects.get_or_create(
            phone_number="+2348030000002",
            defaults={
                "email": "seller.two@declutro.demo",
                "name": "Lekan Tech",
                "is_email_verified": True,
            },
        )
        second_seller.set_password("DeclutroDemo123!")
        second_seller.save(update_fields=["password"])

        listings = [
            {
                "seller": seller,
                "title": "iPhone 14 Pro 256GB",
                "category": Listing.Category.PHONES,
                "condition": Listing.Condition.LIKE_NEW,
                "location": "Lagos",
                "price": "1125000.00",
                "description": "Factory-unlocked, boxed, and available for same-day inspection.",
                "defects": "",
                "is_negotiable": False,
                "is_hot": True,
            },
            {
                "seller": second_seller,
                "title": "MacBook Pro 14 M2 Pro",
                "category": Listing.Category.LAPTOPS,
                "condition": Listing.Condition.USED_GOOD,
                "location": "Abuja",
                "price": "1980000.00",
                "description": "16GB RAM, 512GB SSD, charger included, clean keyboard and display.",
                "defects": "Light wear on the outer shell.",
                "is_negotiable": True,
                "is_hot": True,
            },
            {
                "seller": seller,
                "title": "Sony WH-1000XM5",
                "category": Listing.Category.AUDIO,
                "condition": Listing.Condition.USED_GOOD,
                "location": "Port Harcourt",
                "price": "280000.00",
                "description": "Noise cancellation is excellent and the case is included.",
                "defects": "",
                "is_negotiable": True,
                "is_hot": False,
            },
            {
                "seller": second_seller,
                "title": "iPad Air 5",
                "category": Listing.Category.TABLETS,
                "condition": Listing.Condition.NEW,
                "location": "Lagos",
                "price": "720000.00",
                "description": "Sealed unit with charging cable and receipt.",
                "defects": "",
                "is_negotiable": False,
                "is_hot": False,
            },
        ]

        for payload in listings:
            Listing.objects.update_or_create(
                seller=payload["seller"],
                title=payload["title"],
                defaults={
                    **payload,
                    "status": Listing.Status.ACTIVE,
                    "image_url": "",
                    "gallery_image_urls": "",
                },
            )

        self.stdout.write(self.style.SUCCESS("Declutro demo listings seeded successfully."))
