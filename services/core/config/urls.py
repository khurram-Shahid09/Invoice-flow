from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from audit.views import AuditLogListView
from common.views import healthz, readyz

api_v1: list[URLPattern | URLResolver] = [
    path("", include("accounts.urls")),
    path("audit", AuditLogListView.as_view(), name="audit-list"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
]

# Development only: uvicorn doesn't serve static files the way runserver does (admin CSS).
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
