from django.core.management.base import BaseCommand

from apps.master.models import State


# 28 states
STATES = [
    ("Andhra Pradesh", "AP"), ("Arunachal Pradesh", "AR"), ("Assam", "AS"),
    ("Bihar", "BR"), ("Chhattisgarh", "CG"), ("Goa", "GA"),
    ("Gujarat", "GJ"), ("Haryana", "HR"), ("Himachal Pradesh", "HP"),
    ("Jharkhand", "JH"), ("Karnataka", "KA"), ("Kerala", "KL"),
    ("Madhya Pradesh", "MP"), ("Maharashtra", "MH"), ("Manipur", "MN"),
    ("Meghalaya", "ML"), ("Mizoram", "MZ"), ("Nagaland", "NL"),
    ("Odisha", "OD"), ("Punjab", "PB"), ("Rajasthan", "RJ"),
    ("Sikkim", "SK"), ("Tamil Nadu", "TN"), ("Telangana", "TG"),
    ("Tripura", "TR"), ("Uttar Pradesh", "UP"), ("Uttarakhand", "UK"),
    ("West Bengal", "WB"),
]

# 8 union territories
UTS = [
    ("Andaman and Nicobar Islands", "AN"), ("Chandigarh", "CH"),
    ("Dadra and Nagar Haveli and Daman and Diu", "DH"), ("Delhi", "DL"),
    ("Jammu and Kashmir", "JK"), ("Ladakh", "LA"),
    ("Lakshadweep", "LD"), ("Puducherry", "PY"),
]


class Command(BaseCommand):
    help = "Seed Indian states and union territories. Idempotent."

    def handle(self, *args, **opts):
        for name, code in STATES:
            State.objects.update_or_create(
                code=code,
                defaults={"name": name, "is_union_territory": False},
            )
        for name, code in UTS:
            State.objects.update_or_create(
                code=code,
                defaults={"name": name, "is_union_territory": True},
            )
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(STATES)} states + {len(UTS)} union territories."
        ))
