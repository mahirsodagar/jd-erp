# 6 — Fees (`fees`)

Mounted at `/api/fees/`. Frontend: `src/pages/fees/FeesCollectPage.tsx`,
`src/pages/admission/FeeReportsPage.tsx`,
`src/pages/admission/ConcessionReportsPage.tsx`, and
`src/pages/students/StudentFeesCard.tsx`.

---

## 6.1 Purpose

Records what a student owes and what they have paid, against an **Enrollment**
(not against a Student). Everything in this module keys off
`admissions.Enrollment`.

## 6.2 The money model

```
master.FeeTemplate            "what this program costs this year"
   keyed on (academic_year, campus, program[, course])
   total_fee is STORED, not computed
        │
        │  looked up at read time by enrollment_balance()
        ▼
admissions.Enrollment ──┬── Installment      (the schedule; seq 1..N)
                        ├── OtherFee         (ad-hoc, NOT in the total)
                        ├── Concession       (discount, needs approval)
                        └── FeeReceipt       (money actually received)
```

### `Installment`

Per-enrolment schedule row: `kind` (COURSE / REGISTRATION), `sequence`
(1-indexed, unique per enrolment), `due_date`, `amount`, `description`. Created
by HR after enrolment, usually in one shot via
`POST /api/fees/installments/bulk/`.

> **Convention:** the React enrolment-create form writes the registration row
> first and the down payment with a `description` starting `"Down payment"`.
> The fee undertaking PDF ([chapter 5](05-admissions.md) §5.6) pulls
> REGISTRATION rows out first, then finds the down payment by description —
> it no longer keys on `sequence == 1`.

#### `kind = REGISTRATION` — the mandatory yearly fee

`master.FeeTemplate.registration_fee` (default ₹10,000) is a **carved-out
slice of `total_fee`, never an addition to it**. It rides the installment
schedule rather than living in `OtherFee` because only installments carry a
due date, link to receipts, and feed the due-date reminders and collection
reports.

Four rules, all enforced server-side rather than only in the UI:

| Rule | Enforced by |
|---|---|
| Amount is fixed by the template | `InstallmentSerializer.validate` |
| At most one per **(student, academic year)** — *not* per enrolment | `InstallmentSerializer.validate` + `services/registration.py`; the bulk endpoint also rejects two in one payload |
| Cannot be deleted, and only its due date/description may be edited | `InstallmentDetailView.delete` / `.patch` |
| Cannot be reduced by a concession | `ConcessionDecisionView` (400 on approval) with `enrollment_balance()` capping as a backstop |

Keying on (student, academic year) matters because `promote_batch()` is used
both for year-to-year promotion **and** for sem 1 → sem 2 inside the same year;
keying on the enrolment would charge a mid-year promotion twice.
`promote_batch()` calls `ensure_registration_installment()` for each new
enrolment, so a 3-year course collects the fee three times without HR having to
remember. The rest of each year's schedule is still built by hand.

**Rolled out forward, not backfilled.** Migration `master.0012` sets
`registration_fee = 0` on every pre-existing template, because their live
enrolments already have schedules summing to `total_fee` with no registration
line — and signed undertakings to match. New templates default to ₹10,000.

### `FeeReceipt`

A payment. `receipt_no` is unique and generated as
`RCP-{CAMPUS_CODE}-{YYYY}-{seq:05d}`.

| Field | Notes |
|---|---|
| `enrollment` | `PROTECT` |
| `installment` | Optional — a receipt may or may not be tied to one. Split payments across several receipts on one installment are allowed |
| `other_fee` | Set when the receipt pays an ad-hoc fee. **Such receipts are excluded from the course-fee balance** |
| `basic_fee`, `sgst`, `cgst`, `igst`, `amount` | `amount` = basic + all three taxes |
| `payment_mode` | CASH / CHEQUE / DD / ONLINE / UPI / NEFT / RTGS |
| `instrument_ref`, `bank`, `received_date`, `notes` | |
| `status` | ACTIVE / CANCELLED, with `cancelled_by`, `cancelled_on`, `cancellation_reason` |

**Receipts are never deleted — only cancelled.** Cancellation is an in-place
status flip, which is why the payment-confirmation signal (which fires only on
`created`) does not re-fire.

### `OtherFee`

An ad-hoc charge (exam re-attempt, material kit, event fee) kept deliberately
**separate** from the scheduled total. It is never folded into
`FeeTemplate.total_fee` or into `enrollment_balance()`'s `total`/`payable`, and
receipts pointing at it are excluded from `paid_total`. This keeps the
course-fee balance untouched by incidental charges. Do not "simplify" it into
the main total.

### `Concession`

A discount on the fee total. Single-step approval per the institute's spec:
anyone holding `fees.concession.approve` can decide. States PENDING /
APPROVED / REJECTED with `approver`, `approver_remarks`, `decided_on`.

## 6.3 Balance computation (`services/balance.py`)

```python
enrollment_balance(enrollment) -> {
  total_fee,            # FeeTemplate.total_fee for (academic_year, campus, program), active
  registration_fee,     # FeeTemplate.registration_fee — INSIDE total_fee, not added to it
  concession_total,     # Σ APPROVED concessions (raw)
  concession_applied,   # concession_total capped at total_fee − registration_fee
  concession_capped,    # True when the two differ
  paid_total,           # Σ ACTIVE receipts WHERE other_fee IS NULL
  payable,              # total_fee − concession_applied
  balance,              # payable − paid_total
  registration_due,     # Σ REGISTRATION installments actually on the schedule
  registration_paid,    # Σ ACTIVE receipts against them
  registration_balance, # due − paid
}
```

A non-zero `registration_fee` alongside a zero `registration_due` means this
year's schedule has not been built yet.

