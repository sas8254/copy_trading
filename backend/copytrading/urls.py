from django.urls import path

from .api import OverviewView, ResolveAlertView

urlpatterns = [
    path("overview/", OverviewView.as_view(), name="ct-overview"),
    path("alerts/<int:pk>/resolve/", ResolveAlertView.as_view(), name="ct-resolve-alert"),
]
