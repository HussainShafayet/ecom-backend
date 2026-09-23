from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.defaults import page_not_found, server_error
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from .errors import build_error_envelope
from .exceptions import ServiceUnavailable
from .responses import api_response


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.CharField()


class HealthView(APIView):
    """Readiness probe: the API is up and can reach PostgreSQL."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["health"], summary="Health check", responses=HealthSerializer, auth=[]
    )
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError as exc:
            raise ServiceUnavailable("Database is unavailable.") from exc
        return api_response({"status": "ok", "database": "ok"})


@extend_schema(exclude=True)
class ApiNotFoundView(APIView):
    """Catch-all mounted LAST under /api/v1/: unknown API paths get the JSON envelope in every mode.

    Django's `handler404` is ignored while DEBUG=True (the HTML debug page wins), so dev and prod
    would otherwise answer differently.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def _not_found(self, request, *args, **kwargs):
        raise NotFound()

    get = post = put = patch = delete = _not_found


def api_not_found(request, exception=None):
    """handler404: JSON envelope for /api/ paths, Django's normal page elsewhere (admin, ...)."""
    if request.path.startswith("/api/"):
        return JsonResponse(build_error_envelope("Not found."), status=404)
    return page_not_found(request, exception)


def api_server_error(request):
    """handler500: same idea for errors raised outside DRF (middleware, URL resolution)."""
    if request.path.startswith("/api/"):
        return JsonResponse(
            build_error_envelope("Internal server error.", ["Something went wrong on our side."]),
            status=500,
        )
    return server_error(request)
