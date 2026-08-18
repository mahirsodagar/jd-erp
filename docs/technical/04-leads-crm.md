# 4 — Leads / CRM (`leads`)

Mounted at `/api/leads/`. Frontend under `src/pages/leads/`.

The commercial front door of the system: every student begins life here as a
lead. The module implements the institute's documented *JD Lead-to-Admission
Process*, and several behaviours are deliberate ports of that process rather
than generic CRM defaults.

---

## 4.1 The pipeline

```
   Website / ads / walk-in
            │
            ▼
   POST /api/leads/intake/  (API key)          Staff: POST /api/leads/
            │                                          │
            └──────────────┬───────────────────────────┘
                           ▼
                    create_lead()
                     ├─ normalise phone (last 10 digits)
                     ├─ detect duplicates (email OR phone)
                     ├─ number the occurrence (Primary/Secondary/…)
                     ├─ merge alternate contacts onto the root lead
                     └─ round-robin assign a counsellor (by program category)
                           │
                           ▼
              Follow-ups with a mandatory OUTCOME
              (HOT / WARM / COLD / NOT_ANSWERING / NOT_CONNECTED / ENROLLED)
                           │  post_save signal → drip notifications
                           ▼
              Send fee link  →  mark application fee paid
                           │           (this is a GATE)
                           ▼
              Send application link (tokenised, public form)
                           │
                           ▼
              Student self-fills →  status: application_submitted
                           │
                           ▼
              Promote to Student  →  apps.admissions
```

## 4.2 Models

### `Lead`

The central row. Field groups:

| Group | Fields |
|---|---|
| Identity | `name`, `email`, `phone`, `phone_normalized`, `alternative_phone`, `alternative_email`, `father_mobile`, `father_email` |
| Placement | `campus`, `program`, `source` (all → `master`) |
| Ownership | `assign_to` (→ `User`), `created_by` (null for API intake) |
| Lifecycle | `status`: `active` / `inactive` / `non_responsive` / `application_submitted` / `enrolled` |
| Dedup | `occurrence_number` (1=Primary … 4+=Repeated), `is_repeated`, `duplicate_of` (self-FK to the earliest matching lead) |
| Application form | `application_token` (UUID), `application_token_sent_at`, `application_locked_for_student`, `application_locked_at`, `application_locked_by` |
| Application fee | `application_fee_paid_at`, `_amount`, `_mode`, `_ref`, `_notes`, `_recorded_by`, `fee_link_sent_at` |
| Misc | `remarks`, `city`, `state` |

`phone_normalized` is the **last 10 digits** and is what dedup matches on.
`backfill_phone_normalized()` exists for historical rows.

### Supporting models

| Model | Purpose |
|---|---|
| `CounsellorPool` | One pool per `Program.Category` (`REGULAR` / `SHORT` / `NEW`), each with a round-robin `pointer` |
| `CounsellorPoolMembership` | Through table; `sort_order` sets the rotation order, `is_active` suspends a member |
| `LeadFollowup` | One interaction: `followup_type`, `notes`, `next_followup_date`, and the **mandatory** `outcome_category` + `outcome_disposition` |
| `LeadStatusHistory` | Append-only status trail. Written by `change_status()` only — no manual API |
| `LeadCommunication` | Record of what was sent (does not itself send). Written by the send-link helpers and the bulk-message endpoint |
| `LeadUtm` | 1:1 marketing attribution (`utm_source/campaign/medium/term/content`) |
| `EntranceExam*` | See §4.8 |

## 4.3 Duplicate handling (`services.create_lead`)

The rules, in order:

1. `phone_normalized = last 10 digits of phone`.
2. Find existing leads matching **email (case-insensitive) OR
   phone_normalized**, earliest first.
3. **No match** → fresh lead, `occurrence_number = 1`, round-robin assignment
   if `assign_to` was not supplied and the program has a category.
