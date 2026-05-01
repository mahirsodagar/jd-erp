from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import (
    Batch, Classroom, Subject, TimeSlot,
)
from apps.employees.models import Employee

from .attendance_service import (
    batch_attendance_summary, bulk_mark, freeze_attendance,
    notify_absent_students, roster_for, student_attendance_summary,
    unfreeze_attendance,
)
from .marks_service import (
    build_transcript, grade_submission, publish_marks,
    submission_status_after_save, unpublish_marks,
)
from .models import (
    Assignment, AssignmentSubmission, Attendance, MarksEntry, ScheduleSlot,
)
from .permissions import ScheduleAccess, has_perm
from .serializers import (
    AssignmentSerializer, AssignmentSubmissionSerializer,
    AttendanceSerializer, BulkMarkAttendanceSerializer,
    BulkWeeklyPublishSerializer, FreezeSerializer, MarksEntrySerializer,
    ScheduleSlotSerializer, StudentSubmitSerializer, SubmissionGradeSerializer,
)
from .services import bulk_publish_weekly, create_slot, detect_conflicts


def _scope(qs, user):
    """Campus-scope mutations / non-admin reads."""
    if user.is_superuser or has_perm(user, "academics.schedule.view_all"):
        return qs
    return qs.filter(batch__campus__in=user.campuses.all())


# --- Schedule slot CRUD -----------------------------------------------

class ScheduleSlotListCreateView(APIView):
    permission_classes = [IsAuthenticated, ScheduleAccess]

    def get(self, request):
        qs = ScheduleSlot.objects.select_related(
            "batch", "subject", "instructor", "classroom", "time_slot",
        )
        qs = _scope(qs, request.user)
        params = request.query_params
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := params.get("instructor"):
            qs = qs.filter(instructor_id=v)
        if v := params.get("classroom"):
            qs = qs.filter(classroom_id=v)
        if v := params.get("subject"):
            qs = qs.filter(subject_id=v)
        if v := params.get("status"):
            qs = qs.filter(status=v)
        if v := params.get("date"):
            if d := parse_date(v):
                qs = qs.filter(date=d)
        else:
            if v := params.get("from"):
                if d := parse_date(v):
                    qs = qs.filter(date__gte=d)
            if v := params.get("to"):
                if d := parse_date(v):
                    qs = qs.filter(date__lte=d)
        return Response(ScheduleSlotSerializer(qs[:1000], many=True).data)

    def post(self, request):
        s = ScheduleSlotSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        slot, report = create_slot(
            batch=d["batch"], subject=d["subject"],
            instructor=d["instructor"], classroom=d.get("classroom"),
            time_slot=d["time_slot"], date=d["date"],
            created_by=request.user,
            force=bool(request.data.get("force", False)),
            notes=d.get("notes", ""),
        )
        if not slot:
            code = (http.HTTP_409_CONFLICT
                    if report["errors"]
                    else http.HTTP_400_BAD_REQUEST)
            return Response(report, status=code)
        return Response(ScheduleSlotSerializer(slot).data,
                        status=http.HTTP_201_CREATED)


class ScheduleSlotDetailView(APIView):
    permission_classes = [IsAuthenticated, ScheduleAccess]

    def _obj(self, pk):
        try:
            return ScheduleSlot.objects.get(pk=pk)
        except ScheduleSlot.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        return Response(ScheduleSlotSerializer(self._obj(pk)).data)

    def patch(self, request, pk):
        slot = self._obj(pk)
        # Re-validate conflicts if a key field changes.
        force = bool(request.data.get("force", False))
        s = ScheduleSlotSerializer(slot, data=request.data, partial=True)
        s.is_valid(raise_exception=True)

        new_batch = s.validated_data.get("batch", slot.batch)
        new_subject = s.validated_data.get("subject", slot.subject)
        new_instr = s.validated_data.get("instructor", slot.instructor)
        new_room = s.validated_data.get("classroom", slot.classroom)
        new_ts = s.validated_data.get("time_slot", slot.time_slot)
        new_date = s.validated_data.get("date", slot.date)

        report = detect_conflicts(
            batch=new_batch, instructor=new_instr,
            classroom=new_room, time_slot=new_ts, date=new_date,
            exclude_id=slot.pk,
        )
        if report["errors"]:
            return Response(report, status=http.HTTP_409_CONFLICT)
        if report["warnings"] and not force:
            return Response(report, status=http.HTTP_400_BAD_REQUEST)

        slot.batch = new_batch
        slot.subject = new_subject
        slot.instructor = new_instr
        slot.classroom = new_room
        slot.time_slot = new_ts
        slot.date = new_date
        slot.notes = s.validated_data.get("notes", slot.notes)
        slot.classroom_conflict_overridden = bool(report["warnings"] and force)
        slot.save()
        return Response(ScheduleSlotSerializer(slot).data)

    def delete(self, request, pk):
        slot = self._obj(pk)
        slot.status = ScheduleSlot.Status.CANCELLED
        slot.save(update_fields=["status", "updated_at"])
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Bulk weekly publish ----------------------------------------------

