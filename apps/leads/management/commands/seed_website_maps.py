"""Seed WebsiteValueMap from what the website actually sends.

Values come from ~2,000 real payloads in the legacy webhooks/log.txt
(Jul–Dec 2025). Idempotent: rows are matched by (kind, normalised value)
and re-pointed; rows added by hand in admin are left alone.

Program targets are looked up by name; a missing program is reported
and skipped, never invented.
"""

from django.core.management.base import BaseCommand

from apps.leads.models import WebsiteValueMap
from apps.leads.website_webhook import WILDCARD, normalise
from apps.master.models import Campus, LeadSource, Program

# website select_1 → Campus.code
CAMPUSES = {
    "Bangalore": "BLR",
    "Bengaluru": "BLR",
    "Goa": "GOA",
    "Cochin": "COK",
    "Kochi": "COK",
    "Hyderabad": "HYD",
    "Vijayawada": "BZA",
    WILDCARD: "BLR",
}

# Forminator form_title → LeadSource.slug (seed_lead_sources names)
SOURCES = {
    "Download Brochure - Popup": "jdi-brochure-download",
    "Brochure Download - QR code": "jdi-brochure-download",
    "Course Pricing Reveal": "jdi-course-price-reveal",
    "Apply Online": "jdi-website",
    "Course pages - Form": "jdi-website",
    "ADMISSIONS OPEN - ALL COURSE PAGES": "jdi-website",
    "Contact us": "jdi-website",
    "Admissions - Bengaluru": "jdi-website",
    "Admissions - Cochin": "jdi-website",
    "Walkin - QR code": "direct-walkin",
    WILDCARD: "jdi-website",
}

# Website course *categories* → the entry-level Program for that stream.
# Full course names ("B.des in Fashion Design - 4 Years") need no row:
# the webhook matches them to Program.name after dropping the duration.
PROGRAMS = {
    "Fashion Designing Courses": "Diploma in Fashion Design",
    "Fashion Design Course": "Diploma in Fashion Design",
    "Fashion Design Courses": "Diploma in Fashion Design",
    "Interior Designing Courses": "Diploma in Interior Design",
    "Interior Design Course": "Diploma in Interior Design",
    "Interior Design Courses": "Diploma in Interior Design",
    "Jewellery Designing Courses": "Diploma in Fine Jewellery Design",
    "Jewellery Design Course": "Diploma in Fine Jewellery Design",
    "Graphic Designing Courses": "Diploma in Graphic Design",
    "Graphic Design Course": "Diploma in Graphic Design",
    "UI/UX Design Courses": "MA in UI/UX",
    "Photography Courses": "Certificate Program in Fashion Photography",
    "Event Management Courses": "PG Diploma in Fashion Business and Event Management",
    "Animation Courses": "Diploma in Animation & Multimedia",
    "VFX Courses": "Diploma in VFX and Compositing",
    "Visual Communication Course": "B.des in Visual Communication",
    "Social Media Marketing Courses": "Certificate Program in Social Media and influencer marketing",
    "Influencer Marketing Courses": "Certificate Program in Social Media and influencer marketing",
    "Certificate Program in Film making and Editing": "Certificate Program in Filmmaking and Editing",
    "PG Diploma in Fashion Design & Management": "PG Diploma in Fashion design and Management",
    "Architecture Designing Courses": "Diploma in Architectural Design & Visualization",
    # Spellings seen on campus-specific dropdowns
    "B'Des Fashion Design": "B.des in Fashion Design",
    "B.Des. in Fashion Design": "B.des in Fashion Design",
    "M'Des Fashion Design": "M.des in Fashion design",
    "M.Des in Interior Design": "M.des in Interior Design",
    "BSC Fashion Design & Garment Management": "B.sc in Fashion and Apparel Design",
    "Bsc in Fashion Design and Garment Management": "B.sc in Fashion and Apparel Design",
    "MSC Fashion Design & Management": "M.sc in Fashion design and Management",
    "MBA Fashion Business & Event Management": "MBA in Fashion Business and Event Management",
    WILDCARD: "Diploma in Fashion Design",
}


class Command(BaseCommand):
    help = "Seed WebsiteValueMap (campus / program / source) for the website webhook. Idempotent."

    def handle(self, *args, **opts):
        self._seed("campus", CAMPUSES, lambda code: Campus.objects.filter(code=code).first(), "campus")
        self._seed("source", SOURCES, lambda slug: LeadSource.objects.filter(slug=slug).first(), "source")
        self._seed("program", PROGRAMS, lambda name: Program.objects.filter(name__iexact=name).first(), "program")

    def _seed(self, kind, table, find, fk):
        done = skipped = 0
        for website_value, target_key in table.items():
            target = find(target_key)
            if target is None:
                self.stderr.write(f"  {kind}: {website_value!r} → {target_key!r} not found, skipped")
                skipped += 1
                continue
            key = WILDCARD if website_value == WILDCARD else normalise(website_value)
            WebsiteValueMap.objects.update_or_create(
                kind=kind, website_value=key,
                defaults={fk: target, "is_active": True},
            )
            done += 1
        self.stdout.write(f"{kind}: {done} mapped, {skipped} skipped")
