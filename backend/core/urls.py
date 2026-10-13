from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from accounts.views import HealthView

# Zerodha redirects here if a Kite app's Redirect URL points at the backend
# (e.g. the old http://localhost:8000/). Forward to the website's callback page,
# keeping ?request_token=...&account=... so it can finish the login.
kite_callback = RedirectView.as_view(
    url=f"{settings.FRONTEND_URL}/kite/callback", query_string=True
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/auth/", include("accounts.urls")),
    path("api/copytrading/", include("copytrading.urls")),
    path("kite/callback/", kite_callback),
    path("", kite_callback),
]
