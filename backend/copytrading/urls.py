from django.urls import path
from rest_framework.routers import SimpleRouter

from . import api

router = SimpleRouter()
router.register("accounts", api.AccountViewSet, basename="ct-account")

urlpatterns = [
    path("overview/", api.OverviewView.as_view(), name="ct-overview"),
    path("positions/", api.PositionsView.as_view(), name="ct-positions"),
    path("orders/", api.OrdersView.as_view(), name="ct-orders"),
    path("settings/", api.SettingsView.as_view(), name="ct-settings"),
    path("settings/test-email/", api.TestEmailView.as_view(), name="ct-test-email"),
    path("alerts/", api.AlertListView.as_view(), name="ct-alerts"),
    path("alerts/resolve-all/", api.ResolveAllAlertsView.as_view(), name="ct-resolve-all"),
    path("alerts/<int:pk>/resolve/", api.ResolveAlertView.as_view(), name="ct-resolve-alert"),
    *router.urls,
]
