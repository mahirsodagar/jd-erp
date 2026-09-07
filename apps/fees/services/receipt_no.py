"""Sequential receipt number generator.

Format: JD{CAMPUS_CODE}{seq:04d}-{YYYY}, e.g. `JDBNG8065-2026` — the
format printed on the paper receipts finance hands to students.

Receipts issued before this format was adopted carry the older
`RCP-{CAMPUS}-{YYYY}-{seq}` numbers and are left alone; the sequence
below only ever looks at numbers in the current format, so the two
coexist without colliding.

Race-safe enough for HR-scale traffic (single-digit concurrent writers);
the unique constraint on `receipt_no` is the real backstop.
"""

import re
from datetime import datetime

from apps.fees.models import FeeReceipt


def generate_receipt_no(*, campus_code: str, year: int | None = None) -> str:
    year = year or datetime.now().year
    prefix = f"JD{campus_code.upper()}"
    suffix = f"-{year}"
    pattern = re.compile(rf"{re.escape(prefix)}(\d+){re.escape(suffix)}\Z")

    # The sequence runs per campus per year. We max in Python rather than
    # in SQL because a string MAX would rank `9999` above `10000` once a
    # busy campus crosses four digits; the candidate set is one campus-
    # year of receipts, so the scan is cheap.
    issued = FeeReceipt.objects.filter(
        receipt_no__startswith=prefix,
        receipt_no__endswith=suffix,
    ).values_list("receipt_no", flat=True)
    seq = max(
        (int(m.group(1)) for n in issued if (m := pattern.match(n))),
        default=0,
    ) + 1
    return f"{prefix}{seq:04d}{suffix}"
