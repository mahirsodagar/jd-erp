"""Resolve the Student associated with a request — either as themselves
or via their parent user account. Single source of truth for portal scoping."""

from dataclasses import dataclass

from apps.admissions.models import Enrollment, Student


@dataclass
class PortalContext:
    student: Student
    is_parent: bool
    enrollment: Enrollment | None  # current/active enrollment (most recent)


def resolve_portal_context(user) -> PortalContext | None:
    """Return PortalContext or None when the requesting user is not
    a student or a parent."""
    if not getattr(user, "is_authenticated", False):
        return None
    student = (Student.objects
               .filter(user_account=user)
               .select_related("institute", "campus", "academic_year",
                                "program")
               .first())
    is_parent = False
    if student is None:
        student = (Student.objects
                   .filter(parent_user_account=user)
                   .select_related("institute", "campus", "academic_year",
                                    "program")
                   .first())
        is_parent = student is not None
    if student is None:
        return None
    enrollment = (student.enrollments
                  .filter(status=Enrollment.Status.ACTIVE)
                  .select_related("batch", "semester", "course",
                                   "program", "academic_year")
                  .order_by("-created_on")
                  .first())
    if enrollment is None:
        # Fall back to most recent of any status
        enrollment = (student.enrollments
                      .select_related("batch", "semester", "course",
                                       "program", "academic_year")
                      .order_by("-created_on")
                      .first())
    return PortalContext(student=student, is_parent=is_parent,
                         enrollment=enrollment)
