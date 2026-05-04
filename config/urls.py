from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
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
    path("api/portal/", include("apps.portal.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
