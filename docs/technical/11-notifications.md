# 11 — Notifications (`notifications`)

**Not mounted in `config/urls.py`** — this app has no `urls.py` and no
`views.py`. It is a library that every other module calls. There is no admin
screen for templates; they are managed through Django admin and a seeder.

---

## 11.1 The one rule

**Everything outbound goes through `queue_notification(...)`.** Nothing else
should call a provider. The two exceptions in the current codebase are the
handbook email (`apps/admissions/services_handbook.py`) and the bulk-message
endpoint (`apps/leads/bulk_message.py`), which call
`apps.notifications.email.send_email` directly and therefore produce **no
dispatch-log row**. New code should not follow those two.

```python
from apps.notifications.services import queue_notification

queue_notification(
    template_key="fees.receipt.email",   # dotted key, suffix = channel
    recipient="student@example.com",
    context={"name": "...", "amount": "5000", "degree_type": "B.Des"},
    cc="accounts@jdinstitute.edu.in",
    fire_at=None,                        # future datetime → scheduled
    related=receipt,                     # generic FK for traceability
)
```

Returns a `NotificationDispatchLog` (immediate) or a `ScheduledNotification`
(future-dated).

## 11.2 Models

| Model | Purpose |
|---|---|
| `NotificationTemplate` | `key` (unique), `channel` (EMAIL / WHATSAPP / SMS / IN_CRM), `subject_template`, `body_template`, `is_active`. Bodies use Python `str.format()` with named placeholders |
| `ScheduledNotification` | The queue for future-dated sends: `template_key`, `channel`, `recipient`, `cc`, `context` JSON, `fire_at`, `processed_at`, generic FK to the triggering object |
| `NotificationDispatchLog` | **One row per attempt.** `channel`, `template_key`, `recipient`, `cc`, rendered `subject`/`body`, `status` (QUEUED / SENT / FAILED), the provider's verbatim `error`, `sent_at`, generic FK, and a link back to the `ScheduledNotification` if any |

`NotificationDispatchLog` is the diagnostic surface. When someone says "the SMS
didn't arrive", start here.

## 11.3 Dispatch flow

```
queue_notification(template_key, recipient, context, cc, fire_at, related)
        │
        ├─ template row missing?  → FAILED log row explaining how to fix it
        │                            (channel guessed from the key suffix)
        ├─ fire_at in the future? → ScheduledNotification  ─┐
        │                                                   │ process_due()
        └─ otherwise ─────────────────────────────────────► _dispatch_now()
                                                                │
                render subject + body via str.format(context)   │
                create the log row at QUEUED                    │
                                                                ▼
                        ┌───────────────┬─────────────────┬──────────────┐
                        │ SMS           │ WHATSAPP        │ EMAIL        │ IN_CRM
                        │ sms.send_sms  │ whatsapp.send_  │ _send_email  │ stays
                        │               │ whatsapp        │              │ QUEUED
                        └───────────────┴─────────────────┴──────────────┘
                                        │
                            status ← SENT | FAILED, error ← provider reply
```

**Rendering is forgiving:** a missing placeholder falls back to the literal
template rather than dropping the message.

**Channel inference:** if no `NotificationTemplate` row exists,
`_guess_channel` reads the key suffix (`.sms` / `_sms`, `.wa` / `_wa` /
`.whatsapp`, `.in_crm`, else EMAIL) so at least the failure row is filterable.

**IN_CRM messages never dispatch** — they stay QUEUED by design and are read in
the CRM UI.

**WhatsApp is gated twice:** `WHATSAPP_ENABLED` must be True *and* a trigger
must be mapped. While the gate is off the log row simply stays QUEUED — nothing
fails, nothing sends.

### `process_due(batch_size=200)`

Drains `ScheduledNotification` rows where `fire_at <= now` and
`processed_at IS NULL`, dispatching each and stamping `processed_at`. Returns
`{processed, dispatched, missing_template, errors}`.

Run by `manage.py process_notifications`. **This must be on cron** — without
it every drip campaign, campus-visit reminder and cold-lead follow-up silently
accumulates and never fires.

