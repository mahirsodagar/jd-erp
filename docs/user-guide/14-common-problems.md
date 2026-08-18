# 14 — Common Problems

For everyone. Check here before raising a support request — most questions have
an answer on this page.

---

## 14.1 Logging in

| Problem | What to do |
|---|---|
| **My password doesn't work** | Check you're on the right login page — staff and portal logins are separate. Then use Forgot password |
| **My account is locked** | 5 wrong passwords locks it for 15 minutes. Wait; the lock clears itself. Guessing again restarts the clock |
| **The reset email never arrived** | Check spam. You can only request a few resets an hour. If it still doesn't come, ask your administrator to reset it directly |
| **I get logged out constantly** | You're signed out after about 45 minutes of inactivity. If it happens while you're actively working, report it |
| **"Your session expired"** | Normal after a long break. Log in again. Saved work is safe; unsaved form entries are not |

## 14.2 "I can't see a menu item"

Work through these in order.

**1. Have you logged out and back in since your access changed?**
This fixes it most of the time. Your permissions are loaded at login. After an
administrator changes your role you must log out and back in.

**2. Do you have the permission?**
Menu items you don't have access to are hidden, not greyed out. Ask your
administrator.

**3. Is it a page that's simply empty for you?**
Some pages are visible to everyone but only show work addressed to *you*:

| Page | Empty if |
|---|---|
| Team Approvals | Nobody reports to you |
| Student Leaves | You don't mentor a batch |
| Appointments | No student has requested a meeting with you |
| Relieving | You have no application and aren't an approver on one |
| Forms to fill | No form is published to your role |
| My Tasks | You have no tasks |

That's correct behaviour, not a fault.

## 14.3 "I can't find a record"

| Problem | Usual cause |
|---|---|
| **A student, employee or lead I know exists isn't in my list** | You only see records from **your campuses**. Ask your administrator to check your campus assignment |
| **A colleague can see it and I can't** | Same reason — they have wider campus access or a "view all" permission |
| **A lead isn't in my list** | Counsellors see only leads assigned to them, unless they have the see-all permission |
| **The list seems to stop** | The lead list shows a maximum of 500 at a time. Use the filters |

## 14.4 Messages that didn't arrive

Applies to SMS, WhatsApp and email — to leads, students and parents.

**First, check the obvious:**

1. Is there an email address or phone number on the record? Several actions
   fail silently or partially if the contact detail is blank.
2. Check spam, for email.
3. After a Send action, the screen reports **each channel separately** — the
   SMS may have gone while the email failed. Read all of the lines.

**If it's still missing, tell your technical team:**

- the **exact date and time** you sent it,
- **who** it was for,
- **what** it was (fee link, receipt confirmation, absence alert…),
- **which channel** (SMS, WhatsApp or email).

Every attempt is recorded with the provider's own response, so they can tell
you exactly what happened.

**Things that are normal, not faults:**

| Situation | Explanation |
|---|---|
| **WhatsApp messages aren't going out at all** | WhatsApp is switched off until the institute's message templates are approved. SMS and email are unaffected |
| **A message is "queued" and never sends** | Some messages are scheduled for later — reminders, drip follow-ups. They send at their scheduled time |
| **The SMS wording is wrong or out of date** | SMS wording is registered with the telecom regulator and cannot be changed from inside the system. It needs re-registering. Raise it with your technical team |

## 14.5 Numbers that look wrong

### Attendance percentages look too low

The percentage counts **every scheduled class**, not just the ones where the
register was taken. Classes nobody marked count against the student.

Check the **unmarked** count in the report before concluding students are
missing classes.

### A fee balance looks wrong

| Symptom | Usual cause |
|---|---|
| Total fee is zero or unexpected | No fee template matches the student's year, campus and program — or more than one does |
| The balance changed without a payment | Someone approved a concession, or cancelled a receipt |
| A payment isn't reflected | It may have been recorded against an **other fee**, which by design does not affect the course-fee balance |
| Everyone's balance changed | A fee template was edited. Templates are read live |

