from django.core.management.base import BaseCommand

from apps.leaves.models import LeaveType


CATALOGUE = [
    # (code, name, category, half_day_allowed, enforce_balance)
    ("CASUAL",        "Casual Leave",    "LEAVE",   True,  True),
    ("COMP_OFF",      "Comp-Off",        "LEAVE",   True,  True),
    ("VISIT",         "Visits",          "ON_DUTY", True,  False),
    ("EXAM_DUTY",     "Examination Duty","ON_DUTY", True,  False),
    ("OTHERS",        "Others",          "ON_DUTY", True,  False),
    ("SATURDAY_OFF",  "Saturday Off",    "LEAVE",   False, False),
    ("PERMISSION",    "Permission",      "LEAVE",   True,  False),
]


class Command(BaseCommand):
    help = "Seed the leave type catalogue. Idempotent."

    def handle(self, *args, **opts):
        for code, name, category, half, enforce in CATALOGUE:
            LeaveType.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "half_day_allowed": half,
                    "enforce_balance": enforce,
                    "is_active": True,
                },
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(CATALOGUE)} leave types."))