## 11.4 Email transports

Three transports coexist and the routing is **two orthogonal decisions**:

1. **Which provider physically delivers it** — `transport_for(domain)`.
2. **Which From domain it appears from** — `resolve_sender(template_key,
   degree_type)`.

### The domain ↔ service table (`sender.transport_for`)

| Sending domain | Transport |
|---|---|
| `jdindia.com` | **Dedicated SMTP** (its own mailbox/host), configured via `EMAIL_SMTP_BY_DOMAIN` — takes precedence over MSG91 |
| `mail.jdinstitute.com` | **MSG91** templated transactional API |
| `jdinstitute.edu.in` | Default SMTP (Gmail/Workspace) |
| anything else | Default SMTP |

### Provider split (`MSG91_EMAIL_TEMPLATES`)

- **MSG91 (`mail.jdinstitute.com`)** — transactional mail to **external**
  recipients: leads, students, parents.
- **SMTP (`admin.a@jdinstitute.edu.in`)** — **internal** mail to faculty and
  employees: HR workflows, employee leave decisions, task assignments, staff
  password resets. Any template not in `MSG91_EMAIL_TEMPLATES` falls through to
  SMTP.

`SMTP_INTERNAL_TEMPLATE_KEYS` lists the templates that *intentionally* use
SMTP, so the dispatcher can warn if someone adds one to the MSG91 registry by
mistake. **Do not bypass this split** — the two domains have different sender
reputations and branding.

Currently registered MSG91 templates:

| Our key | MSG91 template name |
|---|---|
| `fees.receipt.email` | `student_invoice_copy` |
| `fees.application_fee_receipt.email` | `application_fee_receipt` |
| `academics.assignment_assigned.email` | `assignment_assigned` |
| `leaves.application_status_student.email` | `leave_application_status_student` |
| `student.portal_credentials.email` | `student_portal_credentials` |
| `lead.application_link.email` | `lead_application_link` |
| `lead.fee_link.email` | `lead_fee_link` |
| `lead.welcome.email` | `lead_welcome` |

## 11.5 Sender-domain policy (`sender.py`)

`EMAIL_SENDER_DOMAIN_POLICY` maps a trigger to a routing token:

| Token | Resolves to |
|---|---|
| `COURSE` | `EMAIL_DOMAIN_DIPLOMA` (`jdinstitute.edu.in`) if the program is a diploma, else `EMAIL_DOMAIN_DEGREE` (`jdindia.com`) |
| `PORTAL` | `EMAIL_DOMAIN_PORTAL` (`mail.jdinstitute.com`) |
| `HR` | `EMAIL_DOMAIN_HR` (`jdinstitute.edu.in`) |
| anything else | treated as a literal domain |

`COURSE` triggers: fee link, application link, fee receipt, application-fee
receipt, admission-form-submitted, installment undertaking, installment-pending
reminder. `PORTAL`: student credentials. `HR`: leave and relieving workflows.

Diploma detection is a **substring match** on `Program.degree_type`
(`"diploma" in degree_type.lower()`). Callers pass it into the context as
`degree_type`; anything not matching is treated as a degree course.

### The safety valve

A domain only goes **live** when it has an entry in `EMAIL_SENDER_BY_DOMAIN`.
Domains absent from that map resolve to an empty From-address and the
dispatcher falls back to the provider default. That is how the routing policy
could ship before `jdinstitute.edu.in` and `jdindia.com` were verified on
MSG91 — activating a domain is an env-var change, not a code change.

### The no-SMTP-egress downgrade

When `EMAIL_SMTP_OUTBOUND_ENABLED=False` (hosts that block outbound SMTP, e.g.
PythonAnywhere free), an SMTP-routed trigger **downgrades to MSG91** if it has
a registered template — so mail keeps flowing from `mail.jdinstitute.com` until
proper egress exists. On a downgraded send the From override is suppressed,
because a course domain is not a valid MSG91 sender.

### From-header construction (`email.py::_resolve_from_email`)

