# 2 — Leads

For counsellors and the admissions team. Menu group: **Leads**.

A lead is a prospective student who has enquired. This chapter covers the whole
journey from first enquiry to handing a confirmed student over to Admissions.

---

## 2.1 The journey at a glance

```
   Enquiry arrives  ──►  Assigned to a counsellor automatically
            │
            ▼
   You call / message and log a FOLLOW-UP with an OUTCOME
            │
            ▼
   Interested?  ──►  Send the FEE LINK
            │
            ▼
   Payment received  ──►  MARK THE FEE AS PAID
            │
            ▼
   Send the APPLICATION LINK   (only works after the step above)
            │
            ▼
   Student fills the form online  ──►  Their record is created
            │
            ▼
   PROMOTE to student  ──►  handed over to Admission
```

The order matters. Two steps are enforced by the system and cannot be skipped —
see §2.6.

## 2.2 Where leads come from

**Automatically.** Website forms and advertising platforms send enquiries
straight into the system. These arrive with no counsellor listed as the
creator.

**Manually.** You add them yourself: **Leads → Add Lead**.

Either way, the same checks run.

## 2.3 What happens when a lead arrives

Three things happen by themselves:

**1. Duplicate check.**
The system compares the email address and the phone number against every
existing lead. Only the **last 10 digits** of the phone are compared, so
`+91 99001 12233`, `099001 12233` and `9900112233` all count as the same
number.

If there is a match, the new enquiry is marked as a repeat and labelled by how
many times this person has now enquired:

| Label | Meaning |
|---|---|
| Primary | First enquiry |
| Secondary | Second |
| Tertiary | Third |
| Repeated | Fourth or later |

**2. It goes back to the original counsellor.**
A repeat enquiry is always assigned to whoever handled the first one — even if
someone else entered it. Whoever built the relationship keeps it.

**3. New contact details are saved as alternates.**
If the same person enquires again from a different phone number, that number is
saved as an *alternative phone* on their original record so you can see every
way to reach them. The same happens for email addresses. Existing details are
never overwritten.

### If it is a genuinely new person

The lead is assigned automatically by rotation. Each program category —
Regular, Short and Newly launched — has its own pool of counsellors, and leads
are handed out in turn. Counsellors marked unavailable (for example, on leave)
are skipped.

If no pool exists for that program's category, the lead arrives unassigned and
someone must assign it by hand.

## 2.4 Working the lead list

**Leads → All Leads**.

You see the leads assigned to you. Senior roles see everybody's.

### Filters

You can narrow the list by status, source, campus, program, assigned
counsellor, and by the date the lead was created. There is also:

- a **search box** that matches name, email or phone;
- a **repeat-enquiries** filter;
- an **overdue** filter — leads whose next follow-up date has already passed.
  Start your day here.

> The list shows a maximum of 500 leads at a time. Use the filters to narrow it
> rather than scrolling.

### Lead statuses

| Status | Meaning |
|---|---|
| Active | Being worked |
| Inactive | Parked |
| Non Responsive | Repeatedly unreachable |
| Application Submitted | They have filled the application form |
| Enrolled | Admitted |

## 2.5 Logging a follow-up

Open the lead and add a follow-up after **every** interaction. Record:

- **Type** — phone call, email, WhatsApp, SMS, campus visit, meeting or other
- **Notes** — what was said
- **Next follow-up date** — when you will contact them again
- **Outcome** — how it went (required)
- **Sub-outcome** — the specific reason

### Outcomes and their sub-options

| Outcome | Choose from |
|---|---|
| **Hot** | Decide and call · Planning to visit the campus · Campus visit done |
| **Warm** | Student will call back · Student is not available · Need more time to decide |
| **Cold** | Fees feel high · Cannot relocate to Bangalore · Looking for an online course · Distance is far · Language barrier · Not eligible due to qualification · Wrong number · Joined somewhere else · Looking for other courses · Disconnecting calls · Not looking for any course |
| **Not Answering** | Not answering |
| **Not Connected** | Switched off · Invalid number · Line busy · Temporarily out of service · Incoming barred · Not reachable |
| **Enrolled** | Registration fee fully paid · Registration fee partially paid |

**Choose these carefully.** They are not just notes — they trigger automatic
follow-up messages to the student, and they feed the reports management reads.

### What each outcome triggers automatically

You do not need to do anything for these; saving the follow-up is enough.

| Outcome | The student receives |
|---|---|
| **Hot** | A "why join JD" email straight away, and a WhatsApp reminder on your next follow-up date |
| **Hot** + "Planning to visit the campus" | A visit confirmation email, then reminders 24 hours and 1 hour before the visit |
| **Hot** + "Campus visit done" | A thank-you email and WhatsApp message |
| **Not Answering** | A follow-up message 10 minutes later |
| **Cold** | Re-engagement emails after 30, 60 and 90 days |
| **Enrolled** | A confirmation email and WhatsApp message |

## 2.6 The two rules you cannot skip

### Rule 1 — You must log an outcome before moving a lead's status

If you try to change a lead's status without having logged a follow-up
(with an outcome) since the last status change, the system will refuse.

This exists so the record always explains *why* a lead moved stage.
**Log the follow-up first, then change the status.**

