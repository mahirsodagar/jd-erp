"""Dashboard campus cards + the batch-wise drill-down behind them.

Ports the PHP dashboard's campus strip (`dashboard.php` → the
`campus_master` loop) and the modal it opened (`includes/get.php`,
`bscampusid` branch). The PHP version showed one card per campus the
user could reach, each with the campus image and a headcount, and the
modal broke that headcount down by batch.

Two rules the PHP had implicitly and this makes explicit:

* the strip is scoped to the caller's campuses unless they hold
  ``dashboard.campuses.view_all_campuses`` — the PHP equivalent of
  "own campus + assigned campuses";
* asking for a campus outside that scope is a 403, not an empty table,
  so the drill-down can't be used to probe headcounts by URL.

Counts are active enrolments (``Enrollment.Status.ACTIVE``) in the
academic year flagged ``is_current``, counted over distinct students —
the modern equivalent of the PHP's ``acad_year=25 and
student_master.active_status=0``. With no current year configured,
every count is 0 rather than an error, so the cards still render.
"""

from django.db.models import Count
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import has_perm
from apps.admissions.models import Enrollment

from .models import AcademicYear, Campus


def _allowed_campus_ids(user):
    """Campus ids the caller may see, or None for institute-wide.

    Same shape as `academics.batch_report_views._allowed_campus_ids`.
    """
    if has_perm(user, "dashboard.campuses.view_all_campuses"):
        return None
    return list(user.campuses.values_list("pk", flat=True))


def _current_year():
    return AcademicYear.objects.filter(is_current=True).first()


def _deny():
    return Response(
        {"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN,
    )


class CampusCardsView(APIView):
    """GET /api/master/dashboard/campuses/

    One row per visible campus: identity, image and the active-student
    headcount for the current academic year.
    """

    permission_classes = [IsAuthenticated]
    required_perm = "dashboard.campuses.view"

    def get(self, request):
        user = request.user
        if not has_perm(user, self.required_perm):
            return _deny()

        allowed = _allowed_campus_ids(user)
        campuses = Campus.objects.filter(is_active=True)
        if allowed is not None:
            campuses = campuses.filter(pk__in=allowed)

        year = _current_year()
        counts = {}
        if year:
            rows = (
                Enrollment.objects
                .filter(status=Enrollment.Status.ACTIVE, academic_year=year,
                        campus__in=campuses)
                .values("campus_id")
                .annotate(total=Count("student_id", distinct=True))
            )
            counts = {r["campus_id"]: r["total"] for r in rows}

        return Response({
            "academic_year": year.code if year else None,
            "academic_year_name": (year.full_name or year.code) if year else "",
            "campuses": [
                {
                    "id": c.pk,
                    "name": c.name,
                    "code": c.code,
                    "city": c.city,
                    "image_url": (
                        request.build_absolute_uri(c.image.url)
                        if c.image else None
                    ),
                    "student_count": counts.get(c.pk, 0),
                }
                for c in campuses
            ],
        })


class CampusBatchesView(APIView):
    """GET /api/master/dashboard/campuses/<pk>/batches/

    The batch-wise breakdown behind a card: academic year, batch name
    and headcount, matching the PHP modal's three columns (plus the
    program and batch id, which the SPA links on).
    """

    permission_classes = [IsAuthenticated]
    required_perm = "dashboard.campuses.view"

    def get(self, request, pk):
        user = request.user
        if not has_perm(user, self.required_perm):
            return _deny()

        campus = Campus.objects.filter(pk=pk).first()
        if campus is None:
            return Response(
                {"detail": "Campus not found."}, status=http.HTTP_404_NOT_FOUND,
            )

        allowed = _allowed_campus_ids(user)
        if allowed is not None and campus.pk not in allowed:
            return _deny()

        year = _current_year()
        batches = []
        if year:
            rows = (
                Enrollment.objects
                .filter(status=Enrollment.Status.ACTIVE, academic_year=year,
                        campus=campus)
                .values(
                    "batch_id", "batch__name", "batch__program__name",
                    "academic_year__code",
                )
                .annotate(total=Count("student_id", distinct=True))
                .order_by("batch__name")
            )
            batches = [
                {
                    "batch_id": r["batch_id"],
                    "batch_name": r["batch__name"],
                    "program_name": r["batch__program__name"] or "",
                    "academic_year": r["academic_year__code"],
                    "student_count": r["total"],
                }
                for r in rows
            ]

        return Response({
            "campus": {
                "id": campus.pk,
                "name": campus.name,
                "code": campus.code,
                "city": campus.city,
                "image_url": (
                    request.build_absolute_uri(campus.image.url)
                    if campus.image else None
                ),
            },
            "academic_year": year.code if year else None,
            "academic_year_name": (year.full_name or year.code) if year else "",
            "student_count": sum(b["student_count"] for b in batches),
            "batches": batches,
        })
