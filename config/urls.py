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
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