4. **Match** → the earliest matching lead is the *root* (walking up
   `duplicate_of` if the match is itself a duplicate). The new lead gets
   `is_repeated=True`, `duplicate_of=root`, and
   `occurrence_number = size of the whole duplicate family + 1`.
   Counting the family — not just the matches — is what makes a third enquiry
   arriving via a different email/phone combination correctly read "Tertiary".
5. **Assignment is forced back to the root's counsellor**, overriding any
   supplied `assign_to`. Whoever first worked the lead keeps it.
6. **Alternate-contact merge** (`_merge_alts`): same email + different phone
   writes the new phone to `root.alternative_phone`; same phone + different
   email writes to `root.alternative_email`. Only fills blanks — never
   overwrites.
7. A `LeadStatusHistory` row is written either way.

## 4.4 Round-robin assignment (`services.assign_via_round_robin`)

- One pool per program category; `select_for_update()` on the pool row makes
  concurrent creates race-safe.
- Eligible members: `membership.is_active` **and** `user.is_active` **and**
  `user.is_available`. The `is_available` flag on `User` is how a counsellor is
  taken out of rotation while on leave.
- Picks `memberships[pool.pointer % len(memberships)]`, then advances the
  pointer.
- Returns `None` (lead left unassigned) if there is no active pool for the
  category or the pool is empty.

## 4.5 Visibility and permissions

`apps/leads/permissions.py::LeadVisibility` is applied to every lead endpoint:

- Superuser or `leads.lead.view_all` → every lead.
- Otherwise → only leads where `assign_to == request.user`.

Queryset filtering happens in the view via `filter_visible(qs, user)`; the
object-level check runs in `has_object_permission`. **Both are needed** —
if you add a new lead endpoint, wire up both.

Action keys (deliberately fine-grained so a counsellor can log a call without
being able to blast bulk SMS or declare fees received):

| Key | Action |
|---|---|
| `leads.lead.view` / `.view_all` | See mine / see everyone's |
| `leads.lead.create` / `.edit` | Add / edit |
| `leads.lead.view_history` | Status timeline |
| `leads.lead.reassign` | Move to another counsellor |
| `leads.lead.change_status` | Advance the stage |
| `leads.lead.promote` | Convert to a student (**also requires `admissions.student.create`**) |
| `leads.followup.view/add/edit/delete` | Follow-ups |
| `leads.communication.log` | Log a call/message |
| `leads.send.fee_link` / `.application_link` / `.welcome` | The three Send actions |
| `leads.bulk_message.send` | Bulk message |
| `leads.application_fee.record` / `.clear` | Mark paid / undo |
| `leads.application_form.lock` | Close / reopen the student's self-fill form |
| `leads.pool.view/add/edit/delete` | Counsellor pools |
| `leads.escalation.receive` | Receive overdue-hot-lead alerts |
| `leads.report.funnel` / `.leaderboard` / `.revenue` / `.quality` | The four report groups |
| `leads.exam.*` | Entrance exams (§4.8) |

## 4.6 Endpoints

### Public intake

```
POST /api/leads/intake/
Header: X-API-Key: <LEAD_INTAKE_API_KEY>
```

No JWT (`authentication_classes = []`). Throttled 120/hour per (key, IP).
**If `LEAD_INTAKE_API_KEY` is unset the endpoint refuses everything** — this is
deliberate fail-closed behaviour, not a bug. Accepts UTM fields alongside the
lead payload and returns `{id, is_repeated, duplicate_of}`.

Use this for website forms, ad-platform webhooks and Zapier. Rotate the key by
changing the env var and restarting; there is only one key and no per-source
identity.

### Staff

