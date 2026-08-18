# 3 — Admission & Students

For the admissions team and front office. Menu group: **Admission**.

---

## 3.1 Student versus enrolment

Two different things, and the difference matters:

- A **student** is the person — their name, contact details, parents, address,
  photo and certificates. One record, forever.
- An **enrolment** is that student joining a **specific batch**, in a specific
  program, semester, campus and academic year.

A student can exist with **no enrolment** (they applied but have not been
admitted yet), and will build up **several enrolments** over time as they move
through semesters.

Almost everything academic — attendance, fees, assignments, marks, courseware —
hangs off the *enrolment*, not the student. That is why a student with no
active enrolment appears in no class list.

## 3.2 Finding a student

**Admission → Students.**

The list shows students at your campus. Use the search and filters to narrow
it, then select a student to open their profile.

Each student has an **application form number**, generated automatically, and
optionally a **registration number** that you enter by hand once admission is
confirmed. When a registration number exists, it is shown in place of the
application number on the profile.

## 3.3 The student profile

The profile is organised into cards. Which ones you can see depends on your
permissions — personal, family and address details are behind a separate
permission from the basic record, because they are sensitive.

| Card | Contents |
|---|---|
| **Basic details** | Name, date of birth, gender, category, nationality, blood group, placement |
| **Personal & family** | Parents' names, occupations, contact numbers and emails, addresses |
| **Education history** | 10th, 12th, diploma, degree certificates and ID documents |
| **Documents** | Uploaded files |
| **Enrolments** | Every batch this student has been part of |
| **Fees** | Their fee position |
| **Attendance** | Their attendance summary and session-by-session record |
| **Remarks** | Internal notes |
| **Portal access** | Their login and the option to resend credentials |
| **Parent account** | The parent's separate login |

### Editing

Different parts of the profile need different permissions:

| To change… | You need |
|---|---|
| Basic details | The general student-edit permission |
| Institute, campus, program or course | The **transfer** permission — this is a bigger decision than an ordinary edit |
| Registration number | Its own permission |
| Remarks | The add-remark permission |

## 3.4 Remarks

Remarks are internal notes about a student — a conversation, a concern, an
agreement about fees.

They are **append-only**. You add new notes; older ones stay visible with the
name of whoever wrote them and when. Nothing is edited away, so context is
never lost.

## 3.5 Documents

Two kinds of file live on a student:

- **Education history** — one entry per certificate type (10th, 12th, Diploma,
  UG, PG, Aadhaar, Passport, PAN, photo, other), each with its registration
  number, school or board, certificate number, percentage and the scanned file.
- **General documents** — anything else.

Uploading a certificate under a type that already exists **replaces** it rather
than adding a duplicate.

### What files are accepted

The system checks the actual contents of a file, not just its name. Renaming
a file to `.jpg` will not get it past the check.

- Photos: JPEG, PNG or WEBP
- Documents: PDF (and common office formats where allowed)
- Programs, scripts, web pages and SVG images are always rejected
- Photos up to 5 MB, PDFs up to 10 MB, other documents up to 25 MB

If an upload is refused, the message tells you what type the system actually
detected.

## 3.6 Giving a student their portal login

On the student's profile, use **Send portal credentials**.

This resets their password, saves it so you can re-share it without another
reset, and emails the student their username, password and the portal address.

Use it when:

- the student never received the original email,
- they have forgotten their password and cannot use the reset link,
- their email address has changed and they need a fresh copy.

The saved password is cleared automatically once the student logs in
successfully, or once they change it themselves.

> The student's email address must be on their record. If it is missing the
> action fails and tells you so.

## 3.7 Parent accounts

From the student's profile you can create a **parent account** — a separate
login for the parent.

Parents get a **read-only** view: the dashboard, attendance, timetable, lesson
plans and the student's profile. They **cannot** submit assignments, take
tests, apply for leave or book appointments on the student's behalf.

## 3.8 Sending the handbook

**Send handbook** emails the student the induction handbook — attendance norms,
assessment scheme, dress code, library timings and the grievance process. Needs
an email address on the record.

## 3.9 Creating an enrolment

**Admission → Students → (student) → Enrolments**, or the Enrolments screen.

An enrolment needs: program, course, semester, campus, batch and academic year.

Its **status** controls what the student can do:

| Status | Meaning |
|---|---|
| **Pending** | Admitted on paper, not yet started |
| **Active** | Currently studying. **Only Active students appear in class lists, attendance rosters and batch reports** |
| **Promoted** | Moved on to the next semester |
| **Dropped** | Left |
| **Alumni** | Graduated |

> If a student is missing from an attendance list or a batch roster, check
> their enrolment status first. It is almost always this.

### The fee plan

When you create the enrolment you normally set up the fee schedule at the same
time — the down payment and the installments. See [chapter 4](04-fees.md).

Keep the convention of naming the first installment **"Down payment"**. The
fee undertaking document relies on it to lay out the schedule correctly.

## 3.10 The fee undertaking

From an enrolment you can **email the undertaking** — a declaration of the
course, duration, total fee, down payment, installment schedule and any
approved concession, produced as a PDF and sent to the student.

It is generated fresh each time from the current data, so if you correct an
installment and resend, the new version is correct. Nothing is stored, so there
are no stale copies to worry about.

The totals it shows follow one rule:

```
down payment  +  remaining installments  +  approved concessions  =  total fee
```

If the numbers look wrong, the fee plan is wrong — fix it there and resend.

## 3.11 Batch promotion

**Admission → Batch Promotion.**

At the end of a semester, move a whole batch on in one action rather than
editing each student. Two operations live here:

- **Promote** — move students to the next semester or batch.
- **Graduate** — mark students as alumni. This also creates their alumni
  record, capturing their final program, batch and result.

Both need their own permissions and are usually restricted to the academic
office.

## 3.12 Fee reports

Two pages sit under this menu for convenience:

- **Fee Reports** — collections and outstanding amounts
- **Concession Reports** — discounts requested and approved

They only show data for campuses you have access to. Full detail is in
[chapter 4](04-fees.md).

## 3.13 What your actions affect

| When you… | This happens elsewhere |
|---|---|
| Set an enrolment to **Active** | The student appears in attendance rosters, batch rosters and class lists |
| Move an enrolment off **Active** | They disappear from those lists. Past attendance and marks are untouched |
| Change a student's campus | Different staff can now see them; the record leaves your list if it leaves your campus |
| Send portal credentials | Their old password stops working immediately |
| Create a parent account | The parent can see the student's academic record from that moment |
| Graduate a student | Their enrolment becomes Alumni, an alumni record is created, and certificate eligibility changes |
| Correct a fee installment | The undertaking, balance and any reminder amounts all follow automatically |
