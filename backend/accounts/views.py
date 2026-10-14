from django.contrib.auth import login
from knox.views import LoginView as KnoxLoginView
from rest_framework import generics, permissions
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .serializers import UserSerializer


class HealthView(APIView):
    """Public liveness check for uptime monitors: 503 if the copy engine
    (Celery worker + beat) hasn't run recently."""

    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        from copytrading.heartbeat import engine_alive, seconds_since_last_run

        age = seconds_since_last_run()
        alive = engine_alive()
        return Response(
            {
                "status": "ok" if alive else "engine_down",
                "engine_last_run_seconds_ago": None if age is None else round(age),
            },
            status=200 if alive else 503,
        )


class LoginView(KnoxLoginView):
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "login"

    def post(self, request, format=None):
        serializer = AuthTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        login(request, user)
        return super().post(request, format=None)


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