Priority: per-trigger override → `DEFAULT_FROM_EMAIL` (kept verbatim if it
already carries a display name, otherwise wrapped with `DEFAULT_FROM_NAME`) →
`EMAIL_HOST_USER` wrapped with the display name → empty, which returns a clean
error rather than letting Django raise deep inside the SMTP code path.

## 11.6 SMS transports

`sms.send_sms` picks the backend from `settings.SMS_PROVIDER`.

### MSG91 flow API (`msg91_sms.py`)

`POST https://control.msg91.com/api/v5/flow/` with a `template_id` (the
**24-char MSG91 flow ID**, not the DLT id) and **positional variables**
`var1`, `var2`, … built by `variables_for()` from
`settings.MSG91_SMS_VAR_ORDER`. The DLT-approved body lives on MSG91's side;
we only send variables.

Phone numbers are normalised to digits only, with a bare 10-digit number
prefixed `91`.

### BulkSMS Gateway India (`sms.py`)

`GET https://api.bulksmsgateway.in/sendmessage.php` with the **rendered body**
and a DLT `template_id` from `BULK_SMS_TEMPLATE_IDS`.

Two quirks worth knowing:

1. BulkSMS treats `&`, `+` and `#` in the body as URL syntax. Their docs
   require base64 substitutions (`Jg==`, `Kw==`, `Iw==`) instead of standard
   percent-encoding. `_bulksms_safe_message` applies them — without it, URLs
   with query strings or `#/portal/login/` fragments arrive broken.
2. **None of BulkSMS's failure strings contain the word "error".** An earlier
   `"error" not in text` heuristic logged every rejection as SENT.
   `_interpret_bulksms_response` now requires an explicit `status: success` and
   surfaces the `refid` so a send can be traced in the BulkSMS panel.

`status: success` means BulkSMS **accepted and billed** the message — not that
the operator delivered it. Final delivery is in the DLR.

### DLT / TRAI

Every SMS body must be pre-registered with the DLT operators under principal
entity `JDEDUC`. `settings.BULK_SMS_TEMPLATE_IDS` maps our template keys to
those registered ids. **You cannot change SMS wording without re-registering
the template.** URLs are shortened via TinyURL
(`apps/notifications/shorten.py`) so the message matches the approved
`tinyurl.com/{var}` format; if TinyURL fails the long URL is used.

## 11.7 WhatsApp — XIRCLS (`whatsapp.py`)

XIRCLS bridges to the WhatsApp Business API. Every send references a
pre-configured **trigger** (campaign) plus named **parameters** that fill the
approved template.

```
POST https://api.xircls.com/talk/api/v1/send_trigger_message/
Api-key: <XIRCLS_API_KEY>                        # Profile → Global Settings
Whatsapp-Project-Key: <XIRCLS_WHATSAPP_PROJECT_KEY>  # Settings → Projects → Token
{ "trigger": "...", "country_code": "91", "contact": "9900000000",
  "parameters": {"parameter_1": "...", "parameter_2": "..."} }
```

- `XIRCLS_WA_TRIGGERS` maps our template key → trigger name. Trigger names are
  not secrets and live in `settings.py`, one per message type. A **blank
  trigger yields a clear "not mapped" error** rather than a provider rejection.
- `XIRCLS_WA_PARAM_MAP` maps our template key →
  `{xircls_param_name: our_context_key}`. Without an entry, the whole context
  dict is passed through as-is.
- Parameters are **positional in naming** (`parameter_1`, `parameter_2`) for
  the real templates.
- A 200 response can still be a failure ("Campaign not active" for an inactive
  trigger) — `_interpret_response` handles that.
- API keys are masked in the logs unless `XIRCLS_LOG_FULL_KEYS=True`.

> **Current state.** `lead.application_link.wa` is temporarily pointed at the
> XIRCLS trigger `"Test"`, whose only variable is `test` (the student name),
> pending approval of the real `application_form_2026` template. Swap
> `XIRCLS_WA_TRIGGERS` and `XIRCLS_WA_PARAM_MAP` together when it lands.
> `lead.fee_link.wa` and the six lead-drip triggers are blank — those messages
> stay queue-only until filled in.

