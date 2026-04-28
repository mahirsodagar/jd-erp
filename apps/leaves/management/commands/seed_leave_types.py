from django.core.management.base import BaseCommand

from apps.leaves.models import LeaveType


CATALOGUE = [
    # (code, name, category, half_day_allowed)
    ("CASUAL",        "Casual Leave",    "LEAVE",   True),
    ("COMP_OFF",      "Comp-Off",        "LEAVE",   True),
    ("VISIT",         "Visits",          "ON_DUTY", True),
    ("EXAM_DUTY",     "Examination Duty","ON_DUTY", True),
    ("OTHERS",        "Others",          "ON_DUTY", True),
    ("SATURDAY_OFF",  "Saturday Off",    "LEAVE",   False),
    ("PERMISSION",    "Permission",      "LEAVE",   True),
]


class Command(BaseCommand):
    help = "Seed the leave type catalogue. Idempotent."

    def handle(self, *args, **opts):
        for code, name, category, half in CATALOGUE:
            LeaveType.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "half_day_allowed": half,
                    "is_active": True,
                },
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(CATALOGUE)} leave types."))
