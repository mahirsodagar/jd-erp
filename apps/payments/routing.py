"""Which gateway and which bank account a fee is paid into.

JD collects into three bank accounts, owned by two legal entities, and
the client's rule for choosing between them (2026-11-02, replacing the
2026-10-26 table, which sent JDSD's registration fee to SmartGateway):

1. **Registration fee, every institute and centre** — through
   **Razorpay** into JD Institute of Fashion Technology ROYALTY,
   A/c 50200123417910. Both the fee paid straight after the application
   form and the "Send link" on the REGISTRATION installment row.
2. **JDSD** (B.Sc / M.Sc / B.Des / M.Des) — JD Educational Trust,
   A/c 50100515602102, through **HDFC SmartGateway**: application fee,
   every course installment and every "other" fee.
3. **JDIFT application fee** — through **HDFC SmartGateway** (user's
   rule, 2026-11-02: "application fees should be paid through
   SmartGateway for all programs and institutes"), settling to the JDIFT
   main account, A/c 59245987654321. That account inherits the shared
   SmartGateway merchant until it has credentials of its own
   (`SMARTGATEWAY_JDIFT_MAIN_*`), and needs
   `SMARTGATEWAY_JDIFT_MAIN_LIVE=True` per environment.

Anything the table does not cover (JDIFT course installments and other
fees, a program with no institute) resolves to **no route**, which
means "no online payment": JDIFT students pay those at the college
(user, 2026-11-02), so the per-row "Send link" is hidden for them. The
older enrollment-level link falls back to the manual fee page (our
UPI/bank page, see `apps.payments.manual`). A zero registration fee
never gets this far — no installment is laid down for it
(`fees.services.registration`).

Institute is read off the *program* — Program.institute is the only
place the ERP records it — never off the campus or the degree name.

The route is frozen onto `PaymentRequest.gateway/account` when the
request is raised, so a later change to this table never sends an
in-flight order's status check to a different merchant.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

# ---------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------

GATEWAY_SMARTGATEWAY = "smartgateway"
GATEWAY_RAZORPAY = "razorpay"

#: Fee kinds the table routes on. Finer than PaymentRequest.purpose,
#: which lumps registration in with the other installments.
FEE_APPLICATION = "APPLICATION_FEE"
FEE_REGISTRATION = "REGISTRATION"
FEE_INSTALLMENT = "INSTALLMENT"
FEE_OTHER = "OTHER_FEE"

#: Settlement accounts. `bank_account` is for humans reading receipts and
#: the admin — the gateway decides where money settles from the merchant /
#: TID configuration, not from anything we send.
ACCOUNTS = {
    "JDSD_TRUST": {
        "label": "JD Educational Trust",
        "bank_account": "50100515602102",
    },
    "JDIFT_MAIN": {
        "label": "JD Institute of Fashion Technology",
        "bank_account": "59245987654321",
    },
    "JDIFT_ROYALTY": {
        "label": "JD Institute of Fashion Technology Royalty",
        "bank_account": "50200123417910",
    },
}

#: Ordered; the first rule that matches wins. A key left out matches
#: anything; a list matches any of its values. Override the whole table
#: per environment with settings.PAYMENT_ROUTES.
DEFAULT_ROUTES = [
    {
        "fee": FEE_REGISTRATION,
        "gateway": GATEWAY_RAZORPAY, "account": "JDIFT_ROYALTY",
    },
    {
        "institute": "JDSD",
        "fee": [FEE_APPLICATION, FEE_INSTALLMENT, FEE_OTHER],
        "gateway": GATEWAY_SMARTGATEWAY, "account": "JDSD_TRUST",
    },
    {
        "institute": "JDIFT", "fee": FEE_APPLICATION,
        "gateway": GATEWAY_SMARTGATEWAY, "account": "JDIFT_MAIN",
    },
]


@dataclass(frozen=True)
class Route:
    gateway: str
    account: str

    @property
    def label(self) -> str:
        return account_label(self.account)


def account_label(account: str) -> str:
    return (ACCOUNTS.get(account) or {}).get("label", account or "default")


def routes() -> list[dict]:
    configured = getattr(settings, "PAYMENT_ROUTES", None)
    return DEFAULT_ROUTES if configured is None else configured


# ---------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------

def _matches(rule_value, actual: str) -> bool:
    if rule_value is None:
        return True
    wanted = [rule_value] if isinstance(rule_value, str) else rule_value
    return (actual or "").upper() in {str(v).upper() for v in wanted}


def resolve(*, fee: str, institute: str, campus: str) -> Route | None:
    """The route for this fee, or None when no rule covers it."""
    for rule in routes():
        if (
            _matches(rule.get("fee"), fee)
            and _matches(rule.get("institute"), institute)
            and _matches(rule.get("campus"), campus)
        ):
            return Route(gateway=rule["gateway"], account=rule["account"])
    return None


def _code(obj) -> str:
    return getattr(obj, "code", "") or ""


def route_for_lead(lead, institute_key: str = "") -> Route | None:
    """Route a lead's application fee.

    `institute_key` is the institute the counsellor sent the fee link
    for, and the SMS names that institute as payee — so it wins over the
    lead's program when both are present.
    """
    program = getattr(lead, "program", None)
    institute = institute_key or _code(getattr(program, "institute", None))
    return resolve(
        fee=FEE_APPLICATION,
        institute=institute,
        campus=_code(getattr(lead, "campus", None)),
    )


def route_for_student_registration(student) -> Route | None:
    """Route an applicant's registration fee, paid straight after the
    application form — there is no enrollment yet, so the institute and
    campus come off the Student's own placement."""
    program = getattr(student, "program", None)
    return resolve(
        fee=FEE_REGISTRATION,
        institute=_code(getattr(program, "institute", None)),
        campus=_code(getattr(student, "campus", None)),
    )


def route_for_installment(installment) -> Route | None:
    """Route a scheduled installment — registration or course fee."""
    from apps.fees.models import Installment

    enrollment = installment.enrollment
    fee = (
        FEE_REGISTRATION
        if installment.kind == Installment.Kind.REGISTRATION
        else FEE_INSTALLMENT
    )
    return resolve(
        fee=fee,
        institute=_code(enrollment.program.institute),
        campus=_code(enrollment.campus),
    )


def route_for_other_fee(other_fee) -> Route | None:
    """Route an ad-hoc "other" fee (exam re-attempt, kit, event…)."""
    enrollment = other_fee.enrollment
    return resolve(
        fee=FEE_OTHER,
        institute=_code(enrollment.program.institute),
        campus=_code(enrollment.campus),
    )