| Method + path | Notes |
|---|---|
| `GET /api/leads/` | Filters: `status`, `source`, `campus`, `program`, `assign_to`, `is_repeated=1`, `created_after`, `created_before`, `q` (name/email/phone), `overdue=1`. **Returns at most 500 rows, unpaginated** |
| `POST /api/leads/` | Runs the full dedup pipeline |
| `GET/PATCH /api/leads/<id>/` | |
| `POST /api/leads/<id>/status/` | Guarded — see §4.7 |
| `POST /api/leads/<id>/reassign/` | |
| `POST /api/leads/<id>/promote/` | Needs both `leads.lead.promote` and `admissions.student.create`. Returns the new student id **plus a one-time temporary password** |
| `GET /api/leads/<id>/history/` | |
| `GET/POST /api/leads/<id>/followups/`, `PATCH/DELETE /api/leads/followups/<id>/` | |
| `GET/POST /api/leads/<id>/communications/` | |
| `POST /api/leads/<id>/send-fee-link/` | SMS + WhatsApp + email; stamps `fee_link_sent_at` |
| `POST /api/leads/<id>/mark-fee-paid/` | Body all-optional: `{amount, mode, ref, paid_at, notes}` |
| `POST /api/leads/<id>/clear-fee-paid/` | Undo |
| `POST /api/leads/<id>/send-application-link/` | **Raises 400 unless the fee is marked paid** |
| `POST /api/leads/<id>/send-welcome/` | Requires an email on the lead |
| `POST /api/leads/<id>/application/close/` and `/open/` | Counsellor kill-switch on the public form |
| `POST /api/leads/bulk-message/` | multipart; `lead_ids` (≤500), `channels` (`email`, `whatsapp`), `subject`, `body`, `attachments[]` |
| `GET/POST /api/leads/pools/`, `/pool-members/` + detail routes | |
| `GET /api/leads/reports/{funnel,leaderboard,time-per-stage,lost-analysis,coursewise-revenue,duplicates,summary}/` | |

## 4.7 The two gates

These are the module's most important business rules and the two things most
likely to look like bugs:

**1. Application-fee gate.**
`send_links.send_application_link` raises `ValueError` — surfaced as a 400 —
if `lead.application_fee_paid_at is None`. The sequence is fixed:
*send fee link → collect payment → mark paid → send application link.*

**2. Outcome gate on status progression.**
`services.has_recent_outcome(lead)` returns True only if a follow-up carrying
an `outcome_category` was logged **after** the most recent status-history
entry. The status endpoint uses this to stop a counsellor advancing a lead
without recording what actually happened on the call.

A third, softer control: `application_locked_for_student`. While True the
public form's POST returns 403 ("form closed by counsellor") but GET still
works so the student can see what they submitted. Staff edits through the
authenticated admissions endpoints are unaffected.

## 4.8 Entrance exams

`apps/leads/exam_models.py` (re-exported from `models.py` so Django registers
them under the `leads` app_label) — a near-clone of the academics online-test
feature, retargeted from students to leads.

```
EntranceExam ── EntranceExamQuestion (MCQ | SHORT, marks, sort_order)
     │
     └── EntranceExamAttempt (exam, lead, access_token UUID, start_dt, end_dt)
              └── EntranceExamResponse (attempt, question, answer, marks_awarded)
```

Because prospects have no user account, each attempt carries a public
`access_token` UUID; the candidate takes the exam from a tokenised link at
`/#/exam/<token>` served by three unauthenticated endpoints:

```
GET  /api/public/exam/<uuid:token>/
POST /api/public/exam/<uuid:token>/start/
POST /api/public/exam/<uuid:token>/submit/
```

MCQ answers auto-grade against `answer_key`; SHORT answers need a human via
`POST /api/leads/exam-responses/<id>/review/` (`leads.exam.review`).

Staff routes: `exams/` CRUD, `/publish/`, `/close/`, `/questions/`, `/map/`
(creates attempts for a set of leads), `/attempts/`, `/report/`, plus
`GET /api/leads/<id>/exams/` for the lead-detail panel.

## 4.9 Notifications produced by this module

Two `post_save` signal handlers in `apps/notifications/signals.py` — worth
knowing because they fire automatically:

**On `Lead` create** → queues `lead_welcome_email` and `lead_welcome_wa`.

**On `LeadFollowup` create (with an outcome)** → the drip programme:

