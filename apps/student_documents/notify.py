"""In-app bell notifications for the document request flow (TC,
Bonafide, Study Certificate, Bank Letter, LOR, Other).

Request  → every active staff user who can decide document requests for
           the student's campus (holds student_documents.approve or
           student_documents.reject, and either student_documents.view_all
           or the student's campus on their login) — the same people who
           see the row on the staff Document Requests page.
Decision → the student's portal login (approved / rejected).

In-app only, on purpose (client, 2026-11-25) — same as the certificate
and appointment flows.
"""

from django.db.models import Q

from apps.accounts.models import User
from apps.accounts.permissions import has_perm
from apps.notifications.inapp import notify
from apps.notifications.models import InAppNotification

DECIDE_KEYS = ("student_documents.approve", "student_documents.reject")
ALL_CAMPUSES_KEY = "student_documents.view_all"
STAFF_LINK = "/student-documents"
PORTAL_LINK = "/portal/documents"


def _deciders_for(student):
    qs = (User.objects
          .filter(Q(roles__permissions__key__in=DECIDE_KEYS), is_active=True)
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


def notify_document_requested(req) -> int:
    student = req.student
    return notify(
        _deciders_for(student),
        kind=InAppNotification.Kind.OTHER,
        title=f"{req.doc_type_label} requested",
        body=(f"{student.student_name} ({student.application_form_id}) "
              f"has requested a {req.doc_type_label}."
              + (f" Purpose: {req.purpose}" if req.purpose else "")),
        link=STAFF_LINK,
    )


def notify_document_decision(req) -> int:
    student = req.student
    if req.status == req.Status.APPROVED:
        title = f"{req.doc_type_label} request approved"
        body = ("Your document is ready"
                + (" — download it from the portal." if req.attachment
                   else "; please collect it from the office."))
    else:
        title = f"{req.doc_type_label} request rejected"
        body = req.approver_remarks or "Please contact the office for details."
    return notify(
        [student.user_account],
        kind=InAppNotification.Kind.OTHER,
        title=title, body=body, link=PORTAL_LINK,
        exclude_user=req.decided_by,
    )
