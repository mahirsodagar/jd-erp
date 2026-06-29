"""Entrance-exam endpoints.

Staff endpoints (authenticated, permission-gated) mirror the academics
Test views (apps/academics/views.py:1270-1697). Candidate endpoints are
public (no auth) and resolve an attempt by its `access_token`, mirroring
apps/admissions/public_views.py.
"""

from django.http import Http404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.permissions import has_perm

from .exam_models import (
    EntranceExam, EntranceExamAttempt, EntranceExamQuestion,
    EntranceExamResponse,
)
from .exam_serializers import (
    EntranceExamAttemptSerializer, EntranceExamQuestionPublicSerializer,
    EntranceExamQuestionSerializer, EntranceExamResponseSerializer,
    EntranceExamSerializer, MapExamSerializer, ReviewResponseSerializer,
    SubmitAttemptSerializer,
)
from .exam_service import (
    can_attempt_now, exam_report, map_exam_to_leads, recompute_total_marks,
    review_response, submit_attempt,
)


def _is_exam_owner(user, exam) -> bool:
    if user.is_superuser:
        return True
    return exam.created_by_id == user.id


# --- Exam CRUD --------------------------------------------------------

class ExamListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = EntranceExam.objects.select_related("program", "academic_year")
        if not (u.is_superuser or has_perm(u, "leads.exam.view_all")):
            qs = qs.filter(created_by=u)
        params = request.query_params
        if v := params.get("program"):
            qs = qs.filter(program_id=v)
        if v := params.get("status"):
            qs = qs.filter(status=v)
        return Response(EntranceExamSerializer(qs[:500], many=True).data)

    def post(self, request):
        if not has_perm(request.user, "leads.exam.create"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = EntranceExamSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class ExamDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return EntranceExam.objects.select_related("program").get(pk=pk)
        except EntranceExam.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        return Response(EntranceExamSerializer(self._obj(pk)).data)

    def patch(self, request, pk):
        exam = self._obj(pk)
        if not (_is_exam_owner(request.user, exam)
                or has_perm(request.user, "leads.exam.manage_any")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if exam.status != EntranceExam.Status.DRAFT:
            return Response(
                {"detail": "Only DRAFT exams can be edited."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        s = EntranceExamSerializer(exam, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        exam = self._obj(pk)
        if not (_is_exam_owner(request.user, exam)
                or has_perm(request.user, "leads.exam.manage_any")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if exam.attempts.exists():
            return Response(
                {"detail": "Exam has attempts; close it instead of deleting."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        exam.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Status transitions -----------------------------------------------

class ExamPublishView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            exam = EntranceExam.objects.get(pk=pk)
        except EntranceExam.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        if not (_is_exam_owner(u, exam) or has_perm(u, "leads.exam.publish")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if exam.status != EntranceExam.Status.DRAFT:
            return Response({"detail": f"Status is {exam.status}, expected DRAFT."},
                            status=http.HTTP_400_BAD_REQUEST)
        if exam.questions.count() == 0:
            return Response({"detail": "Add at least one question first."},
                            status=http.HTTP_400_BAD_REQUEST)
        recompute_total_marks(exam)
        exam.status = EntranceExam.Status.PUBLISHED
        exam.save(update_fields=["status", "updated_at"])
        return Response(EntranceExamSerializer(exam).data)


class ExamCloseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            exam = EntranceExam.objects.get(pk=pk)
        except EntranceExam.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        if not (_is_exam_owner(u, exam) or has_perm(u, "leads.exam.publish")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if exam.status != EntranceExam.Status.PUBLISHED:
            return Response({"detail": f"Status is {exam.status}, expected PUBLISHED."},
                            status=http.HTTP_400_BAD_REQUEST)
        exam.status = EntranceExam.Status.CLOSED
        exam.save(update_fields=["status", "updated_at"])
        return Response(EntranceExamSerializer(exam).data)


# --- Question CRUD ----------------------------------------------------

class ExamQuestionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            exam = EntranceExam.objects.get(pk=pk)
        except EntranceExam.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        if not (_is_exam_owner(u, exam) or has_perm(u, "leads.exam.view_all")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = exam.questions.all()
        return Response(EntranceExamQuestionSerializer(qs, many=True).data)

    def post(self, request, pk):
        try:
            exam = EntranceExam.objects.get(pk=pk)
        except EntranceExam.DoesNotExist as e:
            raise Http404 from e
        if exam.status != EntranceExam.Status.DRAFT:
            return Response({"detail": "Only DRAFT exams can take new questions."},
                            status=http.HTTP_400_BAD_REQUEST)
        if not (_is_exam_owner(request.user, exam)
                or has_perm(request.user, "leads.exam.manage_any")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        data = {**request.data, "exam": exam.id}
        s = EntranceExamQuestionSerializer(data=data)
        s.is_valid(raise_exception=True)
        q = s.save()
        recompute_total_marks(exam)
        return Response(EntranceExamQuestionSerializer(q).data,
                        status=http.HTTP_201_CREATED)


class ExamQuestionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return EntranceExamQuestion.objects.select_related("exam").get(pk=pk)
        except EntranceExamQuestion.DoesNotExist as e:
            raise Http404 from e

    def patch(self, request, pk):
        q = self._obj(pk)
        if q.exam.status != EntranceExam.Status.DRAFT:
            return Response({"detail": "Only DRAFT exams can be edited."},
                            status=http.HTTP_400_BAD_REQUEST)
        if not (_is_exam_owner(request.user, q.exam)
                or has_perm(request.user, "leads.exam.manage_any")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = EntranceExamQuestionSerializer(q, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        recompute_total_marks(q.exam)
        return Response(s.data)

    def delete(self, request, pk):
        q = self._obj(pk)
        if q.exam.status != EntranceExam.Status.DRAFT:
            return Response({"detail": "Only DRAFT exams can be edited."},
                            status=http.HTTP_400_BAD_REQUEST)
        if not (_is_exam_owner(request.user, q.exam)
                or has_perm(request.user, "leads.exam.manage_any")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        exam = q.exam
        q.delete()
        recompute_total_marks(exam)
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Mapping + reports ------------------------------------------------

class ExamMapView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            exam = EntranceExam.objects.get(pk=pk)
        except EntranceExam.DoesNotExist as e:
            raise Http404 from e
        if not (_is_exam_owner(request.user, exam)
                or has_perm(request.user, "leads.exam.publish")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if exam.status != EntranceExam.Status.PUBLISHED:
            return Response({"detail": "Exam must be PUBLISHED to map."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = MapExamSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        result = map_exam_to_leads(
            exam=exam, lead_ids=d["lead_ids"],
            start_dt=d["start_dt"], end_dt=d["end_dt"],
        )
        return Response(result, status=http.HTTP_201_CREATED)


class ExamAttemptsListView(APIView):
    """Staff: see all attempts for an exam."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            exam = EntranceExam.objects.get(pk=pk)
        except EntranceExam.DoesNotExist as e:
            raise Http404 from e
        if not (_is_exam_owner(request.user, exam)
                or has_perm(request.user, "leads.exam.view_all")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = exam.attempts.select_related("lead").all()
        return Response(EntranceExamAttemptSerializer(qs, many=True).data)


class ExamReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            exam = EntranceExam.objects.get(pk=pk)
        except EntranceExam.DoesNotExist as e:
            raise Http404 from e
        if not (_is_exam_owner(request.user, exam)
                or has_perm(request.user, "leads.exam.view_all")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(exam_report(exam))


class LeadExamAttemptsView(APIView):
    """Attempts for a single lead — powers the lead-detail panel."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        qs = EntranceExamAttempt.objects.select_related(
            "exam", "lead",
        ).filter(lead_id=pk).order_by("-created_at")
        return Response(EntranceExamAttemptSerializer(qs, many=True).data)


# --- Staff attempt review --------------------------------------------

class ExamAttemptDetailView(APIView):
    """Staff view of one attempt: full questions + responses (for review)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            attempt = EntranceExamAttempt.objects.select_related(
                "exam", "lead",
            ).get(pk=pk)
        except EntranceExamAttempt.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        if not (_is_exam_owner(u, attempt.exam)
                or has_perm(u, "leads.exam.view_all")
                or has_perm(u, "leads.exam.review")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response({
            "attempt": EntranceExamAttemptSerializer(attempt).data,
            "questions": EntranceExamQuestionSerializer(
                attempt.exam.questions.all(), many=True,
            ).data,
            "responses": EntranceExamResponseSerializer(
                attempt.responses.all(), many=True,
            ).data,
        })


class ExamResponseReviewView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            r = EntranceExamResponse.objects.select_related(
                "attempt__exam", "question",
            ).get(pk=pk)
        except EntranceExamResponse.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        if not (u.is_superuser
                or _is_exam_owner(u, r.attempt.exam)
                or has_perm(u, "leads.exam.review")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = ReviewResponseSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            review_response(
                response=r,
                marks_awarded=s.validated_data["marks_awarded"],
                feedback=s.validated_data.get("feedback", ""),
                reviewed_by=u,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(EntranceExamResponseSerializer(r).data)


# --- Public candidate endpoints (no auth, by access_token) -----------

def _resolve_attempt(token):
    try:
        return EntranceExamAttempt.objects.select_related(
            "exam", "lead",
        ).get(access_token=token)
    except (EntranceExamAttempt.DoesNotExist, ValueError) as e:
        raise Http404("Invalid or expired exam link.") from e


class PublicExamView(APIView):
    """GET — exam meta + window state + questions (no answer_key) + saved
    responses, so the candidate can resume."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        attempt = _resolve_attempt(token)
        ok, reason = can_attempt_now(attempt)
        body = {
            "exam": {
                "name": attempt.exam.name,
                "instructions": attempt.exam.instructions,
                "duration_min": attempt.exam.duration_min,
                "total_marks": str(attempt.exam.total_marks),
            },
            "candidate_name": attempt.lead.name,
            "status": attempt.status,
            "start_dt": attempt.start_dt,
            "end_dt": attempt.end_dt,
            "started_at": attempt.started_at,
            "submitted_at": attempt.submitted_at,
            "total_score": (
                str(attempt.total_score)
                if attempt.total_score is not None else None
            ),
            "window_open": ok,
        }
        if not ok:
            body["window_reason"] = reason
            # Outside the window: only reveal questions once finalized.
            if attempt.status not in (
                EntranceExamAttempt.Status.SUBMITTED,
                EntranceExamAttempt.Status.GRADED,
            ):
                return Response(body)
        body["questions"] = EntranceExamQuestionPublicSerializer(
            attempt.exam.questions.all(), many=True,
        ).data
        body["responses"] = [
            {"question": r.question_id, "answer": r.answer}
            for r in attempt.responses.all()
        ]
        return Response(body)


class PublicExamStartView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, token):
        attempt = _resolve_attempt(token)
        ok, reason = can_attempt_now(attempt)
        if not ok:
            return Response({"detail": reason},
                            status=http.HTTP_400_BAD_REQUEST)
        if attempt.status == EntranceExamAttempt.Status.NOT_STARTED:
            attempt.started_at = timezone.now()
            attempt.status = EntranceExamAttempt.Status.IN_PROGRESS
            attempt.save(update_fields=["started_at", "status", "updated_at"])
        return Response({
            "status": attempt.status,
            "started_at": attempt.started_at,
            "end_dt": attempt.end_dt,
            "duration_min": attempt.exam.duration_min,
        })


class PublicExamSubmitView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, token):
        attempt = _resolve_attempt(token)
        ok, reason = can_attempt_now(attempt)
        if not ok:
            return Response({"detail": reason},
                            status=http.HTTP_400_BAD_REQUEST)
        s = SubmitAttemptSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if attempt.started_at is None:
            attempt.started_at = timezone.now()
            attempt.save(update_fields=["started_at"])
        result = submit_attempt(
            attempt=attempt, answers=s.validated_data["answers"],
        )
        return Response({"status": result["status"], **result})
