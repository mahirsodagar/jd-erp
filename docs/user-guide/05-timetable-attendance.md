# 5 — Timetable & Attendance

For faculty and academic coordinators. Menu groups: **Slot** and
**Academics → Attendance**.

---

## 5.1 What a slot is

A **slot** is one scheduled class. It joins six things:

> **batch** + **subject** + **instructor** + **classroom** + **date** +
> **time slot**

Attendance is taken against a slot. No slot, no attendance.

A **time slot** is a reusable time block — "Slot 1, 9:30–11:00". They are set
up per academic year, because timings shift from year to year
(**Slot → Time Slots**).

## 5.2 Creating classes

### One at a time

**Slot → New Slot.** Choose the batch, subject, instructor, classroom, date and
time slot.

### A whole week at once

**Slot → Publish Timetable.** Lay out the weekly grid and publish it across a
date range. The system creates one class for each matching day.

There is also a repeat option that creates the same class on one weekday
(say every Tuesday) between a start and end date.

Any classes that could not be created because of a clash are listed back to you
with the reason, so you can fix those individually.

## 5.3 Clash checking

The system checks three things when you schedule a class.

| Clash | What happens |
|---|---|
| **The instructor is already teaching** at that date and time | **Blocked.** You must change something |
| **The batch already has a class** at that date and time | **Blocked.** You must change something |
| **The classroom is already in use** at that date and time | **Warning.** You may override it |

The first two are hard rules — a person cannot be in two places at once, and a
batch cannot attend two classes at once.

The classroom clash is a warning because rooms genuinely get shared, split or
double-booked deliberately. To go ahead anyway you confirm the override, and
you need a specific permission for it. The class is flagged as an override so
it is visible later.

You can also run a **clash check** before committing, to see what would happen.

## 5.4 Viewing the timetable

| Menu | Shows |
|---|---|
| **Slot → Timetable** | The full institute timetable. Needs the timetable-view permission |
| **Slot → Calendar** | The same in calendar form |
| **Academics → My Timetable** | Just your own classes |

**My Timetable needs no permission.** Every instructor and every student can
see their own schedule. Only the institute-wide timetable is restricted —
because it reveals every colleague's teaching load.

## 5.5 Cancelling a class

Cancel a class rather than deleting it. Cancelling keeps the record and frees
the instructor and batch to be scheduled elsewhere in that slot.

> **Deleting a class also deletes its attendance.** Always cancel.

## 5.6 Taking attendance

**Academics → Attendance → Take Attendance.**

Open the class and you get the student list — everyone with an **active
enrolment in that batch**. Mark each student:

| Status | Use for |
|---|---|
| **Present** | |
| **Absent** | |
| **Late** | Counts as present in the percentage |
| **On Duty** | Official institute business. Counts as present |
| **Excused** | Approved absence. Does **not** count as present |

You can add a short note against any student.

### Who can take attendance

**The instructor of the class can always mark it**, with no special permission.
Anyone else needs the marking permission.

### Two things to know about the student list

1. It is built **live** from the batch. A student who joins the batch appears
   next time you open the register; one who leaves disappears. **Attendance you
   already saved is never changed.**
2. If a student is missing, their enrolment is probably not Active — see
   [chapter 3](03-admission-students.md) §3.9.

## 5.7 Freezing attendance

Once a register is correct, **freeze** it. After that, changes need a special
permission — so a register cannot be quietly altered weeks later.

The instructor of the class can freeze their own class. Unfreezing is available
to whoever holds the freeze permission.

Freeze registers as a matter of routine. Reports on timetable adherence use
whether attendance was marked as the signal that the class actually happened.

## 5.8 Notifying absent students

Once attendance is marked, you can send absence alerts. Every absent student
generates messages to:

- the **student** — email, WhatsApp and SMS
- the **parents** — email and SMS to the father's number, and to the mother's
  number **only if it is different** (so a shared phone is not messaged twice)

This needs the notify permission. It is a deliberate action — nothing is sent
just because you marked someone absent.

## 5.9 Attendance reports

**Academics → Attendance → Attendance Report** has five views:

| Tab | Shows |
|---|---|
| **Activity** | What was taught and marked, day by day |
| **Remarks** | The notes staff added against students |
| **Module grid** | Attendance across subjects at a glance |
| **Batch-wise** | Every student in a batch with their percentage |
| **Student-wise** | One student's full record |
| **Instructor log** | One instructor's teaching record — a separate permission, because it is a view of a named colleague's activity |

Students see their own at **Academics → My Attendance**, and in the portal.

### How the percentage is worked out

```
   Present + Late + On Duty
   ─────────────────────────────────────────  × 100
   All scheduled classes in the period
```

The bottom half is **every class that was scheduled**, not just the ones where
attendance was taken. So **classes nobody marked drag the percentage down**.
The reports show an "unmarked" count separately so you can tell the two apart.

If a batch's attendance looks unexpectedly poor, check the unmarked count
before concluding students are missing classes.

## 5.10 What your actions affect

| When you… | This happens elsewhere |
|---|---|
| Publish a class | It appears on the instructor's and students' timetables, and in the portal |
| Cancel a class | It leaves the timetable; the slot becomes free for that instructor and batch |
| Mark attendance | Percentages update; the class counts as delivered in adherence reports |
| Freeze a register | Further changes need a special permission |
| Send absence alerts | Up to five messages per absent student go out |
| Leave a register unmarked | The batch's percentage falls, and the class looks undelivered in audit dashboards |
