"""Drip / event triggers for the notifications app.

When a counsellor logs a follow-up with an outcome, fire the right
notifications per JD Lead-to-Admission Process PDF Step 8.
"""

from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


def _outcome_handlers(lead, fu):
    """Returns a list of (template_key, recipient, fire_at, cc) tuples."""
    from apps.leads.models import LeadFollowup
    out = fu.outcome_category
    now = timezone.now()
    student_email = lead.email or ""
    student_phone = lead.phone or ""
    plans = []

    if out == LeadFollowup.Outcome.HOT:
        # "Why join JD" + WhatsApp reminder for the next follow-up date.
        plans.append(("hot_why_join_jd", student_email, now, ""))
        if fu.next_followup_date:
            reminder = timezone.make_aware(
                timezone.datetime.combine(fu.next_followup_date,
                                          timezone.datetime.min.time())
            ) if not timezone.is_aware(
                timezone.datetime.combine(fu.next_followup_date,
                                          timezone.datetime.min.time())
            ) else timezone.datetime.combine(fu.next_followup_date,
                                             timezone.datetime.min.time())
            plans.append(("hot_followup_reminder", student_phone, reminder, ""))

        if fu.outcome_disposition == "Planning to visit the campus":
            plans.append(("campus_visit_confirmation", student_email, now, ""))
            if fu.next_followup_date:
                visit_dt = timezone.datetime.combine(
                    fu.next_followup_date, timezone.datetime.min.time(),
                )
                if not timezone.is_aware(visit_dt):
                    visit_dt = timezone.make_aware(visit_dt)
                plans.append(("campus_visit_reminder", student_phone,
                              visit_dt - timedelta(hours=24), ""))
                plans.append(("campus_visit_reminder", student_phone,
                              visit_dt - timedelta(hours=1), ""))
        elif fu.outcome_disposition == "Campus visit done":
            plans.append(("post_visit_thanks", student_email, now, ""))
            plans.append(("post_visit_thanks_wa", student_phone, now, ""))

    elif out == LeadFollowup.Outcome.NOT_ANSWERING:
        plans.append(("not_answered_followup", student_phone,
                      now + timedelta(minutes=10), ""))

    elif out == LeadFollowup.Outcome.COLD:
        # 30/60/90-day re-engagement drip.
        for days, key in ((30, "cold_drip_30"), (60, "cold_drip_60"),
                          (90, "cold_drip_90")):
            plans.append((key, student_email, now + timedelta(days=days), ""))

    elif out == LeadFollowup.Outcome.ENROLLED:
        plans.append(("enrolled_confirmation", student_email, now, ""))
        plans.append(("enrolled_confirmation_wa", student_phone, now, ""))

    return plans


@receiver(post_save, sender="leads.LeadFollowup")
def on_followup_saved(sender, instance, created, **kwargs):
    if not created or not instance.outcome_category:
        return
    from .services import queue_notification

    for tmpl, recipient, fire_at, cc in _outcome_handlers(instance.lead, instance):
        if not recipient:
            continue
        ctx = {
            "name": instance.lead.name,
            "phone": instance.lead.phone,
            "email": instance.lead.email,
            "program": instance.lead.program.name if instance.lead.program else "",
            "campus": instance.lead.campus.name if instance.lead.campus else "",
            "outcome": instance.outcome_category,
            "disposition": instance.outcome_disposition,
        }
        queue_notification(
            template_key=tmpl, recipient=recipient, cc=cc,
            context=ctx, fire_at=fire_at, related=instance.lead,
        )


@receiver(post_save, sender="leads.Lead")
def on_lead_created(sender, instance, created, **kwargs):
    """When a fresh lead lands, queue the welcome WA + brochure email."""
    if not created:
        return
    from .services import queue_notification
    ctx = {
        "name": instance.name, "email": instance.email, "phone": instance.phone,
        "program": instance.program.name if instance.program else "",
    }
    if instance.email:
        queue_notification(
            template_key="lead_welcome_email",
            recipient=instance.email, context=ctx, related=instance,
        )
    if instance.phone:
        queue_notification(
            template_key="lead_welcome_wa",
            recipient=instance.phone, context=ctx, related=instance,
        )
