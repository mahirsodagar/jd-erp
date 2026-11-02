"""The manual-payment page: what a fee link points at when the fee has
no online route.

Until 2026-11 that link was a per-institute short URL into Qfix, a
third-party form service JD no longer uses. The page now lives here, so
it never goes stale and never depends on anyone else: it shows the
institute's UPI QR (amount pre-filled when known), the UPI ID and the
bank-transfer details from `settings.INSTITUTE_PAYMENT_DETAILS`.

Payments made this way are not self-reconciling — accounts still records
the receipt by hand, exactly as before.
"""

from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings
from django.utils.html import escape

from .services import _public_api_base

PATH = "/api/public/pay/manual/{institute}/"


def institute_details(institute_key: str) -> dict | None:
    """UPI / bank details for an institute code, or None if unknown."""
    cfg = getattr(settings, "INSTITUTE_PAYMENT_DETAILS", {}) or {}
    return cfg.get((institute_key or "").upper())


def clean_amount(raw) -> str:
    """A positive money amount as a plain string, else ''.

    The amount rides in the query string, so it is advisory only: it
    pre-fills the QR and is printed on the page, nothing more.
    """
    try:
        value = Decimal(str(raw or "").strip())
    except (InvalidOperation, ValueError):
        return ""
    if value <= 0 or value > Decimal("10000000"):
        return ""
    value = value.quantize(Decimal("1.00"))
    return f"{value:.0f}" if value == value.to_integral_value() else f"{value:.2f}"


def manual_pay_url(institute_key: str, *, amount="", purpose: str = "") -> str:
    """Absolute URL of the manual-payment page for this institute.

    Raises `ValueError` when the institute has no payment details or the
    public origin of this API is not configured — both are setup
    mistakes the counsellor must see, not something to paper over.
    """
    key = (institute_key or "").upper()
    if institute_details(key) is None:
        raise ValueError(
            f"No INSTITUTE_PAYMENT_DETAILS entry for '{institute_key}', so "
            f"no manual fee link can be built.",
        )
    try:
        base = _public_api_base()
    except Exception as e:  # SmartGatewayError — keep callers gateway-agnostic
        raise ValueError(
            f"Cannot build the manual fee link: {e}",
        ) from e
    params = {}
    amount = clean_amount(amount)
    if amount:
        params["amount"] = amount
    if purpose:
        params["for"] = purpose[:60]
    url = base + PATH.format(institute=key)
    return f"{url}?{urlencode(params)}" if params else url


def render_page(institute_key: str, *, amount="", purpose: str = "") -> str:
    """The HTML the student sees. Inline-styled, phone-first."""
    # Lazy: leads.send_links imports payments lazily for the same reason.
    from apps.leads.send_links import _qr_png_bytes, _upi_deeplink

    details = institute_details(institute_key)
    if details is None:
        raise LookupError(institute_key)

    amount = clean_amount(amount)
    purpose = (purpose or "").strip()[:60] or "Fee payment"
    payee = details["payee_name"]
    note = f"{purpose} - {payee}"[:50]
    upi_uri = _upi_deeplink(
        vpa=details["vpa"], payee_name=payee, amount=amount, note=note,
    )
    qr_b64 = base64.b64encode(_qr_png_bytes(upi_uri)).decode("ascii")

    amount_block = (
        f'<p class="amount">Amount <strong>&#8377;{escape(amount)}</strong></p>'
        if amount else
        '<p class="muted">Enter the amount advised by the admissions team.</p>'
    )
    rows = "".join(
        f'<tr><th>{label}</th><td>{escape(str(details.get(field, "") or "—"))}</td></tr>'
        for label, field in (
            ("Account name", "ac_name"), ("Account no", "ac_no"),
            ("IFSC", "ifsc"), ("Bank", "bank"), ("Branch", "branch"),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(purpose)} — {escape(payee)}</title>
<style>
  body {{ margin: 0; font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
         background: #f3f4f6; color: #1f2937; }}
  main {{ max-width: 520px; margin: 0 auto; padding: 24px 16px 40px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 20px; margin-top: 16px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  h2 {{ font-size: 15px; margin: 0 0 12px; }}
  .muted {{ color: #6b7280; font-size: 14px; margin: 0; }}
  .amount {{ font-size: 16px; margin: 8px 0 0; }}
  .qr {{ display: block; width: 220px; height: 220px; margin: 12px auto;
        border: 1px solid #e5e7eb; border-radius: 8px; }}
  .upi {{ text-align: center; font-size: 14px; margin: 0; }}
  .btn {{ display: block; text-align: center; margin: 14px auto 0; padding: 12px 16px;
         background: #be185d; color: #fff; border-radius: 8px; text-decoration: none;
         font-weight: 600; max-width: 260px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{ text-align: left; color: #6b7280; font-weight: 500; padding: 6px 12px 6px 0;
       white-space: nowrap; vertical-align: top; }}
  td {{ padding: 6px 0; font-family: ui-monospace, Menlo, monospace; word-break: break-all; }}
  footer {{ font-size: 13px; color: #6b7280; margin-top: 20px; line-height: 1.5; }}
</style>
</head>
<body>
<main>
  <h1>{escape(payee)}</h1>
  <p class="muted">{escape(purpose)}</p>
  {amount_block}

  <section class="card">
    <h2>Scan to pay with any UPI app</h2>
    <img class="qr" src="data:image/png;base64,{qr_b64}" alt="UPI QR code">
    <p class="upi">UPI ID: <strong>{escape(details["vpa"])}</strong></p>
    <a class="btn" href="{escape(upi_uri)}">Open in UPI app</a>
  </section>

  <section class="card">
    <h2>Bank transfer (NEFT / RTGS / IMPS)</h2>
    <table>{rows}</table>
  </section>

  <footer>
    After paying, please reply to the SMS or email you received with the
    UPI transaction ID or bank reference number, so the admissions team
    can verify your payment.
  </footer>
</main>
</body>
</html>
"""
