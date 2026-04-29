"""Sequential receipt number generator.

Format: RCP-{CAMPUS_CODE}-{YYYY}-{seq:05d}.
Race-safe enough for HR-scale traffic (single-digit concurrent writers);
the unique constraint on `receipt_no` is the real backstop.
"""

import re
from datetime import datetime

from django.db.models import Max

from apps.fees.models import FeeReceipt


def generate_receipt_no(*, campus_code: str, year: int | None = None) -> str:
    year = year or datetime.now().year
    prefix = f"RCP-{campus_code.upper()}-{year}-"
    last = FeeReceipt.objects.filter(
        receipt_no__startswith=prefix,
    ).aggregate(m=Max("receipt_no"))["m"]
    if last and (m := re.match(r".+-(\d+)$", last)):
        seq = int(m.group(1)) + 1
    else:
        seq = 1
    return f"{prefix}{seq:05d}"
