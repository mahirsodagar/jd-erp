"""Program-policy page printed as page 2 of the fee receipt and the fee
undertaking.

Two variants, matching the paper receipts finance issues today:

- ``DIPLOMA`` — JD-certified diploma programs, where JD awards the
  qualification itself.
- ``DEGREE`` — BSc/MSc programs run under an affiliated university,
  which awards the degree. Its clauses differ (university approval for
  extensions, separate exam fees, rejected-application fallback), so the
  two are kept as separate documents rather than one with conditionals.

Which one prints is decided by the program's `degree_type` via
`apps.notifications.sender.is_diploma` — the same string that already
routes outgoing mail, so a program never gets diploma email and degree
policies.

Blocks are `(kind, *args)` tuples `apps.common.pdf_theme.draw_policy_page`
lays out:

    ("h1", text)          document title, centred
    ("sub", text)         small grey subtitle under the title, centred
    ("h2", text)          numbered section heading
    ("h3", text)          sub-heading inside a section
    ("p", text)           body paragraph
    ("note", lead, rest)  shaded callout; `lead` prints bold
    ("li", lead, rest)    bullet; `lead` prints bold, `rest` regular
    ("li2", text)         indented second-level bullet

The closing AGREEMENT clause is only part of the document the student
signs: the fee receipt prints the policies without it (and without the
signature boxes), exactly as the paper receipt does.
"""

from __future__ import annotations

# --- Institute-specific lines ----------------------------------------
#
# The penalty and ID-card figures come from the signed 2026 terms
# (`apps.admissions.application_terms`): JDSD "FEES, ACADEMIC RULES,
# STUDENT REGULATIONS AND UNDERTAKING" §1 and §3, JDIFT "RULES &
# REGULATIONS, FEE POLICY AND STUDENT UNDERTAKING" §A and §C. Every fee
# receipt — application, registration, course, installment, other fee —
# and the fee payment schedule print the SAME line for an institute, so
# a student never reads one penalty on the registration receipt and
# another on an installment receipt. Keep these in step with the terms.

#: Late-payment wording per institute code.
LATE_FEE_WORDING = {
    "JDSD": ("Delayed fee payments will incur a late fee of 12% per annum "
             "on the overdue amount, calculated from the due date until the "
             "date of payment. Bank charges actually incurred on a "
             "dishonoured cheque are payable by the student."),
    "JDIFT": ("Fees not remitted on or before the due date attract a late "
              "payment penalty of Rs.500/- per day, calculated from the date "
              "on which the respective instalment falls due. Bank charges "
              "actually incurred on a dishonoured cheque are payable by the "
              "student."),
}
_DEFAULT_LATE_FEE = ("Delayed fee payments will incur penalties as per "
                     "institutional policy.")

#: Fine for not wearing / producing the ID card, per instance. Both 2026
#: documents carry the same figure.
ID_CARD_FINE = 500
#: Replacement fee for a lost ID card per institute code. Both 2026
#: documents say Rs.1000 (the pre-2026 JD Institute figure was Rs.500).
ID_CARD_REPLACEMENT_FEE = {"JDIFT": 1000, "JDSD": 1000}
_DEFAULT_ID_CARD_FEE = 1000


def _late_fee_line(wording: str) -> tuple:
    return ("li", "Late Payments:", wording)


def _id_card_line(fee: int, fine: int = ID_CARD_FINE) -> tuple:
    return ("li", "ID Cards:",
            "Mandatory at all times on campus, including class hours, "
            "breaks, visits, examinations and institute events. Failure to "
            f"wear or produce the card attracts a fine of Rs.{fine} per "
            f"instance. Replacement of a lost card: Rs.{fee}. Cards are "
            "non-transferable; misuse is treated as serious misconduct.")


_LATE_FEE_LINE = _late_fee_line(_DEFAULT_LATE_FEE)
_ID_CARD_LINE = _id_card_line(_DEFAULT_ID_CARD_FEE)

_SHARED_ADDITIONAL = [
    ("h3", "Additional Policies"),
    ("li", "College Property:",
     "Damage (intentional/accidental) will result in financial liability "
     "+ disciplinary action."),
    _ID_CARD_LINE,
    ("li", "Admission Cancellation:",
     "The institute reserves the right to cancel admission for:"),
    ("li2", "Code of conduct violations (by student/parent/guardian)."),
    ("li2", "Misuse of college property (treated as a serious offense)."),
]

_AGREEMENT = [
    ("h2", "AGREEMENT"),
    ("p", "By signing, you agree to follow all terms and conditions, "
          "undertaking and declaration form. Failure to comply may result "
          "in revoked admission or disciplinary action."),
]