Two behaviours to be aware of:

1. **The template is resolved at read time, not snapshotted.** Editing a
   `FeeTemplate` retroactively changes the balance of every enrolment matching
   that (year, campus, program). If a year's fee is revised mid-session,
   create a new template rather than editing the old one — or accept that
   history shifts.
2. The lookup ignores `FeeTemplate.course`. If several templates match the same
   (year, campus, program) tuple with different courses, `.first()` wins
   arbitrarily.

`installment_balance(installment)` gives per-installment `amount_due` / `paid`
/ `balance`.

## 6.4 Access control

`apps/fees/permissions.py`:

- `FeeAccessPolicy` — **`fees.receipt.view` (or `.view_all`) is the door to the
  entire module.** Without it, no fee endpoint is reachable regardless of the
  finer keys.
- `visible_enrollments_filter(qs, user)` scopes by `enrollment__campus` unless
  the caller holds `fees.receipt.view_all`. That same key is the campus scope
  for every list here, including the day's collection totals.

| Key | Action |
|---|---|
| `fees.receipt.view` / `.view_all` | Module entry / cross-campus |
| `fees.receipt.create` / `.edit` / `.cancel` | Record / correct / cancel |
| `fees.installment.view/add/edit/delete` | Schedule |
| `fees.otherfee.view/add/delete` | Ad-hoc fees |
| `fees.balance.view` | The balance figure |
| `fees.concession.request` / `.approve` | Raise / decide |
| `fees.report.view` | The Fee Reports page |
| `fees.concession_report.view` | The Concession Reports page |

The two report keys are per-page rather than per-action: those pages only read
endpoints that already enforce their own permission and campus scope, so the
key gates the menu entry and the page.

## 6.5 Endpoints

| Method + path | Notes |
|---|---|
| `GET/POST /api/fees/installments/` | |
| `POST /api/fees/installments/bulk/` | Create the whole schedule in one call |
| `GET/PATCH/DELETE /api/fees/installments/<id>/` | |
| `GET/POST /api/fees/other-fees/`, `GET/DELETE /api/fees/other-fees/<id>/` | |
| `GET/POST /api/fees/receipts/` | POST generates `receipt_no` and fires the confirmation SMS |
| `GET/PATCH /api/fees/receipts/<id>/` | |
| `POST /api/fees/receipts/<id>/cancel/` | Requires a reason |
| `GET /api/fees/receipts/<id>/pdf/` | On-demand render |
| `GET/POST /api/fees/concessions/`, `GET/PATCH /api/fees/concessions/<id>/` | |
| `POST /api/fees/concessions/<id>/decision/` | Approve or reject |
| `GET /api/fees/enrollments/<id>/balance/` | The dict above |
| `GET /api/fees/me/` | Student's own fee summary |
| `GET /api/fees/me/receipts/`, `GET /api/fees/me/receipts/<id>/pdf/` | Student's own receipts |

## 6.6 PDF receipts (`services/pdf.py`)

Rendered on demand with fpdf2 and **never stored** — re-rendering is
deterministic and includes the status flag, so a cancelled receipt is clearly
watermarked. As elsewhere, text is transliterated to Latin-1 (`₹` → `INR `)
because fpdf2's built-in Helvetica is Latin-1 only. To support full Unicode you
would need to ship a TTF and register it with `pdf.add_font(...)`.

## 6.7 Notifications produced by this module

`apps/fees/notifications.py`. All sends go through `queue_notification` and are
**best-effort** — a failed SMS is logged and never blocks the receipt or
installment operation.

| Trigger | Template keys | Fired by |
|---|---|---|
| A new ACTIVE receipt | `fees.installment_paid_student.sms`, `fees.installment_paid_parent.sms` | `post_save` signal on `FeeReceipt` (created only) |
| Installment falling due | `fees.installment_due_student.sms`, `fees.installment_due_parent.sms` | `manage.py notify_installments_due` (cron) |
| Bulk campaign | `fees.bulk_reminder.sms` (no variables) | `manage.py notify_fee_bulk_reminder` (on demand) |
| Receipt copy by email | `fees.receipt.email` → MSG91 template `student_invoice_copy` | Fee receipt flow |
| Application-fee receipt | `fees.application_fee_receipt.email` → `application_fee_receipt` | |

The parent recipient is `father_mobile` falling back to `mother_mobile`
(`_parent_phone`). Amounts are rendered without trailing zeros; the installment
number is rendered as an ordinal ("1st", "2nd", "11th").

Because these are DLT-registered SMS templates, the **variable order matters**
and is defined in `settings.MSG91_SMS_VAR_ORDER`. Changing the context keys
here without updating that map sends variables into the wrong slots.

## 6.8 Change impact

| If you change… | Effect |
|---|---|
| `FeeTemplate.total_fee` | Retroactively changes `payable` and `balance` for every matching enrolment |
| `FeeTemplate.registration_fee` | Retroactively changes the concession ceiling for every matching enrolment, and the amount the API will accept for new REGISTRATION rows — existing rows keep the old amount. Raise it on a new template, not a live one |
| A receipt's `other_fee` link | Moves the payment in or out of the course-fee `paid_total` |
| Cancelling a receipt | `paid_total` drops; no notification fires; the PDF re-renders as cancelled |
| Approving a concession | Reduces `payable` immediately; also feeds the fee undertaking's arithmetic |
| The down-payment description convention | The undertaking PDF mislabels the down payment |
| Deleting an `Enrollment` | Blocked — `FeeReceipt.enrollment` is `PROTECT`. Installments, other fees and concessions would cascade, receipts will not |
| SMS context keys | Must be kept in step with `MSG91_SMS_VAR_ORDER` and the DLT-approved bodies |
