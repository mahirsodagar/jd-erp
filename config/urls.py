from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.admissions.public_views import PublicApplicationView
from apps.leads.exam_views import (
    PublicExamStartView, PublicExamSubmitView, PublicExamView,
)
from apps.payments.views import (
    PayRedirectView, PayReturnView, SmartGatewayWebhookView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    # Public, no-auth student application form (tokenized).
    path("api/public/application/<uuid:token>/",
         PublicApplicationView.as_view(), name="public-application"),
    # Public, no-auth entrance exam (tokenized per-attempt link).
    path("api/public/exam/<uuid:token>/",
         PublicExamView.as_view(), name="public-exam"),
    path("api/public/exam/<uuid:token>/start/",
         PublicExamStartView.as_view(), name="public-exam-start"),
    path("api/public/exam/<uuid:token>/submit/",
         PublicExamSubmitView.as_view(), name="public-exam-submit"),
    # Public, no-auth pay link — what the fee SMS/email points at. Mints a
    # SmartGateway session on click and 302s to the hosted payment page,
    # so the URL in the student's SMS never goes stale.
    path("api/public/pay/<uuid:token>/",
         PayRedirectView.as_view(), name="public-pay"),
    # SmartGateway's return_url — where the payer's browser lands after.
    path("api/public/pay/<uuid:token>/return/",
         PayReturnView.as_view(), name="public-pay-return"),
    # SmartGateway webhook. No JWT — authenticated by the Basic
    # credentials configured in the SmartGateway dashboard.
    path("api/public/smartgateway/webhook/",
         SmartGatewayWebhookView.as_view(), name="smartgateway-webhook"),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.roles.urls")),
    path("api/audit/", include("apps.audit.urls")),
    path("api/master/", include("apps.master.urls")),
    path("api/leads/", include("apps.leads.urls")),
    path("api/employees/", include("apps.employees.urls")),
    path("api/leaves/", include("apps.leaves.urls")),
    path("api/admissions/", include("apps.admissions.urls")),
    path("api/fees/", include("apps.fees.urls")),
    path("api/academics/", include("apps.academics.urls")),
    path("api/audit-reports/", include("apps.audit_reports.urls")),
    path("api/hr/relieving/", include("apps.relieving.urls")),
    path("api/courseware/", include("apps.courseware.urls")),
    path("api/student-leaves/", include("apps.student_leaves.urls")),
    path("api/student-documents/", include("apps.student_documents.urls")),
    path("api/appointments/", include("apps.appointments.urls")),
    path("api/portal/", include("apps.portal.urls")),
    path("api/common/", include("apps.common.urls")),
    path("api/tasks/", include("apps.tasks.urls")),
    path("api/payments/", include("apps.payments.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
