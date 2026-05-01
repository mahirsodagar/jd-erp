from django.http import Http404
from django.utils.dateparse import parse_date
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import (
    Batch, Classroom, Subject, TimeSlot,
)
from apps.employees.models import Employee

from .models import ScheduleSlot
from .permissions import ScheduleAccess, has_perm
from .serializers import BulkWeeklyPublishSerializer, ScheduleSlotSerializer
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
