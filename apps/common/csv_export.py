"""Server-rendered CSV downloads for list/report endpoints.

Mirrors the legacy JD_ERP exports: one header row then data rows, the
file named after the report (e.g. "Student Data.csv"). A UTF-8 BOM is
written first so Excel shows ₹ and non-ASCII names correctly.

Endpoints opt in with `?output=csv`; see `wants_csv`.
"""

import csv
from datetime import date, datetime

from django.http import HttpResponse
from django.utils import timezone


def wants_csv(request) -> bool:
    return (request.query_params.get("output") or "").lower() == "csv"


def fmt_date(value) -> str:
    """dd-mm-YYYY in local time; '' for None."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
    if isinstance(value, (date, datetime)):
        return value.strftime("%d-%m-%Y")
    return str(value)


def csv_response(filename: str, header, rows) -> HttpResponse:
    """`rows` may be any iterable (a generator over `qs.iterator()` is fine)."""
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("﻿")
    w = csv.writer(resp)
    w.writerow(header)
    w.writerows(rows)
    return resp