## 11.8 Who produces notifications

| Source | Triggers |
|---|---|
| `leads/signals` (via `notifications/signals.py`) | `lead_welcome_email`, `lead_welcome_wa` on lead create; the full outcome drip on follow-up create |
| `leads/send_links.py` | `lead.application_link.{sms,wa,email}`, `lead.fee_link.{sms,wa,email}`, `lead.welcome.email` |
| `fees/notifications.py` | `fees.installment_paid_{student,parent}.sms` (signal), `fees.installment_due_*` (cron), `fees.bulk_reminder.sms` (command) |
| `academics/attendance_service.py` | `student_absent_email`, `parent_absent_email`, `student_absent_wa`, `attendance.{student,parent}_absent_v2.sms` |
| `admissions/services_portal_email.py` | `student.portal_credentials.email` |
| `relieving`, `tasks`, `leaves` | Internal SMTP triggers |

`apps/leaves/services/notifications.py` is the odd one out — it writes to its
own `EmailDispatchLog` table rather than the notifications queue.

## 11.9 Diagnosing a failed send

1. **Find the log row.** `NotificationDispatchLog.objects.filter(recipient=...)
   .order_by("-created_at")` — check `status` and `error`.
2. **`status=QUEUED` forever** → either the channel is IN_CRM, or WhatsApp is
   gated off, or it is a `ScheduledNotification` and `process_notifications`
   is not on cron.
3. **`status=SENT` but nothing arrived** → check `EMAIL_BACKEND`. The console
   backend prints to stdout and reports success.
4. **MSG91 HTTP 401 / apiError 418** → IP Security. Confirm
   `MSG91_FORCE_IPV4=True` and that the host's IPv4 address is whitelisted on
   the MSG91 dashboard.
5. **MSG91 HTTP 403 / Cloudflare 1010** → the browser-shaped User-Agent is
   missing or was changed. Both clients set one deliberately.
6. **`"No MSG91 flow ID for template_key ..."`** → register the template on the
   MSG91 dashboard and set the matching `MSG91_FLOW_*` env var.
7. **`"No DLT template_id mapped for ..."`** → the BulkSMS `DLT_TPL_*` mapping
   is missing.
8. **`"No XIRCLS trigger mapped for ..."`** → fill `XIRCLS_WA_TRIGGERS`.
9. **`"Template '<key>' not registered."`** → run
   `manage.py seed_notification_templates` or add the row in Django admin.

Smoke tests: `manage.py send_test_mail`, `send_test_sms`, `send_test_wa`,
also wrapped as `scripts/test-jd-mail.sh`, `test-jd-sms.sh`, `test-jd-wa.sh`.

## 11.10 Adding a new notification

1. Pick a key: `<module>.<event>.<channel-suffix>`, e.g.
   `fees.overdue_notice.sms`.
2. Create the `NotificationTemplate` row (seeder or admin) with the right
   `channel` and a `body_template` using `{named}` placeholders.
3. **Email** — decide the transport: add it to `MSG91_EMAIL_TEMPLATES` if it is
   external and you have a registered MSG91 template; otherwise it falls
   through to SMTP. Add it to `EMAIL_SENDER_DOMAIN_POLICY` if the From domain
   should not be the provider default. Add internal keys to
   `SMTP_INTERNAL_TEMPLATE_KEYS`.
4. **SMS** — register the body with DLT, then map both
   `BULK_SMS_TEMPLATE_IDS` and `MSG91_SMS_TEMPLATE_IDS`, and define the
   positional order in `MSG91_SMS_VAR_ORDER`.
5. **WhatsApp** — create the trigger on XIRCLS, add it to `XIRCLS_WA_TRIGGERS`
   and its parameter map to `XIRCLS_WA_PARAM_MAP`.
6. Call `queue_notification(...)` with a context containing every placeholder
   (plus `degree_type` if the trigger is `COURSE`-routed).
7. Verify with the relevant `send_test_*` command and check the log row.
