from django.urls import path

from .consumers import DashboardConsumer, EchoConsumer

websocket_urlpatterns = [
    path("ws/dashboard/", DashboardConsumer.as_asgi()),
    path("ws/echo/", EchoConsumer.as_asgi()),
]
