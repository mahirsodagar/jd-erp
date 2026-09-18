"""Which gateway and which bank account a fee is paid into.

JD collects into three HDFC current accounts, owned by two legal
entities, and the client's rule for choosing between them (2026-09-11):

1. **JDSD** (B.Sc / M.Sc / B.Des / M.Des) — JD Educational Trust,
   A/c 50100515602102: application fee, registration fee and every
   installment. The application fee alone goes through **Razorpay**; the
   rest through SmartGateway.
2. **JDIFT** (all diplomas)
   a. Registration fee at *every* centre — JD Institute of Fashion
      Technology ROYALTY, A/c 50200123417910.
   b. Application fee and installments at Bangalore and Goa — JD Institute
      of Fashion Technology, A/c 59245987654321.

Anything the table does not cover (a JDIFT application fee at a centre
other than BLR/GOA, a program with no institute) resolves to **no
route**, which means "no online payment": the caller falls back to the
manual fee link. That is on hold on purpose, not an oversight.

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

#: Settlement accounts. `bank_account` is for humans reading receipts and
#: the admin — the bank decides where money settles from the merchant /
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
        "institute": "JDSD", "fee": FEE_APPLICATION,
        "gateway": GATEWAY_RAZORPAY, "account": "JDSD_TRUST",
    },
    {
        "institute": "JDSD", "fee": [FEE_REGISTRATION, FEE_INSTALLMENT],
        "gateway": GATEWAY_SMARTGATEWAY, "account": "JDSD_TRUST",
    },
    {
        "institute": "JDIFT", "fee": FEE_REGISTRATION,
        "gateway": GATEWAY_SMARTGATEWAY, "account": "JDIFT_ROYALTY",
    },
    {
        "institute": "JDIFT", "campus": ["BLR", "GOA"],
        "fee": [FEE_APPLICATION, FEE_INSTALLMENT],
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