| Outcome | Queued |
|---|---|
| `HOT` | `hot_why_join_jd` (email, now); `hot_followup_reminder` (WA, on the next follow-up date) |
| `HOT` + disposition "Planning to visit the campus" | `campus_visit_confirmation` (email); `campus_visit_reminder` (WA) at T-24h and T-1h |
| `HOT` + "Campus visit done" | `post_visit_thanks` (email) + `post_visit_thanks_wa` |
| `NOT_ANSWERING` | `not_answered_followup` (WA) after 10 minutes |
| `COLD` | `cold_drip_30` / `_60` / `_90` (email) |
| `ENROLLED` | `enrolled_confirmation` (email) + `enrolled_confirmation_wa` |

Future-dated ones become `ScheduledNotification` rows and **only fire if
`process_notifications` is on cron**.

`apps/leads/outcomes.py` holds the allowed `outcome_disposition` values per
category (validated on write) and
`cold_disposition_to_lost_reason()` maps Cold dispositions to the report
categories Fee / Location / Course mismatch / Eligibility / Language / Wrong
number / Lost to competitor / Disconnect / Not interested / Other.

## 4.10 The send-link helpers (`send_links.py`)

Every Send action follows the same shape: queue each channel through
`queue_notification(...)` so it lands in `NotificationDispatchLog`, **and**
write a `LeadCommunication` row so the activity timeline shows it. The
response flattens per-leg status so the counsellor sees real outcomes rather
than a static "queued":

```json
{ "sms_log_id": 1, "sms_status": "SENT", "sms_error": "",
  "wa_log_id": 2,  "wa_status": "QUEUED", "wa_error": "",
  "email_log_id": 3, "email_sent": true, "email_error": "",
  "communication_id": 9, "url": "...", "short_url": "..." }
```

Configuration it depends on:

- `settings.INSTITUTE_PAYMENT_DETAILS[institute_key]` — UPI VPA, payee name,
  bank account, `default_amount`. Missing key → `ValueError`.
- `settings.FEE_LINK_URLS[institute_key]` — the DLT-approved short payment
  URL. Missing → `ValueError`.
- `settings.FRONTEND_BASE_URL` — used to build `{base}/#/apply/{token}`, which
  is then run through TinyURL (`apps/notifications/shorten.py`) so the SMS fits
  the DLT template. If TinyURL fails, the long URL is used.
- `lead.program.degree_type` is passed into the email context as `degree_type`
  and decides the sender domain ([chapter 11](11-notifications.md) §11.5).

`send_fee_payment_instructions_email()` still exists for a richer HTML email
with an inline UPI QR and bank-transfer block, but is **not wired into the
current `send_fee_link`** — call it directly if that presentation is wanted.

## 4.11 Reports

| Endpoint | Permission | Content |
|---|---|---|
| `reports/funnel/` | `leads.report.funnel` | Counts by status |
| `reports/summary/` | `leads.report.funnel` | Headline totals |
| `reports/time-per-stage/` | `leads.report.funnel` | Average dwell time per status, from `LeadStatusHistory` |
| `reports/leaderboard/` | `leads.report.leaderboard` | Per-counsellor conversion |
| `reports/coursewise-revenue/` | `leads.report.revenue` | Enrolments + revenue by program |
| `reports/lost-analysis/` | `leads.report.quality` | Cold dispositions bucketed into lost reasons |
| `reports/duplicates/` | `leads.report.quality` | Duplicate-phone frequency |

Revenue and staff rankings are deliberately on different keys from the
duplicate-count report.

## 4.12 Change impact

| If you change… | Effect |
|---|---|
| `normalize_phone` | Changes what counts as a duplicate. Existing `phone_normalized` values would need a backfill |
| Pool membership / `User.is_available` | Immediately changes who receives the next lead |
| `Lead.status` choices | `LeadStatusHistory` stores strings — historical rows keep the old values; the funnel report needs updating |
| Removing the fee gate | Students could receive an application form without paying. Confirm with the institute first |
| `LeadFollowup.Outcome` values | Breaks the signal drip map, `outcomes.CATALOGUE`, and the lost-lead report |
| Deleting a `Lead` | `Student.lead_origin` is `SET_NULL`, so the student survives with no origin. Follow-ups, history, communications and UTM cascade away |
