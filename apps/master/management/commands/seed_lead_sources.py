from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.master.models import LeadSource


# Aligned with the JD Lead-to-Admission Process PDF (38 sources). Order
# matches the PDF table; existing entries are preserved by slug.
SOURCES = [
    "JDI Website",
    "JDSD Website",
    "JDI Course price reveal",
    "JDSD course price reveal",
    "JDI Brochure Download",
    "JDSD Brochure Download",
    "WhatsApp",
    "Chatbot",
    "Quiz",
    "Instagram",
    "AIDAT",
    "Direct Phone Call",
    "Direct walkin",
    "Student Reference",
    "Faculty / staff Reference",
    "Nealesh Sir Reference",
    "Consultants",
    "Workshop",
    "Ex Student",
    "Newspaper",
    "Career fair",
    "Leaflet Distribution",
    "Radio",
    "Bus campaign",
    "Auto campaign",
    "All course Landing page",
    "Landline",
    "Other centre Reference",
    "Summer camp",
    "Fashion New landing page leads - Bengaluru",
    "Interior New landing page leads - Bengaluru",
    "ADS - CAMPAIGN",
    "ADS - CAMPAIGN - JEWELLERY",
    "Interior New landing page leads - Goa",
    "Fashion New landing page leads - Goa",
    "VFX AND ANIMATION",
    "Graphic Design",
    "UI/UX",

    # Legacy (Module B v1) entries — kept for backwards compatibility
    # so existing leads don't lose their source FK.
    "Website",
    "Walk-in",
    "Phone Inquiry",
    "Referral",
    "Facebook",
    "Google Ads",
    "Seminar",
    "Existing Student",
    "Other",
]


class Command(BaseCommand):
    help = "Seed the LeadSource master list (38 PDF sources + legacy). Idempotent."

    def handle(self, *args, **opts):
        for i, name in enumerate(SOURCES):
            LeadSource.objects.update_or_create(
                slug=slugify(name),
                defaults={"name": name, "sort_order": (i + 1) * 10},
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(SOURCES)} lead sources."))