### Rule 2 — The application fee must be paid before the application link goes out

The **Send Application Link** action will fail with a message telling you to
send the fee link first. The sequence is fixed:

1. **Send Fee Link** — the student receives payment instructions by SMS,
   WhatsApp and email.
2. They pay. The bank or UPI reference reaches you or Accounts.
3. **Mark Fee Paid** on the lead — record the amount, payment mode, reference
   number and any notes. All of these are optional except the act of marking it
   paid.
4. **Send Application Link** — now it works.

If you mark a fee paid by mistake, there is an undo action that clears the
record — you may need a specific permission for it.

## 2.7 The Send actions

On a lead's page you will find these actions. Each one may need its own
permission.

| Action | What happens |
|---|---|
| **Send Fee Link** | SMS + WhatsApp + email with the payment link for the correct institute. Records the date it was sent so you can see whether to resend |
| **Send Application Link** | SMS + WhatsApp + email containing the student's personal application-form link. Blocked until the fee is marked paid |
| **Send Welcome** | A welcome email. Needs an email address on the lead |
| **Bulk Message** | Select several leads in the list and send one email to all of them, with attachments if needed |

After sending, the screen shows the result for **each channel separately** —
for example the SMS may have gone but the email failed because the lead has no
email address. Read all three lines, not just the first.

Everything you send is also recorded on the lead's timeline, so anyone opening
the record later can see what the student has already received.

## 2.8 The student's application form

**Send Application Link** gives the student a personal web link. They open it
and fill in their own details, upload their photo and attach their certificates.

Things worth knowing:

- **The link stays valid.** Students often fill it in stages, and you will
  often review it and ask for the gaps. They can return to the same link and
  add more.
- **Blank fields never wipe existing data.** If they resubmit with an empty
  box, whatever was there before is kept.
- **Certificates are replaced, not duplicated.** Re-uploading their 10th
  certificate replaces the previous one instead of adding a second row.
- **They can change their campus and program**, but only to a program actually
  offered at that campus.

### Closing the form

When you are satisfied the form is complete, use **Close application form** on
the lead. After that the student can still *view* what they submitted but can
no longer change it. You can reopen it at any time.

Your own ability to edit the student's details from the Students screen is
unaffected either way.

## 2.9 Entrance exams

**Leads → Entrance Exam.**

Some programs require a candidate to sit an entrance test before admission.

1. **Create the exam** — give it a name, instructions, a duration in minutes,
   and optionally tie it to a program and academic year.
2. **Add questions** — multiple-choice (with the options and the correct one)
   or short-answer. Each question carries marks; the total is calculated for
   you.
3. **Publish** it.
4. **Map** it to the candidates you want to test, setting the window during
   which they may take it. Each candidate gets their own private link.
5. Candidates take the exam from that link. **They do not need a login.**
6. **Multiple-choice answers are marked automatically.** Short answers wait for
   you to read and score them.
7. View results on the exam's report, or on the candidate's own lead page.

You can **Close** an exam when the window has passed.

## 2.10 Counsellor pools

**Leads → Counsellor Pools.** Usually managed by a team lead.

There is one pool per program category — Regular, Short and Newly launched.
Add counsellors to a pool and set their order; new leads in that category are
handed out in rotation.

To take someone out of rotation temporarily (leave, training, workload),
mark them **unavailable** rather than removing them from the pool — their
existing leads stay with them and they resume their place when marked available
again.

## 2.11 Reports

**Leads → Lead Reports.** Which of these you can see depends on your
permissions.

| Report | Answers |
|---|---|
| **Conversion funnel** | How many leads sit at each stage right now |
| **Summary** | The headline numbers |
| **Time per stage** | How long leads typically spend at each stage |
| **Counsellor leaderboard** | Who is converting, and how much |
| **Course-wise revenue** | Enrolments and revenue by program |
| **Lost-lead analysis** | Why we lose people — fees, location, course mismatch, eligibility, language and so on. Built from the Cold sub-outcomes you record |
| **Duplicate frequency** | How often the same phone number enquires repeatedly |

The lost-lead report is only as good as the sub-outcomes counsellors choose.
That is the main reason they are mandatory.

## 2.12 Handing over: promoting to a student

Once the student has applied and you are ready to admit them, use **Promote to
Student** on the lead.

This creates their student record and their portal login, and shows you a
**temporary password once, on screen**. Note it down or send it on immediately
— it is not shown again on that screen. (Admissions can always re-send
credentials later; see [chapter 3](03-admission-students.md).)

Promotion needs both the lead permission and the student-creation permission,
so in many institutes this is done by Admissions rather than the counsellor.

It will fail, with an explanatory message, if:

- the lead has already been promoted;
- the campus has no institute set against it;
- no academic year is marked as current.

All three are for your administrator to fix in Master Data.

## 2.13 What your actions affect

| When you… | This happens elsewhere |
|---|---|
| Log a follow-up with an outcome | Automatic messages are queued to the student; the lead reports update |
| Change a lead's status | The change is recorded permanently on the lead's timeline with your name |
| Mark the fee paid | Unlocks the application link |
| Promote a lead | Creates a student record and a portal login; the lead moves to "Application Submitted" |
| Mark yourself unavailable | New leads skip you until you are marked available again |
