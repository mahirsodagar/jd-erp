# 7 — Academics & Records

For faculty, batch mentors, HODs and the academic office. Menu group:
**Academics** (everything except Attendance, which is
[chapter 5](05-timetable-attendance.md)).

---

## 7.1 Batch Report

**Academics → Batch Report.**

The batch list with headcounts, and for each batch a full student roster.

The roster shows every student's details **for the whole batch at once**, so it
is protected by two separate permissions: one to open the roster, and the
existing sensitive-details permission to see personal, family and address
columns. Without the second, you see the roster with those columns withheld.

You can also set and switch on the batch's **feedback link** here — the
external form students fill in to give feedback. Once enabled, students see it
in their portal under Feedback Links.

## 7.2 Closing Report

**Academics → Closing Report.**

The completion sheet filled in when a batch finishes. For each student it shows
their name, application number and attendance percentage, plus three columns
you fill in:

- **Awards** — JD Annual Design Awards and similar recognition
- **Portfolio** — portfolio notes
- **Remarks** — general remarks

Each cell is saved on its own as you move out of it, so you can work down the
sheet without a save button. There is no personal contact data on this sheet,
so it needs no sensitive-details permission — just the closing-report
permission.

## 7.3 Records

**Academics → Records** holds certificates, alumni and transcripts.

### Certificates

Six types, each with its own eligibility rule:

| Certificate | The student must be |
|---|---|
| **Bonafide** | Currently enrolled and active |
| **Provisional** | Marked as alumni, with marks recorded (they may still be drafts) |
| **Course Completion** | Promoted or alumni, with marks recorded, and **passing every published subject** (40 % or above) |
| **Transfer** | Dropped or alumni |
| **Character** | Any enrolment |
| **No Dues** | Carrying a zero fee balance |

**The flow:**

1. **Request** it — either the student asks, or staff raise it on their behalf.
2. **Check eligibility** — the system tells you whether the rules are met and,
   if not, exactly which one failed.
3. **Issue** or **Reject** it. Issuing and rejecting are separate permissions.
4. If eligibility fails but the certificate should still be issued, someone
   with the **override** permission can go ahead.
5. **Print** the certificate.

**A certificate is frozen at the moment it is issued.** The student's details
are captured onto it, so correcting their name or program afterwards does not
change an already-issued certificate. Reissue if a correction must appear.

Students see theirs at **Records → My Certificates** and in the portal.

### Alumni

When a student graduates, an alumni record is created capturing their final
program, batch, year and result.

The record then stays useful: current status (working, entrepreneur, higher
studies, family business), workplace, job title, LinkedIn and last known
contact details. Keep it updated as you hear from graduates.

**Records → Alumni** shows the full list; a graduate sees their own under
**My Alumni**.

### Transcripts

See [chapter 6](06-teaching-lms.md) §6.4.

## 7.4 0-Hour Form

**Academics → 0-Hour Form.**

Filled in by the class mentor after a batch's 0-Hour session — a readiness
check-in with the batch.

What it captures:

- Date of the session and the batch
- **Batch strength** and how many attended the session
- Average batch attendance for the **1st–15th** and at **month end**
- **Agenda** and **outcome** of the session
- **Activities** planned or completed
- **Remarks**
- Issues **discussed with the HOD or Principal**, and the **action taken**

You fill it here under Academics; the audit team reviews everyone's under
**Audit → 0-Hour Reports**. It is the same information seen from two sides.

You can edit and delete your own. Editing or deleting someone else's needs
extra permissions.

## 7.5 Student Leaves

**Academics → Student Leaves.**

Where **batch mentors** handle leave requests from their students.

**This page needs no permission.** You see requests from the batches you
mentor, matched on your email address. If you mentor no batch, the page is
empty — that is correct, not a fault.

### The flow

1. The student applies from their portal, giving the start date, end date and
   reason.
2. The request appears in your queue.
3. You **approve** or **reject** it, with remarks.
4. The student is emailed the outcome and sees it in their portal.

Approving and rejecting are separate permissions. Someone with the "see all"
permission handles requests across every batch, not just their own.

> Reassigning a batch to a new mentor does **not** move requests that are
> already pending — those stay with the mentor who was recorded when the
> student applied. New requests go to the new mentor.

**Academics → Student Leave Report** gives the campus-wide picture, behind its
own permission.

## 7.6 Document Requests

**Academics → Document Requests.**

Students ask the office for institute-issued letters from their portal:

- Transfer Certificate
- Bonafide Certificate
- Study Certificate
- Bank Letter
- Letter of Recommendation
- Other (they describe what they need)

They give a purpose. You **approve** — optionally attaching the issued document
as a file — or **reject**, with remarks either way. The student sees the
outcome and can download the attachment from their portal.

Approving and rejecting are separate permissions, and the list is limited to
your campuses unless you have the see-all permission.

> This is the lightweight "please write me a letter" path. Formal, numbered
> certificates with eligibility rules go through **Records → Certificates**
> instead (§7.3).

## 7.7 Appointments

**Academics → Appointments.**

Students book a meeting either with an **office team** — Management,
Admissions, Accounts, Academics, Examination, Placement or Other — or with a
**named faculty member**.

**This page needs no permission.** You see requests addressed to you. If none
are, it is empty.

### The flow

1. The student requests a meeting, proposing a date and time and giving a
   reason.
2. You **confirm** or **decline**.
   - When confirming you may set a different date, time and venue. **If you
     leave them blank, the student's proposed slot is accepted as-is** — so
     confirming without changes takes one click.
3. After the meeting, mark it **Completed**.
4. The student can **cancel** their own request while it is still open.

Confirming, declining and completing are three separate permissions —
confirming and declining authorise the meeting, completing records that it
happened.

**Students are notified inside the portal only.** No WhatsApp, SMS or email is
sent for appointments. That is deliberate.

A student can only have one open request with the same team or the same
faculty member at a time — they cannot queue up several.

## 7.8 What your actions affect

| When you… | This happens elsewhere |
|---|---|
| Enable a batch's feedback link | Students see it in their portal |
| Issue a certificate | Its contents are frozen; later profile edits will not appear on it |
| Graduate a student | Their alumni record is created; certificate eligibility changes |
| Approve a student's leave | The student is emailed and sees it in the portal |
| Approve a document request | The student can download the attached file from the portal |
| Confirm an appointment | The student sees the confirmed slot and venue in the portal |
| Submit a 0-Hour report | It appears in the audit team's review list |
