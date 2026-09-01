# 13 — Administration

For system administrators. Menu groups: **Admin** and **Master Data**.

You control who can use the system, what they can do, and the reference lists
everyone else chooses from.

---

## 13.1 Users

**Admin → Users** and **Admin → New User**.

A user account is a login. Staff, students and parents all have one.

For each user you manage:

| Setting | Notes |
|---|---|
| **Name, email, active status** | The basics |
| **Roles** | What they can do — see §13.2 |
| **Campuses** | What they can **see** — see §13.3 |
| **Availability** | For counsellors only — see §13.4 |
| **Password reset** | Set a new password for someone who is locked out |

### Four separate permissions

Editing a user is split deliberately, so that giving someone the ability to fix
a typo in a colleague's name does not also let them make themselves an
administrator:

| Permission | Lets you change |
|---|---|
| Edit user | Name, email, active status — nothing more |
| Assign roles | Which roles a user holds |
| Assign campuses | Which campuses a user can see |
| Reset password | Another user's password |

**Do not merge these.** Anyone with all four can effectively grant themselves
full access.

### Removing access

**Deactivate the account rather than deleting it.** A deleted user leaves
unattributed records behind — approvals, receipts and reports that no longer
say who did them. Deactivating stops the login immediately and keeps the
history readable.

## 13.2 Roles and permissions

**Admin → Roles & Permissions.**

A **permission** is a single switch — "record a fee payment", "approve any
leave", "see students from every campus". There are roughly 260 of them,
grouped by area.

A **role** is a named bundle of permissions. Users are given roles, not
individual permissions.

### The two built-in roles

| Role | Contents |
|---|---|
| **Admin** | Every permission. Assign sparingly |
| **Faculty** | The baseline every new employee gets: apply for leave, see their own timetable, attendance, tests and certificates, use tasks, fill their own daily report and self-appraisal, and fill forms addressed to their role |

Both are system roles and cannot be deleted.

### Creating a role

Work from the job, not from the screen. Ask "what does this person need to
do?", then find the matching permissions.

Recommended practice:

1. **Start from the Faculty baseline** and add what the job needs.
2. **Add "view" permissions before "edit" ones.** Many modules need a basic
   view permission before anything else in that area works at all — Fees is the
   clearest example: without the basic receipt-view permission, no fee screen
   opens regardless of what else is ticked.
3. **Be careful with anything named "all" or "any".** `view_all`,
   `view_all_campuses`, `approve_any`, `edit_any` all remove a safety boundary.
4. **Grant approve and reject separately.** They are separate switches for a
   reason.

### Permissions that deserve extra thought

| Permission | Why |
|---|---|
| **See student feedback (with names)** | Removes the anonymity students were promised. A privacy decision |
| **Assign campuses** | Campus assignment is the basis of nearly all visibility. Whoever has this can widen anyone's access, including their own |
| **Assign roles** | Effectively the ability to grant any permission |
| **View all forms (Audit)** | Shows every draft form, including ones aimed at other roles |
| **See sensitive student / employee details** | Personal, family and address data |
| **View batch roster** | Shows a whole batch's details at once. Personal columns still require the sensitive-details permission on top — keep both |
| **Override eligibility (certificates)** | Issues certificates that failed the rules |
| **Override conflict (timetable)** | Publishes classes despite a room clash |
| **Cancel receipt** | Reverses recorded money |

### ⚠ After changing anyone's role

**The user must log out and log back in.** Their access is loaded at login. Until
they do, they will keep seeing the old menu and get "permission denied" on the
new screens.

Tell them this when you make the change — it saves a support call.

## 13.3 Campuses and who sees what

Every user is assigned one or more campuses. Nearly every list in the system —
students, employees, leads, fees, attendance, reports — shows only records from
those campuses.

Some roles hold a "see all campuses" permission for their area and are not
limited this way.

**If a user says "I can't find a record that definitely exists", check their
campus assignment first.** It is the most common cause.

## 13.4 Counsellor availability

On a counsellor's user record there is an **available** switch, with a reason.

