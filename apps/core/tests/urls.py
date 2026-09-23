"""Throw-away URLconf that exercises the envelope pipeline (use with @pytest.mark.urls)."""
from django.urls import path
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.core.pagination import EnvelopePageNumberPagination
from apps.core.responses import api_response
from apps.core.urls import dual_path

handler404 = "apps.core.views.api_not_found"
handler500 = "apps.core.views.api_server_error"


class ProtectedView(APIView):  # default permission = IsAuthenticated
    def get(self, request):
        return api_response({"secret": 1})


class PayloadSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    quantity = serializers.IntegerField(min_value=1)


class ValidationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return api_response({"id": 1}, message="Order placed", status=201)


class PlainView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return api_response([1, 2, 3])


class BoomView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        raise RuntimeError("secret internal detail")


class NumbersView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        paginator = EnvelopePageNumberPagination()
        page = paginator.paginate_queryset(list(range(1, 46)), request)
        return paginator.get_paginated_response(page)


urlpatterns = [
    path("api/v1/_t/protected/", ProtectedView.as_view()),
    path("api/v1/_t/validate/", ValidationView.as_view()),
    path("api/v1/_t/plain/", PlainView.as_view()),
    path("api/v1/_t/boom/", BoomView.as_view()),
    path("api/v1/_t/numbers/", NumbersView.as_view()),
    *dual_path("api/v1/_t/dual/", PlainView.as_view(), name="dual"),
]