See [chapter 4](04-fees.md) §4.11.

### A leave balance looks wrong

- Leave is counted in **plain calendar days including weekends**. A
  Friday-to-Monday application is 4 days, not 2. Public holidays are not
  deducted. This is intentional.
- **Casual Leave** is different again: 12 a year, accruing one per month, and
  the balance counts **months in which you took CL**, not days.
- **Pending applications don't reduce your balance** until they're approved.
- At the start of a new leave year, CL figures depend on a date window your
  technical team must update. If they look wrong in June, that's the first
  thing to check.

See [chapter 9](09-leaves.md) §9.4.

### A transcript looks incomplete

Unpublished marks are left out. The missing subjects are probably still drafts
awaiting the HOD's publication.

## 14.6 "The system won't let me do something"

These are rules, not faults. Each exists for a reason.

| Message | Why | What to do |
|---|---|---|
| **"Send Fee Link first"** on the application link | The application fee must be marked paid before the form goes out | Send the fee link, collect payment, mark it paid, then resend |
| **Can't change a lead's status** | You must log a follow-up with an outcome since the last status change | Log the follow-up, then change the status |
| **"Instructor is already scheduled"** | Someone can't teach two classes at once | Change the time, the instructor or the day |
| **"Batch is already scheduled"** | A batch can't attend two classes at once | Same |
| **"Classroom is already in use"** | A warning, not a block | Confirm the override if the room really is shared. Needs a permission |
| **Can't edit attendance** | The register has been frozen | Ask someone with the unfreeze permission |
| **Can't edit marks** | They've been published | Ask someone with the edit-published permission, or have them retracted |
| **"No current academic year is set"** | Master Data problem | Ask your administrator to mark one current |
| **"Campus has no institute"** | Master Data problem | Ask your administrator to set it |
| **Certificate eligibility failed** | The student doesn't meet the rule for that type | Read which rule failed. Either fix the underlying data or ask someone with the override permission |
| **"Task already exists"** | The same task name is already assigned to that person | Use a more specific name |
| **"You already have an open appointment"** (students) | One open request per team or person | Wait for a reply |
| **Only one relieving application at a time** | | Complete or withdraw the existing one |

## 14.7 File uploads

| Problem | Cause |
|---|---|
| **"File type not allowed"** | The system checks the **contents** of a file, not its name. Renaming won't help. Convert it to a permitted format |
| **"File too large"** | Photos 5 MB, PDFs 10 MB, other documents 25 MB. Employee photos 2 MB |
| **Rejected even though it's a PDF** | It may be corrupt or not actually a PDF. Re-export it |
| **Photo rejected** | Employee photos must be JPEG or PNG |

Programs, scripts, web pages and SVG images are always refused, for security.

## 14.8 Things that are missing on purpose

Please don't report these as faults:

| Missing | Why |
|---|---|
| Withdrawing or cancelling a leave application | Deliberately not built — the module matches the institute's long-standing process. Ask your manager to reject it |
| A holiday calendar for leave | Same reason. Holidays aren't deducted |
| Applying for leave on someone else's behalf | Same reason |
| SMS or email for appointments | Appointment updates are shown in the portal only, by design |
| Deleting a fee receipt | Receipts are cancelled, never deleted, so the audit trail survives |
| Deleting a campus, program or batch | They're deactivated instead, so historical records stay valid |

## 14.9 When to escalate, and what to include

Contact your technical team when:

- something fails with an unexpected error message;
- a message definitely didn't arrive and §14.4 doesn't explain it;
- figures are wrong in a way §14.5 doesn't explain;
- a screen won't load at all.

**Include all of this** — it usually turns a two-day investigation into a
ten-minute one:

- Your **username**
- **What you were trying to do**, step by step
- The **exact error message**, or a screenshot
- **When** it happened, as precisely as you can
- **Which record** — the student's name, the lead's phone number, the receipt
  number
- Whether it works for a **colleague**
- Whether you've tried **logging out and back in**