- **Available** — they receive new leads in rotation.
- **Unavailable** — they are skipped. Their existing leads stay with them.

Use this for leave, training or workload management, rather than removing
someone from the counsellor list — removing them loses their place in the
rotation.

## 13.5 Master Data

**Master Data** holds the reference lists everyone else picks from. Get these
right and the rest of the system behaves; get them wrong and errors appear in
unrelated places.

| List | Notes |
|---|---|
| **Institutes** | The legal entities. The code is used in generated application numbers and in payment configuration |
| **Campuses** | Physical locations. **Each must have an institute set** |
| **States** and **Cities** | Addresses |
| **Academic Years** | **Exactly one must be marked "current"** |
| **Programs** | Courses of study. Category and degree type both matter — see below |
| **Degrees** | UG / PG / Diploma / Certificate |
| **Courses** | Specific tracks within a program |
| **Semesters** | |
| **Batches** | Student cohorts. **The mentor set here drives several workflows** |
| **Subjects** | Taught modules |
| **Classrooms** | Rooms, per campus |
| **Time Slots** | Reusable time blocks, set up per academic year |
| **Fee Templates** | The standard fee per program, campus and year |
| **Lead Sources** | Where enquiries come from |

### Four settings with far-reaching effects

**1. Academic year — "current".**
Exactly one year must be marked current. Promoting a lead to a student and
accepting an application form both **fail with an error** if none is.

**2. Campus — institute.**
A campus with no institute set makes both of those actions fail too. Check
older campuses; some may predate the field.

**3. Program — category.**
Regular, Short or Newly launched. Reporting and grouping only — it no longer
affects who a lead is assigned to, since all counsellors share one rotation.

**4. Program — degree type.**
Free text such as "B.Des", "M.Des" or "Diploma". Anything containing the word
*diploma* is treated as a diploma course; everything else is treated as a
degree. This decides **which email address fee and admission emails are sent
from**. A typo silently changes the sender.

### Batches and mentors

The **mentor** you set on a batch determines who:

- receives that batch's student leave requests,
- is expected to file the monthly batch-mentor report,
- is expected to file the 0-Hour report.

Changing the mentor redirects **future** work. Requests already pending stay
with the previous mentor.

### Fee templates

A fee template is matched to a student by **academic year + campus + program**.

Two things to be careful about:

- **Editing a template changes existing students' balances**, because the
  figure is read live rather than stored on each student. If a fee is revised
  part-way through a year, **create a new template** instead of editing the old
  one.
- **Do not create overlapping templates** for the same year, campus and program
  — if more than one matches, which one applies is unpredictable.

### Deleting master data

You cannot really delete it. Delete switches the item **inactive**: it stops
appearing in new selections, and everything that already uses it carries on
working. This is deliberate — deleting a campus or a program would break every
historical record attached to it.

## 13.6 Setting up a new academic year — checklist

1. Create the **academic year** and mark it **current** (unmark the old one).
2. Create the year's **time slots**.
3. Create the year's **batches**, each with a **mentor**.
4. Create the year's **fee templates** for each program and campus.
5. Grant staff their **leave allocations** for the new leave year
   ([chapter 9](09-leaves.md) §9.6).
6. Ask your technical team to check the **Casual Leave year window**, which is
   set in the system and must be updated annually.
7. Confirm every campus has an **institute** set.
8. Confirm the **counsellor list** has at least one active member, or new
   leads arrive unassigned.

## 13.7 What your actions affect

| When you… | This happens elsewhere |
|---|---|
| Change a user's role | Nothing, until they log out and back in |
| Change a user's campuses | Immediately changes what they can see across every module |
| Mark a counsellor unavailable | New leads skip them from that moment |
| Mark a different academic year current | New promotions and applications use the new year |
| Edit a fee template | Every matching student's balance changes |
| Change a batch's mentor | Future leave requests and reports go to the new mentor; pending ones do not |
| Change a program's degree type | Changes which address fee and admission emails come from |
| Deactivate a master item | It disappears from new selections; existing records are unaffected |
