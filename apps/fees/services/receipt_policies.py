"""Program-policy page printed as page 2 of every fee receipt.

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

Blocks are `(kind, *args)` tuples the renderer lays out:

    ("h1", text)          document title, centred
    ("h2", text)          numbered section heading
    ("h3", text)          sub-heading inside a section
    ("p", text)           body paragraph
    ("li", lead, rest)    bullet; `lead` prints bold, `rest` regular
    ("li2", text)         indented second-level bullet
"""

from __future__ import annotations

_SHARED_ADDITIONAL = [
    ("h3", "Additional Policies"),
    ("li", "College Property:",
     "Damage (intentional/accidental) will result in financial liability "
     "+ disciplinary action."),
    ("li", "ID Cards:", "Mandatory at all times. Replacement fee: Rs.500."),
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
    ("li", "Delayed Payments:", "Will incur penalties as per institutional policy."),
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
    ("p", "Respective University"),
    ("h2", "1. ADMISSIONS & FEES"),
    ("h3", "Fees Policy"),
    ("li", "Non-refundable & Non-transferable:",
     "Fees will not be refunded or transferred under any circumstances."),
    ("li", "Rejected Applications:",
     "If the university rejects a student's application, they may opt for "
     "an alternate course at JD Institute."),
    ("li", "Late Payments:",
     "Delayed fee payments will incur penalties as per institutional policy."),
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
    ("p", "Note: Degrees are awarded by the respective affiliated "
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


def policy_for(degree_type: str | None) -> list[tuple]:
    """Pick the policy document for a program's free-text degree type."""
    from apps.notifications.sender import is_diploma

    return DIPLOMA if is_diploma(degree_type) else DEGREE
