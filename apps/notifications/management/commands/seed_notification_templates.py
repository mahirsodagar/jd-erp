from django.core.management.base import BaseCommand

from apps.notifications.models import NotificationTemplate as T


TEMPLATES = [
    ("lead_welcome_email", "EMAIL",
     "Welcome to JD Institute, {name}!",
     "Hi {name},\n\nThanks for your interest in {program}. "
     "Our brochure is attached.\n\n— Team JD"),
    ("lead_welcome_wa", "WHATSAPP", "",
     "Hi {name}, thanks for enquiring about {program}. "
     "We will call you shortly. — Team JD"),

    ("hot_why_join_jd", "EMAIL",
     "Why JD is right for you, {name}",
     "Hi {name},\n\nHere is why hundreds of students choose JD..."),
    ("hot_followup_reminder", "WHATSAPP", "",
     "Reminder: follow up with {name} ({phone}) for {program}."),
    ("campus_visit_confirmation", "EMAIL",
     "Your campus visit is confirmed",
     "Hi {name}, looking forward to meeting you at our {campus} campus."),
    ("campus_visit_reminder", "WHATSAPP", "",
     "Reminder: your visit to {campus} campus is coming up."),
    ("post_visit_thanks", "EMAIL",
     "Thanks for visiting JD",
     "Hi {name}, thanks for visiting our {campus} campus today."),
    ("post_visit_thanks_wa", "WHATSAPP", "",
     "Thanks for visiting JD {campus} today, {name}!"),

    ("not_answered_followup", "WHATSAPP", "",
     "Hi {name}, sorry we missed your call. We will try again soon."),
    ("not_answered_closing_soon", "EMAIL",
     "Admissions for {program} closing soon",
     "Hi {name}, last few seats left in {program}. Reply to this mail to confirm."),

    ("cold_drip_30", "EMAIL", "Still considering {program}?",
     "Hi {name}, our team is here when you are ready to talk."),
    ("cold_drip_60", "EMAIL", "A 30% scholarship for {program}?",
     "Hi {name}, fresh scholarships have been announced for {program}."),
    ("cold_drip_90", "EMAIL", "Final call for {program}",
     "Hi {name}, this is our last note for now. Reply if you would like us to keep in touch."),

    ("enrolled_confirmation", "EMAIL",
     "Welcome aboard {name} — your admission is confirmed",
     "Hi {name},\n\nYour enrollment in {program} at {campus} is confirmed."),
    ("enrolled_confirmation_wa", "WHATSAPP", "",
     "Welcome to JD {campus}, {name}! Your admission is confirmed."),

    ("manager_overdue_hot_lead", "EMAIL",
     "Overdue hot lead: {name}",
     "{name} ({phone}) has been hot for over 24h with no contact. "
     "Last counsellor: {counsellor}."),
    ("manager_overdue_hot_lead_in_crm", "IN_CRM",
     "Overdue hot lead",
     "{name} ({phone}) — over 24h no contact."),

    # G.2 — Attendance absentee notifications
    ("student_absent_email", "EMAIL",
     "Absence recorded — {subject} on {date}",
     "Hi {name},\n\nYou were marked absent for {subject} ({slot}) "
     "on {date}, batch {batch} ({campus}).\n\nIf this is a mistake "
     "please contact your batch mentor."),
    ("student_absent_wa", "WHATSAPP", "",
     "Hi {name}, you were marked absent for {subject} on {date}."),
    ("parent_absent_email", "EMAIL",
     "Absence recorded for {name} — {date}",
     "Dear Parent,\n\nYour ward {name} was marked absent for "
     "{subject} ({slot}) on {date}, at our {campus} campus.\n\n"
     "Please contact the batch mentor if this is unexpected."),

    # Lead → student conversion: application + fee link send-out
    # (keys use dot-namespacing — different convention to the older
    # snake_case keys above. Source of truth = the callers in
    # apps/leads/send_links.py.)
    ("lead.application_link.sms", "SMS", "",
     "Dear{name}, Thank you for selecting JD, Your inquiry has been submitted. Please click the link to complete your application - {url}"),
    ("lead.application_link.email", "EMAIL",
     "JD Student Application Link : {name}",
     "Greetings from JD!\nDear {name},\n\n"
     "Thank you for selecting JD, Your inquiry has been submitted.\n\n"
     "Please click the link to complete your application - {url}\n\n"
     "With Regards,\nJD"),
    # WhatsApp leg of the application-link send. XIRCLS stores the approved
    # body on their side (trigger "application_form"); this body_template
    # is only used for the dispatch-log audit row. Variables: {name}, {url}.
    ("lead.application_link.wa", "WHATSAPP", "",
     "Dear {name}, Thank you for selecting JD. Your inquiry has been "
     "submitted. Please click the link to complete your application - {url}"),
    # Verbatim DLT-approved wording — must match what was registered
    # with BulkSMS (template_id 1307168958796572350) or the SMS won't
    # leave the gateway. Variables: {short_name}, {url}.
    ("lead.fee_link.sms", "SMS", "",
     "Dear student, Greetings of the day! Thank you for choosing "
     "{short_name} for your Design/Art/Media course. Click the "
     "following link {url} to pay your fees and complete the "
     "admission process. Best Regards JD Admissions Team"),
    # WhatsApp leg of the fee-link send. XIRCLS stores the approved body
    # on their side; this body_template is only the dispatch-log audit
    # row. Variables: {name}, {url}. Dormant until its XIRCLS trigger is
    # set in settings.XIRCLS_WA_TRIGGERS["lead.fee_link.wa"].
    ("lead.fee_link.wa", "WHATSAPP", "",
     "Dear {name}, Thank you for choosing JD. Click the link {url} to pay "
     "your fees and complete the admission process. — JD Admissions Team"),
    ("lead.fee_link.email", "EMAIL",
     "{institute} — Application fee payment link",
     "Dear {name},\n\n"
     "Thank you for choosing {institute} for your Design/Art/Media "
     "course.\n\n"
     "Click the link below to pay your fees and complete the "
     "admission process:\n\n{url}\n\n"
     "Best Regards,\nJD Admissions Team"),
    ("lead.welcome.email", "EMAIL",
     "Welcome Note for New Students and Parents",
     "Dear {name},\n\n"
     "Thank you for choosing JD as the place to pursue further "
     "education! We are happy to welcome you onboard.\n\n"
     "Our endeavours have always been to provide our students with a "
     "cohesive learning environment that encompasses practical and "
     "theoretical education.\n\n"
     "For any clarifications or queries you can reach out to your "
     "administrative office.\n\n"
     "See you very soon!\n\nRegards,\nJD"),

    # Admin-issued password reset (Admin → Users → Reset password).
    # Goes through MSG91 when MSG91_EMAIL_TEMPLATES has the matching
    # key registered — otherwise falls back to plain SMTP. Variables:
    # {name}, {username}, {password}, {login_url}.
    ("account.password_reset_by_admin.email", "EMAIL",
     "Your JD ERP password has been reset",
     "Hi {name},\n\n"
     "An administrator has reset your JD ERP password.\n\n"
     "You can log in using the credentials below:\n\n"
     "  Username : {username}\n"
     "  Password : {password}\n\n"
     "Please change your password after logging in.\n\n"
     "Sign in at: {login_url}\n\n"
     "If you didn't expect this, contact the admin team.\n\n"
     "— JD Admissions"),

    # Student portal credentials (Student Detail → Reset & send creds).
    # Same routing pattern as the admin reset above. Variables:
    # {name}, {email}, {username}, {password}, {institute}, {login_url}.
    ("student.portal_credentials.email", "EMAIL",
     "Your student portal login",
     "Hi {name},\n\n"
     "Welcome to {institute}. Your student portal account is ready.\n\n"
     "You can log in using the credentials below:\n\n"
     "  Login email : {email}\n"
     "  Username    : {username}\n"
     "  Password    : {password}\n\n"
     "Please change your password after the first login.\n\n"
     "Sign in at: {login_url}\n\n"
     "If you didn't request this, contact your admissions office.\n\n"
     "— JD Admissions"),

    # ------------------------------------------------------------------
    # SMS templates — bodies match DLT-approved wording exactly (any
    # drift causes BulkSMS / MSG91 to garble or reject the send).
    # MSG91 stores its own copy of the body — the body_template here is
    # used (a) for SMTP/BulkSMS dispatch and (b) for the audit row.
    # ------------------------------------------------------------------

    # Attendance — student/parent (legacy DLT variants from PHP project)
    ("attendance.student_absent.sms", "SMS", "",
     "Dear {name}, You have been marked absent for {date} for module "
     "{subject}. Regards JD Admissions Team"),
    ("attendance.parent_absent.sms", "SMS", "",
     "Dear Parent, Please be informed {name}, of {batch} is absent on "
     "{date}. Regards JD Admissions Team"),

    # Attendance v2 — newer DLT variants ("JD Academic Team" footer)
    ("attendance.student_absent_v2.sms", "SMS", "",
     "Dear {name} You have been marked absent for {date} for module "
     "{subject}. Regards, JD Academic Team"),
    ("attendance.parent_absent_v2.sms", "SMS", "",
     "Dear Parent Please be informed {name}, of batch {batch} is "
     "ABSENT ON {date}, Regards, JD Academic Team"),

    # Fees — installment due (student + parent)
    ("fees.installment_due_student.sms", "SMS", "",
     "Dear {name},{registration_no}, {installment} Installment of INR "
     "{amount}, for the course {course}, is due on {due_date}. Request "
     "you to kindly make the payment on time. Kindly ignore if the "
     "payment is made. Regards JD Accounts Department"),
    ("fees.installment_due_parent.sms", "SMS", "",
     "Dear Parent, {installment} Installment of INR {amount} of your "
     "ward, {ward_name} {registration_no} for the course {course}, is "
     "due on {due_date}. Request you to kindly make the payment on "
     "time. Kindly ignore if the payment is made. Regards JD Accounts "
     "Department"),

    # Fees — installment paid (student + parent)
    ("fees.installment_paid_student.sms", "SMS", "",
     "Dear {name},{registration_no}, Thank you for the payment of INR "
     "{amount} towards your {installment} installment. Regards JD "
     "Accounts Department"),
    ("fees.installment_paid_parent.sms", "SMS", "",
     "Dear Parent, Thank you for the payment of INR {amount} towards "
     "the {installment} installment, of your ward {ward_name},"
     "{registration_no}, for the course {course}. Regards JD Accounts "
     "Department"),

    # Fees — bulk reminder (no variables; static body)
    ("fees.bulk_reminder.sms", "SMS", "",
     "Dear Parents and Students, The installment payment is due. "
     "Kindly clear the same on or before the due date to avoid late "
     "payment charges. For queries, please contact the office. Thank "
     "you. JD"),
]


class Command(BaseCommand):
    help = "Seed notification templates. Idempotent."

    def handle(self, *args, **opts):
        for key, channel, subj, body in TEMPLATES:
            T.objects.update_or_create(
                key=key,
                defaults={
                    "channel": channel,
                    "subject_template": subj,
                    "body_template": body,
                },
            )
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(TEMPLATES)} notification templates."
        ))
