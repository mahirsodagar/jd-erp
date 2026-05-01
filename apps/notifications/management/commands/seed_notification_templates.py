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