DIPLOMA = [
    ("h1", "DIPLOMA PROGRAM POLICIES"),
    ("h2", "1. ADMISSIONS & FEES"),
    ("h3", "Fees Policy"),
    ("li", "Non-refundable & Non-transferable:",
     "All fees are strictly non-refundable and non-transferable under any "
     "circumstances."),
    ("li", "Certificates:", "Issued only upon successful completion of the course."),
    _LATE_FEE_LINE,
    ("li", "Repeats:",
     "Students repeating a semester/subject must pay separate examination fees."),
    ("li", "Course Fees Include:",
     "Tuition, library access, and laboratory usage for the academic year."),
    ("li", "Additional Costs:",
     "Materials, industry visits, software, etc. are the student's responsibility."),
    ("li", "Mandatory Disclosure:",
     "Physical/mental health conditions and/or criminal records must be "
     "declared at admission."),
    ("li", "Fee Revision:", "Tuition fees may be revised as per institutional policies."),

    ("h2", "2. ACADEMIC REQUIREMENTS"),
    ("p", "To qualify for the diploma, students must:"),
    ("li", "", "Pass all subjects with minimum required marks within the "
                "stipulated course duration."),
    ("li", "Repeats/Extensions:",
     "Will incur additional costs (per institutional policy)."),
    ("li", "", "Maintain minimum attendance as per guidelines."),
    ("li", "", "Submit a final design portfolio by the prescribed deadline."),
    ("li", "", "Participate in JD Design Awards (only eligible collections "
                "will be showcased)."),
    ("li", "", "Submit an internship completion certificate from the employer."),
    *_SHARED_ADDITIONAL,

    ("h2", "3. TRANSFERS & BATCH SHIFTS"),
    ("h3", "Batch Transfers"),
    ("li", "", "Permitted only for exceptional cases (medical/family "
                "emergencies) with management approval."),
    ("h3", "Fees"),
    ("li", "", "First shift: Rs.10,000"),
    ("li", "", "Second shift: Rs.20,000"),
    ("li", "", "Subsequent shifts: Higher fees as per management discretion."),
    ("h3", "Course Transfers (within JD-affiliated programs)"),
    ("li", "", "Require management approval + valid justification/documentation."),
    ("li", "", "Fee: Rs.25,000."),
    ("li", "", "Student must comply with the new centre's fee structure and policies."),
    *_AGREEMENT,
]

DEGREE = [
    ("h1", "BSC/MSC PROGRAM POLICIES"),
    ("sub", "Respective University"),
    ("h2", "1. ADMISSIONS & FEES"),
    ("h3", "Fees Policy"),
    ("li", "Non-refundable & Non-transferable:",
     "Fees will not be refunded or transferred under any circumstances."),
    ("li", "Rejected Applications:",
     "If the university rejects a student's application, they may opt for "
     "an alternate course at JD Institute."),
    _LATE_FEE_LINE,
    ("li", "Course Fee Includes:",
     "Tuition, library access, and laboratory usage for the academic year."),
    ("li", "Examination Fees:", "Paid separately by the student."),
    ("li", "Additional Costs:",
     "Students are responsible for study materials, industry visits, "
     "software, and other program-related expenses."),
    ("li", "Mandatory Disclosure:",
     "Physical/mental health conditions and criminal records must be "
     "declared at admission."),
    ("li", "Fee Revision:", "Tuition fees may be revised per institutional policies."),
    ("note", "Note:", "Degrees are awarded by the respective affiliated "
             "university, not JD Institute."),

    ("h2", "2. ACADEMIC REQUIREMENTS"),
    ("p", "To graduate, students must:"),
    ("li", "", "Pass all subjects within the stipulated duration."),
    ("li", "Extensions/Readmissions:", "Require university pre-approval."),
    ("li", "", "Readmission fees must be paid via DD/NEFT to the university."),
    ("li", "", "Maintain minimum attendance as per university guidelines."),
    ("li", "", "Submit a final portfolio by the deadline."),
    ("li", "", "Participate in JD Design Awards (only eligible collections showcased)."),
    ("li", "", "Submit an internship completion certificate issued by the "
                "employer/organization."),
    *_SHARED_ADDITIONAL,

    ("h2", "3. TRANSFERS & BATCH SHIFTS"),
    ("h3", "Batch Transfers"),
    ("li", "", "Permitted only for valid reasons (medical/family emergencies) "
                "with documentation + management approval."),
    ("h3", "Fees"),
    ("li", "", "First shift: Rs.10,000"),
    ("li", "", "Second shift: Rs.20,000"),
    ("li", "", "Subsequent shifts: Higher fees as per management discretion."),
    ("h3", "Course Transfers (within JD-affiliated programs)"),
    ("li", "", "Require university + management approval."),
    ("li", "", "Submit valid justification + supporting documents."),
    ("li", "", "Transfer fee: Rs.25,000."),
    ("li", "", "Must comply with the new centre's fee structure & academic policies."),
    *_AGREEMENT,
]

#: Signature boxes drawn at the foot of the policy page.
SIGNATORIES = ("Authorised Signatory", "Student Signature",
               "Parents/Guardian Signature")


def is_diploma(degree_type: str | None) -> bool:
    """True when a program's free-form `degree_type` denotes a diploma.

    `degree_type` is entered by hand (e.g. "B.Des", "M.Des", "Diploma"),
    so we match on substring rather than equality. Anything that isn't a
    diploma is treated as a degree / bachelors course.
    """
    return "diploma" in (degree_type or "").strip().lower()


def policy_for(degree_type: str | None, *, agreement: bool = True,
               institute=None) -> list[tuple]:
    """Pick the policy document for a program's free-text degree type.

    `agreement=False` drops the AGREEMENT clause — the receipt variant,
    which nobody signs. `institute` (an `Institute` or its code) swaps in
    that institute's late-payment penalty and ID-card figures from the
    signed 2026 terms; without it (or for an institute without its own
    terms) the generic "as per institutional policy" line prints.

    The module-level documents are never mutated: a fresh list is
    returned every call."""
    doc = DIPLOMA if is_diploma(degree_type) else DEGREE
    if not agreement:
        doc = [b for b in doc if b not in _AGREEMENT]
    code = (institute if isinstance(institute, str)
            else getattr(institute, "code", "") or "").upper()
    late_fee = _late_fee_line(LATE_FEE_WORDING.get(code, _DEFAULT_LATE_FEE))
    id_card = _id_card_line(ID_CARD_REPLACEMENT_FEE.get(code, _DEFAULT_ID_CARD_FEE))
    swaps = {_LATE_FEE_LINE: late_fee, _ID_CARD_LINE: id_card}
    return [swaps.get(b, b) for b in doc]