class BulkWeeklyPublishView(APIView):
    permission_classes = [IsAuthenticated, ScheduleAccess]

    def post(self, request):
        if not has_perm(request.user, "academics.schedule.manage"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = BulkWeeklyPublishSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        # Resolve FK ids
        try:
            batch = Batch.objects.get(pk=d["batch"])
            subject = Subject.objects.get(pk=d["subject"])
            instructor = Employee.objects.get(pk=d["instructor"])
            time_slot = TimeSlot.objects.get(pk=d["time_slot"])
            classroom = (Classroom.objects.get(pk=d["classroom"])
                         if d.get("classroom") else None)
        except (Batch.DoesNotExist, Subject.DoesNotExist,
                Employee.DoesNotExist, TimeSlot.DoesNotExist,
                Classroom.DoesNotExist) as e:
            return Response({"detail": f"Master id not found: {e}"},
                            status=http.HTTP_400_BAD_REQUEST)

        result = bulk_publish_weekly(
            start_date=d["start_date"], end_date=d["end_date"],
            weekday=d["weekday"], batch=batch, subject=subject,
            instructor=instructor, classroom=classroom,
            time_slot=time_slot, created_by=request.user,
            force=d.get("force", False),
        )
        return Response(result, status=http.HTTP_201_CREATED)


# --- "My timetable" --------------------------------------------------

class MyTimetableView(APIView):
    """Returns scheduled slots for the requesting user.

    - If the user is linked to an Employee → returns slots where that
      Employee is the instructor.
    - If the user is linked to a Student → returns slots for any of
      that student's active enrollment batches.
    - Otherwise returns an empty list.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        params = request.query_params
        from_date = parse_date(params.get("from") or "")
        to_date = parse_date(params.get("to") or "")

        qs = ScheduleSlot.objects.select_related(
            "batch", "subject", "instructor", "classroom", "time_slot",
        ).filter(status=ScheduleSlot.Status.SCHEDULED)
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)

        # Instructor view
        emp = getattr(u, "employee", None)
        if emp is not None:
            qs = qs.filter(instructor=emp)
            return Response(ScheduleSlotSerializer(qs, many=True).data)

        # Student view
        student = getattr(u, "student", None)
        if student is not None:
            batch_ids = list(student.enrollments.values_list("batch_id", flat=True))
            qs = qs.filter(batch_id__in=batch_ids)
            return Response(ScheduleSlotSerializer(qs, many=True).data)

        return Response([])


# --- Conflict-check (dry-run) ----------------------------------------

class ConflictCheckView(APIView):
    """Dry-run check — returns what would happen if a slot was created
    with the given fields. Useful for the HOD UI to give live feedback
    before submitting."""
    permission_classes = [IsAuthenticated, ScheduleAccess]

    def post(self, request):
        try:
            batch = Batch.objects.get(pk=request.data.get("batch"))
            instructor = Employee.objects.get(pk=request.data.get("instructor"))
            time_slot = TimeSlot.objects.get(pk=request.data.get("time_slot"))
        except (Batch.DoesNotExist, Employee.DoesNotExist,
                TimeSlot.DoesNotExist) as e:
            return Response({"detail": f"Master id not found: {e}"},
                            status=http.HTTP_400_BAD_REQUEST)
        classroom_id = request.data.get("classroom")
        classroom = (Classroom.objects.filter(pk=classroom_id).first()
                     if classroom_id else None)
        date = parse_date(request.data.get("date") or "")
        if not date:
            return Response({"date": "Required."}, status=http.HTTP_400_BAD_REQUEST)

        report = detect_conflicts(
            batch=batch, instructor=instructor,
            classroom=classroom, time_slot=time_slot, date=date,
        )
        return Response(report)


# === G.2 — Attendance ================================================

def _can_mark_attendance(user, slot: ScheduleSlot) -> bool:
    """Instructor of the slot can mark; otherwise need the perm."""
    if user.is_superuser:
        return True
    emp = getattr(user, "employee", None)
    if emp is not None and slot.instructor_id == emp.id:
        return True
    return has_perm(user, "academics.attendance.mark")


class AttendanceRosterView(APIView):
    """`GET` — returns the slot's roster + each student's current
    attendance row (or null). `POST` — bulk mark.

    Per-method auth: GET open to any auth user; POST checks
    `_can_mark_attendance` (instructor-of-slot or perm holder)."""
    permission_classes = [IsAuthenticated]

    def _slot(self, pk):
        try:
            return ScheduleSlot.objects.select_related(
                "batch", "subject", "time_slot",
            ).get(pk=pk)
        except ScheduleSlot.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        slot = self._slot(pk)
        existing = {
            a.student_id: a
            for a in Attendance.objects.filter(schedule_slot=slot)
        }
        rows = []
        for enr in roster_for(slot):
            s = enr.student
            a = existing.get(s.id)
            rows.append({
                "student_id": s.id,
                "application_form_id": s.application_form_id,
                "name": s.student_name,
                "status": a.status if a else None,
                "note": a.note if a else "",
                "attendance_id": a.id if a else None,
            })
        return Response({
            "schedule_slot_id": slot.id,
            "date": str(slot.date),
            "subject": slot.subject.name,
            "batch": slot.batch.name,
            "frozen": slot.attendance_frozen,
            "frozen_at": slot.attendance_frozen_at,
            "frozen_by": (slot.attendance_frozen_by.username
                          if slot.attendance_frozen_by_id else None),
            "roster": rows,
        })

    def post(self, request, pk):
        slot = self._slot(pk)

        if not _can_mark_attendance(request.user, slot):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        if slot.attendance_frozen and not has_perm(
            request.user, "academics.attendance.edit_frozen"
        ):
            return Response(
                {"detail": "Attendance is frozen for this slot. "
                           "Unfreeze first or use an admin with "
                           "academics.attendance.edit_frozen."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        s = BulkMarkAttendanceSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        result = bulk_mark(
            slot=slot, marks=s.validated_data["marks"],
            marked_by=request.user,
        )

        notified = 0
        if s.validated_data.get("notify_absent"):
            notified = notify_absent_students(slot)

        return Response({**result, "notified_absent": notified},
                        status=http.HTTP_200_OK)


class AttendanceFreezeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            slot = ScheduleSlot.objects.get(pk=pk)
        except ScheduleSlot.DoesNotExist as e:
            raise Http404 from e
        # Same access rule as marking — instructor or perm holder.
        if not (_can_mark_attendance(request.user, slot)
                or has_perm(request.user, "academics.attendance.freeze")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if slot.attendance_frozen:
            return Response({"detail": "Already frozen."},
                            status=http.HTTP_400_BAD_REQUEST)
        freeze_attendance(slot=slot, by_user=request.user)
        return Response({"frozen": True})


class AttendanceUnfreezeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            slot = ScheduleSlot.objects.get(pk=pk)
        except ScheduleSlot.DoesNotExist as e:
            raise Http404 from e
        # Unfreeze is admin-only.
        if not has_perm(request.user, "academics.attendance.freeze"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if not slot.attendance_frozen:
            return Response({"detail": "Not frozen."},
                            status=http.HTTP_400_BAD_REQUEST)
        unfreeze_attendance(slot=slot, by_user=request.user)
        return Response({"frozen": False})


# --- Reports ----------------------------------------------------------

class BatchAttendanceReportView(APIView):
    permission_classes = [IsAuthenticated, ScheduleAccess]

    def get(self, request, pk):
        try:
            batch = Batch.objects.get(pk=pk)
        except Batch.DoesNotExist as e:
            raise Http404 from e
        if not (request.user.is_superuser
                or has_perm(request.user, "academics.attendance.view_report")
                or request.user.campuses.filter(pk=batch.campus_id).exists()):
            raise Http404
        params = request.query_params
        from_date = parse_date(params.get("from") or "") or None
        to_date = parse_date(params.get("to") or "") or None
        rows = batch_attendance_summary(
            batch=batch, from_date=from_date, to_date=to_date,
        )
        return Response({
            "batch_id": batch.id,
            "batch_name": batch.name,
            "from": str(from_date) if from_date else None,
            "to": str(to_date) if to_date else None,
            "rows": rows,
        })


class StudentAttendanceReportView(APIView):
    permission_classes = [IsAuthenticated, ScheduleAccess]

    def get(self, request, pk):
        from apps.admissions.models import Student
        try:
            student = Student.objects.get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        # Self, superuser, or HR with the explicit view_report perm.
        # Campus assignment alone is NOT enough — otherwise classmates
        # could see each other.
        u = request.user
        is_self = (student.user_account_id == u.id)
        if not (u.is_superuser or is_self
                or has_perm(u, "academics.attendance.view_report")):
            raise Http404

        params = request.query_params
        from_date = parse_date(params.get("from") or "") or None
        to_date = parse_date(params.get("to") or "") or None
        return Response(student_attendance_summary(
            student=student, from_date=from_date, to_date=to_date,
        ))


class MyAttendanceView(APIView):
    """Logged-in student fetches their own attendance summary."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = getattr(request.user, "student", None)
        if student is None:
            return Response(
                {"detail": "No student record linked to this user."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        params = request.query_params
        from_date = parse_date(params.get("from") or "") or None
        to_date = parse_date(params.get("to") or "") or None
        return Response(student_attendance_summary(
            student=student, from_date=from_date, to_date=to_date,
        ))


# === G.3 — Assignments + Marks ======================================

def _is_assignment_owner(user, assignment) -> bool:
    """A faculty 'owns' an assignment they created. Used to gate
    grade/edit. Superusers and `academics.assignment.manage_any` bypass."""
    if user.is_superuser:
        return True
    return assignment.created_by_id == user.id


# --- Assignment CRUD --------------------------------------------------

class AssignmentListCreateView(APIView):
    """Faculty side: list + create assignments. Students use
    `/api/academics/assignments/me/`."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = Assignment.objects.select_related("subject", "batch")
        params = request.query_params
        if v := params.get("subject"):
            qs = qs.filter(subject_id=v)
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := params.get("due_after"):
            if d := parse_date(v):
                qs = qs.filter(due_date__date__gte=d)
        if v := params.get("due_before"):
            if d := parse_date(v):
                qs = qs.filter(due_date__date__lte=d)

        # Campus scope: non-admins only see assignments for batches in
        # their campus(es).
        if not (u.is_superuser or has_perm(u, "academics.schedule.view_all")):
            qs = qs.filter(batch__campus__in=u.campuses.all())
        return Response(AssignmentSerializer(qs[:500], many=True).data)

    def post(self, request):
        if not has_perm(request.user, "academics.assignment.create"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = AssignmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class AssignmentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return Assignment.objects.select_related("subject", "batch").get(pk=pk)
        except Assignment.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        return Response(AssignmentSerializer(self._obj(pk)).data)

    def patch(self, request, pk):
        a = self._obj(pk)
        if not (_is_assignment_owner(request.user, a)
                or has_perm(request.user, "academics.assignment.manage_any")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = AssignmentSerializer(a, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        a = self._obj(pk)
        if not (_is_assignment_owner(request.user, a)
                or has_perm(request.user, "academics.assignment.manage_any")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        a.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class AssignmentSubmissionsView(APIView):
    """Faculty: list all submissions for an assignment."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            a = Assignment.objects.get(pk=pk)
        except Assignment.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        if not (u.is_superuser or _is_assignment_owner(u, a)
                or has_perm(u, "academics.assignment.grade")):
            raise Http404
        qs = a.submissions.select_related("student", "graded_by").all()
        return Response(AssignmentSubmissionSerializer(qs, many=True).data)


# --- Submission grading -----------------------------------------------

class SubmissionGradeView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            sub = AssignmentSubmission.objects.select_related(
                "assignment", "student",
            ).get(pk=pk)
        except AssignmentSubmission.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        if not (u.is_superuser
                or _is_assignment_owner(u, sub.assignment)
                or has_perm(u, "academics.assignment.grade")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = SubmissionGradeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            grade_submission(
                submission=sub,
                grade=s.validated_data["grade"],
                feedback=s.validated_data.get("feedback", ""),
                graded_by=u,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=http.HTTP_400_BAD_REQUEST)
        return Response(AssignmentSubmissionSerializer(sub).data)


# --- Student-facing assignment endpoints -----------------------------

class MyAssignmentsView(APIView):
    """List assignments visible to the logged-in student (own batches),
    each annotated with their submission status."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = getattr(request.user, "student", None)
        if student is None:
            return Response(
                {"detail": "No student record linked to this user."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        from apps.admissions.models import Enrollment
        batch_ids = list(
            Enrollment.objects.filter(
                student=student, status=Enrollment.Status.ACTIVE,
            ).values_list("batch_id", flat=True)
        )
        qs = Assignment.objects.filter(
            batch_id__in=batch_ids, is_published=True,
        ).select_related("subject", "batch").order_by("due_date")

        existing = {
            s.assignment_id: s
            for s in AssignmentSubmission.objects.filter(
                student=student, assignment__in=qs,
            )
        }
        rows = []
        for a in qs:
            sub = existing.get(a.id)
            rows.append({
                "assignment": AssignmentSerializer(a).data,
                "submission": (AssignmentSubmissionSerializer(sub).data
                                if sub else None),
            })
        return Response(rows)


class StudentSubmitView(APIView):
    """Student uploads / replaces their submission for an assignment."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        student = getattr(request.user, "student", None)
        if student is None:
            return Response(
                {"detail": "No student record linked to this user."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        try:
            a = Assignment.objects.get(pk=pk, is_published=True)
        except Assignment.DoesNotExist as e:
            raise Http404 from e

        # Roster check.
        from apps.admissions.models import Enrollment
        if not Enrollment.objects.filter(
            student=student, batch=a.batch, status=Enrollment.Status.ACTIVE,
        ).exists():
            return Response({"detail": "Not enrolled in this batch."},
                            status=http.HTTP_403_FORBIDDEN)

        s = StudentSubmitSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        sub, _ = AssignmentSubmission.objects.get_or_create(
            assignment=a, student=student,
        )
        if "file" in s.validated_data and s.validated_data["file"] is not None:
            sub.file = s.validated_data["file"]
        if "text_response" in s.validated_data:
            sub.text_response = s.validated_data["text_response"]
        sub.submitted_at = timezone.now()
        sub.status = submission_status_after_save(sub)
        sub.save()
        return Response(AssignmentSubmissionSerializer(sub).data,
                        status=http.HTTP_200_OK)


# --- Marks -----------------------------------------------------------

class MarksListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not (u.is_superuser
                or has_perm(u, "academics.marks.enter")
                or has_perm(u, "academics.marks.publish")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = MarksEntry.objects.select_related(
            "student", "subject", "batch", "semester",
        )
        params = request.query_params
        if v := params.get("student"):
            qs = qs.filter(student_id=v)
        if v := params.get("subject"):
            qs = qs.filter(subject_id=v)
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := params.get("semester"):
            qs = qs.filter(semester_id=v)
        if params.get("published") == "1":
            qs = qs.filter(published=True)
        elif params.get("published") == "0":
            qs = qs.filter(published=False)
        return Response(MarksEntrySerializer(qs[:1000], many=True).data)

    def post(self, request):
        u = request.user
        if not has_perm(u, "academics.marks.enter"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = MarksEntrySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            obj = s.save(entered_by=u)
        except Exception as e:
            return Response({"detail": str(e)}, status=http.HTTP_400_BAD_REQUEST)
        return Response(MarksEntrySerializer(obj).data,
                        status=http.HTTP_201_CREATED)


class MarksDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return MarksEntry.objects.get(pk=pk)
        except MarksEntry.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        u = request.user
        if not (u.is_superuser or has_perm(u, "academics.marks.enter")
                or has_perm(u, "academics.marks.publish")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(MarksEntrySerializer(self._obj(pk)).data)

    def patch(self, request, pk):
        u = request.user
        m = self._obj(pk)
        if m.published:
            if not has_perm(u, "academics.marks.edit_published"):
                return Response(
                    {"detail": "Marks are published; "
                               "academics.marks.edit_published required."},
                    status=http.HTTP_400_BAD_REQUEST,
                )
        elif not has_perm(u, "academics.marks.enter"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = MarksEntrySerializer(m, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class MarksPublishView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not has_perm(u, "academics.marks.publish"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            m = MarksEntry.objects.get(pk=pk)
        except MarksEntry.DoesNotExist as e:
            raise Http404 from e
        if m.published:
            return Response({"detail": "Already published."},
                            status=http.HTTP_400_BAD_REQUEST)
        publish_marks(marks=m, by_user=u)
        return Response(MarksEntrySerializer(m).data)


class MarksUnpublishView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not has_perm(u, "academics.marks.publish"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            m = MarksEntry.objects.get(pk=pk)
        except MarksEntry.DoesNotExist as e:
            raise Http404 from e
        if not m.published:
            return Response({"detail": "Not published."},
                            status=http.HTTP_400_BAD_REQUEST)
        unpublish_marks(marks=m, by_user=u)
        return Response(MarksEntrySerializer(m).data)


# --- Transcript -------------------------------------------------------

class StudentTranscriptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from apps.admissions.models import Student
        try:
            student = Student.objects.get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        is_self = (student.user_account_id == u.id)
        if not (u.is_superuser or is_self
                or has_perm(u, "academics.transcript.view_any")):
            raise Http404
        only_published = not (u.is_superuser
                              or has_perm(u, "academics.transcript.view_drafts"))
        return Response(build_transcript(
            student=student, only_published=only_published,
        ))


class MyTranscriptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = getattr(request.user, "student", None)
        if student is None:
            return Response(
                {"detail": "No student record linked to this user."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        return Response(build_transcript(student=student, only_published=True))
