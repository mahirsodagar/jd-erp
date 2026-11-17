"""Audit > Fee Receipts Export — every fee receipt as a Tally-style
*Receipt voucher* row, filterable student-, program- and campus-wise.

Column order is fixed to the accountant's import sheet (2026-11-14):

    Date, Voucher No, Vtype, Cr One, Cr_1 Amount, Cr Two, Cr_2 Amount,
    Cr Three, Cr_3 Amount, Dr, Amount, Reference number, Narration,
    Cost Centre, <blank>, <blank>

Row rules (agreed 2026-11-14):
  * Only `FeeReceipt` rows — installment and Other-fee receipts, cash
    and online. Registration / application fees collected through the
    payment gateway have no FeeReceipt and are out of scope. Cancelled
    receipts are excluded unless asked for.
  * Cr One   = the student (party ledger) with the pre-tax basic fee.
  * Cr Two   = "GST" with SGST+CGST (or "IGST") when tax > 0, else blank.
               The three credits always sum to `Amount`, which is what
               Tally needs to balance the voucher — so the fee head is
               NOT a separate credit (that would double-count the basic
               fee). It is spelled out in the Narration instead.
  * Cr Three = blank (kept so the sheet shape matches).
  * Dr       = "Cash" for cash receipts, else the bank named on the
               receipt (fallback "Bank").
  * Voucher No = 1, 2, 3 … within the download (date order).
  * Reference number = cheque / DD / UTR / UPI ref on the receipt.
  * Cost Centre = campus code, so campus-wise totals survive the import.
  * The unnamed 16th column carries "Receipts" as in the sample sheet.
"""

import csv
from decimal import Decimal

from django.db.models import Q
from django.http import HttpResponse

from apps.fees.models import FeeReceipt, Installment

HEADERS = [
    "Date", "Voucher No", "Vtype",
    "Cr One ", "Cr_1 Amount", "Cr Two", "Cr_2 Amount",
    "Cr Three", "Cr_3 Amount", "Dr", "Amount",
    "Reference number", "Narration", "Cost Centre", "", "",
]

FEE_HEAD_COURSE = "Course Fees"
FEE_HEAD_REGISTRATION = "Registration Fees"


def base_queryset():
    return (FeeReceipt.objects
            .select_related(
                "enrollment__student", "enrollment__program",
                "enrollment__campus", "enrollment__program__institute",
                "installment", "other_fee",
            )
            .order_by("received_date", "id"))


def apply_filters(qs, params, *, campus_ids=None):
    """`params` is a query dict. `campus_ids` (optional) restricts the
    export to the caller's assigned campuses."""
    if campus_ids:
        qs = qs.filter(enrollment__campus_id__in=campus_ids)
    if v := params.get("campus"):
        qs = qs.filter(enrollment__campus_id=v)
    if v := params.get("program"):
        qs = qs.filter(enrollment__program_id=v)
    if v := params.get("institute"):
        qs = qs.filter(enrollment__program__institute_id=v)
    if v := params.get("student"):
        qs = qs.filter(enrollment__student_id=v)
    if v := (params.get("q") or "").strip():
        qs = qs.filter(
            Q(enrollment__student__student_name__icontains=v)
            | Q(enrollment__student__application_form_id__icontains=v)
            | Q(enrollment__student__registration_number__icontains=v)
            | Q(receipt_no__icontains=v)
        )
    if v := params.get("start_date"):
        qs = qs.filter(received_date__gte=v)
    if v := params.get("end_date"):
        qs = qs.filter(received_date__lte=v)
    if (params.get("include_cancelled") or "") not in ("1", "true"):
        qs = qs.filter(status=FeeReceipt.Status.ACTIVE)
    return qs


def fee_head(r: FeeReceipt) -> str:
    if r.other_fee_id and r.other_fee:
        return r.other_fee.name
    if r.installment_id and r.installment and \
            r.installment.kind == Installment.Kind.REGISTRATION:
        return FEE_HEAD_REGISTRATION
    return FEE_HEAD_COURSE


def _money(v: Decimal) -> str:
    """Tally-friendly: no thousands separator, trailing .00 dropped."""
    v = Decimal(v or 0)
    s = f"{v:.2f}"
    return s[:-3] if s.endswith(".00") else s


def voucher_row(r: FeeReceipt, voucher_no: int) -> dict:
    s = r.enrollment.student
    gst = Decimal(r.sgst or 0) + Decimal(r.cgst or 0) + Decimal(r.igst or 0)
    if gst > 0:
        gst_ledger = "IGST" if Decimal(r.igst or 0) > 0 else "GST"
        cr2, cr2_amt = gst_ledger, _money(gst)
    else:
        cr2, cr2_amt = "", ""

    if r.payment_mode == FeeReceipt.PaymentMode.CASH:
        dr = "Cash"
    else:
        dr = (r.bank or "").strip() or "Bank"

    head = fee_head(r)
    narration = f"Being {head} received from {s.student_name}"
    if r.installment_id and r.installment and head != FEE_HEAD_REGISTRATION:
        narration += f" (Installment {r.installment.sequence})"
    narration += f" — Receipt {r.receipt_no}"
    if r.status == FeeReceipt.Status.CANCELLED:
        narration += " [CANCELLED]"

    d = r.received_date
    return {
        "id": r.id,
        "date": f"{d.day}/{d.month}/{d.year}",
        "voucher_no": voucher_no,
        "vtype": "Receipt",
        "cr_one": s.student_name,
        "cr_1_amount": _money(r.basic_fee),
        "cr_two": cr2,
        "cr_2_amount": cr2_amt,
        "cr_three": "",
        "cr_3_amount": "",
        "dr": dr,
        "amount": _money(r.amount),
        "reference_number": r.instrument_ref or "",
        "narration": narration,
        "cost_centre": r.enrollment.campus.code,
        "tail": "Receipts",
        # Extra context for the on-screen preview only (not in the CSV).
        "receipt_no": r.receipt_no,
        "status": r.status,
        "fee_head": head,
        "payment_mode": r.payment_mode,
        "student_id": s.id,
        "application_form_id": s.application_form_id,
        "program_code": r.enrollment.program.code,
        "campus_code": r.enrollment.campus.code,
    }


def voucher_rows(qs, *, start: int = 1) -> list[dict]:
    """`start` is the voucher number of the first row, so a page of the
    preview numbers its rows exactly as the full CSV does."""
    return [voucher_row(r, i) for i, r in enumerate(qs, start=start)]


def csv_response(qs, filename="Receipt Vch.csv") -> HttpResponse:
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("﻿")  # BOM so Excel reads UTF-8
    w = csv.writer(resp)
    w.writerow(HEADERS)
    for i, r in enumerate(qs.iterator(chunk_size=500), start=1):
        row = voucher_row(r, i)
        w.writerow([
            row["date"], row["voucher_no"], row["vtype"],
            row["cr_one"], row["cr_1_amount"],
            row["cr_two"], row["cr_2_amount"],
            row["cr_three"], row["cr_3_amount"],
            row["dr"], row["amount"],
            row["reference_number"], row["narration"],
            row["cost_centre"], "", row["tail"],
        ])
    return resp
