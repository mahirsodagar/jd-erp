# 4 — Fees

For the accounts team. Menu: **Admission → Fee Collection**, plus the Fee
Reports and Concession Reports pages.

---

## 4.1 How fees are put together

```
   FEE TEMPLATE        the standard fee for a program, campus and year
        │              (set up once by the admin team)
        ▼
   The student's ENROLMENT
        │
        ├── INSTALLMENTS   the agreed payment schedule
        ├── CONCESSIONS    an approved discount
        ├── OTHER FEES     one-off extras, kept separate
        └── RECEIPTS       money actually received
```

The balance you see on screen is worked out like this:

```
   Total fee            from the fee template
   − Concessions        approved discounts only
   ─────────────────
   = Payable
   − Payments received  active receipts only
   ─────────────────
   = Balance outstanding
```

Two things worth understanding:

- **Only *approved* concessions count.** A pending request changes nothing.
- **Only *active* receipts count.** A cancelled receipt is excluded
  immediately.

## 4.2 Getting in

Everything in this area sits behind one gate: you need the basic
**view fee receipts** permission before any fee screen opens at all. If the Fee
Collection menu is missing, that is what you are lacking.

You will also only see students at your own campus, unless you have been given
cross-campus fee access. That includes the day's collection totals.

## 4.3 Setting up a student's installment plan

Do this once, when the enrolment is created.

1. Open the student's enrolment.
2. Add the installments — each one has a **number in sequence**, a **due date**,
   an **amount** and a **description**.
3. There is a bulk option so you can lay down the whole schedule in one go
   rather than adding rows one at a time.

**Name the first installment "Down payment".** The fee undertaking document
uses that description to separate the down payment from the rest of the
schedule. If you name it something else, the undertaking still generates but
labels it wrongly.

You can edit an installment's amount or due date later, and delete one, each
with its own permission.

## 4.4 Recording a payment

**Admission → Fee Collection**, find the student, and record the receipt.

You will enter:

| Field | Notes |
|---|---|
| **Which installment** | Optional. Link the payment to an installment where it makes sense |
| **Amount before tax** | |
| **SGST / CGST / IGST** | Where applicable |
| **Total received** | The pre-tax amount plus all taxes |
| **Payment mode** | Cash, cheque, demand draft, online, UPI, NEFT or RTGS |
| **Reference** | Cheque number, transaction ID or bank reference |
| **Bank** | |
| **Date received** | |
| **Notes** | |

The **receipt number is generated for you** in the form
`RCP-<campus>-<year>-<number>`. You cannot set it yourself, and it is never
reused.

### Split payments

A student may pay one installment across several receipts. Just link each
receipt to the same installment; the system tracks how much of that installment
has been paid and what is left.

### What happens automatically

As soon as you save an active receipt, **two confirmation SMS messages go out**
— one to the student, one to the parent (father's number, or the mother's if
there is no father's number on file).

If a message fails, your receipt is still saved. Messaging never blocks the
money being recorded.

## 4.5 Correcting a mistake

**Receipts are never deleted.** They are **cancelled**, which keeps the audit
trail intact.

To cancel: open the receipt, choose Cancel, and give a reason. The system
records who cancelled it and when.

Effects of cancelling:

- The amount is removed from the student's paid total immediately.
- The receipt's PDF re-prints clearly marked as cancelled.
- **No message goes to the student.** If they need telling, contact them
  yourself.

Small errors — a wrong reference number or note — can be corrected by editing
the receipt instead, if you have the edit permission.

## 4.6 Other fees

An **other fee** is a one-off charge on top of the course fee: an exam
re-attempt, a material kit, an event fee.

They are kept **deliberately separate** from the course fee:

- They are **not** added to the total fee or the payable amount.
- Payments against them are **not** counted in the course-fee paid total.

So collecting an other fee never disturbs the student's course-fee balance.
That is intentional — it keeps the tuition position clean. Record them as other
fees rather than folding them into an installment.

## 4.7 Concessions

A concession is a discount on the course fee.

1. **Raise the request** on the enrolment — the amount and the reason.
2. It sits as **Pending**, changing nothing.
3. Someone with the approval permission **approves or rejects** it, with
   remarks.
4. Once **approved**, the discount reduces the payable amount immediately, and
   is included in the fee undertaking.

There is only one approval step. Whoever holds the approval permission can
decide.

## 4.8 Receipts and documents

- **Print a receipt** — available on any receipt. Generated fresh each time, so
  it always reflects the current status. Cancelled receipts are printed marked
  as such.
- Students can print their own receipts from the portal.
- The **fee undertaking** is sent from the enrolment — see
  [chapter 3](03-admission-students.md) §3.10.

## 4.9 Automatic fee messages

Three things go out without you doing anything:

| When | Who gets it |
|---|---|
| A payment is recorded | Student and parent — a confirmation SMS each |
| An installment is coming due | Student and parent — a reminder SMS each, sent automatically each morning |
| A reminder campaign is run | Student and parent — a general fee-reminder SMS |

The last one is a deliberate campaign started by your technical team on
request, not something that runs on its own.

Students also receive their receipt copy by email, and the application-fee
receipt where relevant.

> **You cannot change the wording of these SMS messages yourself.** They are
> registered with the telecom regulator and any change means re-registering the
> template. Raise it with your technical team if the wording needs updating.

## 4.10 The reports

**Fee Reports** — what has been collected and what is outstanding, filtered to
your campuses.

**Concession Reports** — concessions requested, approved and rejected.

Both are separate permissions from the fee-collection screen, so someone can be
given reporting access without being able to take money.

## 4.11 Numbers that look wrong — check these first

| Symptom | Usual cause |
|---|---|
| Total fee is zero or unexpected | No fee template matches this student's academic year, campus and program — or more than one does. Ask the admin team to check Master Data → Fee Templates |
| Balance changed without a payment | Someone approved a concession, or cancelled a receipt |
| The student says they paid but the balance is unchanged | The receipt may have been recorded against an **other fee**, which by design does not touch the course-fee balance |
| Everyone's balance changed at once | A fee template was edited. Templates are read live, so editing one changes every matching student's figures |
| Undertaking shows the wrong down payment | The first installment is not described as "Down payment" |

## 4.12 What your actions affect

| When you… | This happens elsewhere |
|---|---|
| Record a receipt | Balance drops; two SMS go out; the receipt appears in the student's portal |
| Cancel a receipt | Balance rises again; no message is sent |
| Approve a concession | Payable drops immediately; the undertaking figures change |
| Add or edit an installment | Due-date reminders follow the new schedule |
| Add an other fee | The course-fee balance is deliberately unaffected |
