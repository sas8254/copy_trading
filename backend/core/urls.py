from django.contrib import admin
from django.urls import include, path

from accounts.views import HealthView
from copytrading.views import DashboardView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/auth/", include("accounts.urls")),
    path("api/copytrading/", include("copytrading.urls")),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
]
