"""In-app bell notifications for the certificate request flow.

Request  → every active staff user who can issue certificates for the
           student's campus (holds academics.certificate.issue, and
           either the *_all_campuses key or the campus on their login).
Decision → the student's portal login.

No email on purpose: the portal page shows the outcome, and the mail
transports are not reliable enough to block the flow on.
"""

from apps.accounts.models import User
from apps.accounts.permissions import has_perm
from apps.notifications.inapp import notify
from apps.notifications.models import InAppNotification

ISSUE_KEY = "academics.certificate.issue"
ALL_CAMPUSES_KEY = "academics.certificate.view_all_campuses"


def _issuers_for(student):
    qs = (User.objects
          .filter(is_active=True, roles__permissions__key=ISSUE_KEY)
          .prefetch_related("campuses")
          .distinct())
    out = []
    for u in qs:
        if has_perm(u, ALL_CAMPUSES_KEY):
            out.append(u)
            continue
        if student.campus_id and any(
                c.pk == student.campus_id for c in u.campuses.all()):
            out.append(u)
    return out


def notify_certificate_requested(cert, *, actor=None) -> int:
    student = cert.student
    return notify(
        _issuers_for(student),
        kind=InAppNotification.Kind.OTHER,
        title=f"{cert.get_type_display()} requested",
        body=(f"{student.student_name} ({student.application_form_id}) "
              f"has requested a {cert.get_type_display()}."
              + (f" Purpose: {cert.purpose}" if cert.purpose else "")),
        link="/certificates?status=REQUESTED",
        exclude_user=actor,
    )


def notify_certificate_decision(cert) -> int:
    student = cert.student
    if cert.status == cert.Status.ISSUED:
        title = f"{cert.get_type_display()} issued"
        body = (f"Certificate no. {cert.certificate_no} is ready to "
                f"download from the portal.")
    else:
        title = f"{cert.get_type_display()} request rejected"
        body = cert.remarks or "Please contact the office for details."
    return notify(
        [student.user_account],
        kind=InAppNotification.Kind.OTHER,
        title=title, body=body, link="/portal/certificates",
    )
