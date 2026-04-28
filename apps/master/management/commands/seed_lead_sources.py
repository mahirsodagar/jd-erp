from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.master.models import LeadSource


SOURCES = [
    "Website",
    "Walk-in",
    "Phone Inquiry",
    "WhatsApp",
    "Referral",
    "Instagram",
    "Facebook",
    "Google Ads",
    "Seminar",
    "Existing Student",
    "Other",
]


class Command(BaseCommand):
    help = "Seed the LeadSource master list. Idempotent."

    def handle(self, *args, **opts):
        for i, name in enumerate(SOURCES):
            LeadSource.objects.update_or_create(
                slug=slugify(name),
                defaults={"name": name, "sort_order": (i + 1) * 10},
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(SOURCES)} lead sources."))
