# 9 — Leaves

For everyone, plus managers who approve and HR who allocate. Menu group:
**Leaves**.

---

## 9.1 What's in the menu

| Page | For |
|---|---|
| **Apply Leave** | Everyone |
| **My Leaves** | Everyone — your own history |
| **Comp-Off** | Everyone — claiming a day back for working a holiday |
| **Balances** | Everyone — what you have left |
| **Team Approvals** | Managers |
| **Allocations** | HR |
| **Leave Report** | HR and management |
| **Leave Types** | HR |

## 9.2 Applying for leave

**Leaves → Apply Leave.**

Fill in:

| Field | Notes |
|---|---|
| **Leave type** | Casual, comp-off and so on — the list your institute has set up |
| **From** and **To** dates | |
| **Session** | Half day (morning), full day, or one of the two permission slots |
| **Reason** | |
| **CC** | Anyone else who should be told |

**You can only apply for yourself.** There is no apply-on-behalf-of option.

### How days are counted

The system counts **plain calendar days**, including both the first and last
day.

**Weekends and public holidays are not deducted.** A Friday-to-Monday
application counts as **4 days**, not 2.

This matches how the institute has always counted leave. If it looks wrong to
you, it is behaving as intended — check with HR before assuming it is a fault.

For a **single day**:

- Half day (morning) → **0.5**
- Full day → **1**
- Either permission slot → **0.5**

### Who your application goes to

It goes to your **first reporting manager**, whose address is captured at the
moment you apply. HR is copied automatically.

> Because the manager is captured when you apply, **a later change to your
> reporting manager does not reroute an application already pending.** It goes
> to whoever was your manager when you applied.

## 9.3 Comp-off

**Leaves → Comp-Off.**

If you worked on a day you were not required to, claim it back:

1. Record the **date you worked** and which session(s) — first, second or both.
2. Give a reason.
3. Your manager approves or rejects it.

Once approved, the day joins your comp-off pool. You then **use** it by
applying for leave with the comp-off leave type.

So comp-off has two halves: **earning** it here, and **spending** it through
the normal Apply Leave screen.

## 9.4 Understanding your balances

**Leaves → Balances.**

Two different figures appear, and they are calculated differently. This is the
most common source of confusion.

### Balance per leave type

```
   Total ever allocated to you   (by HR)
   − Total approved and taken
   ─────────────────────────────
   = Your balance
```

This is a **lifetime** figure, not per-year. Pending applications are shown
separately and do **not** reduce the balance until they are approved.

### Casual Leave on the Apply screen

Casual Leave is shown differently: it builds up at **one day per month**, up to
**12 in a leave year**.

```
   12  −  the number of different months in which a CL was approved
```

Note "different **months**", not "days taken". Two Casual Leaves in the same
month use up **one** month of accrual, not two.

### Comp-off balance

```
   Comp-off days approved   (earned)
   − Comp-off leave taken   (spent)
   ─────────────────────────
   = Your comp-off balance
```

### On-duty types

Types in the "on-duty" category are unlimited and show no balance.

> **A note for HR.** The leave year used by the Casual Leave calculation is a
> fixed window set in the system and must be updated each year by the technical
> team. If CL balances look wrong at the start of a new leave year, that is the
> first thing to check.

## 9.5 Approving leave — for managers

**Leaves → Team Approvals.**

**This page needs no permission.** You see requests from the people who report
to you. If nobody reports to you, it is empty — that is correct.

For each request you see the person, leave type, dates, session, day count,
reason and their balance. You **approve** or **reject**, with remarks.

The applicant is emailed the outcome.

### Approving outside your own team

Two extra permissions exist for HR and senior management:

- **See all** — every employee's applications, not just your team's.
- **Approve any / Reject any** — decide any request. Approving and rejecting
  are deliberately separate permissions.

## 9.6 Allocations — for HR

**Leaves → Allocations.**

An allocation grants an employee a number of days of a particular leave type,
valid between a start and end date.

- There is a **bulk option** for granting the same allocation to many employees
  at once — use it at the start of a leave year.
- An allocation can be **deleted only while it is unconsumed**.
- One allocation per employee, per leave type, per date window.

Balances are simply the sum of allocations minus what has been approved, so
adding an allocation increases the balance immediately.

## 9.7 Leave types — for HR

**Leaves → Leave Types.**

Each type has a short code, a name, a category (**Leave** or **On-duty**), and
whether half days are allowed.

> **Warning for HR.** The system identifies Casual Leave and Comp-Off **by
> their codes**. Renaming those codes silently breaks the Casual Leave accrual
> and the comp-off balance. Change the display name if you need to, never the
> code — and ask your technical team first.

## 9.8 The leave report

**Leaves → Leave Report.**

Leave taken across the institute, filtered to your campuses — or to every
campus if you hold the wider permission.

Deleting a leave application is a separate permission again, and should be used
only to remove a genuine data-entry error.

## 9.9 Features that are deliberately absent

The following do **not** exist, and their absence is intentional — the module
was rebuilt to match the institute's long-standing process exactly:

- **Withdrawing or cancelling a leave application after submitting it.** Ask
  your manager to reject it, or HR to remove it.
- **A holiday calendar.** Public holidays are not deducted from leave counts.
- **Applying on someone else's behalf.**

Please do not report these as missing features. If the institute decides it
wants them, that is a change request, not a bug.

## 9.10 What your actions affect

| When you… | This happens elsewhere |
|---|---|
| Apply for leave | Your manager and HR are emailed; the days show as pending on your balance |
| Have leave approved | The days come off your balance; the leave appears in the report and in faculty workload calculations |
| Have comp-off approved | Days are added to your comp-off pool, to be spent through Apply Leave |
| Receive a new allocation (HR) | Your balance rises immediately |
| Change your reporting manager | Only affects **future** applications |
