from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics
from rest_framework.exceptions import ValidationError

from apps.core.responses import api_response

from .models import Address
from .serializers import AddressSerializer


class OwnAddressesMixin:
    serializer_class = AddressSerializer
    pagination_class = None  # the frontend expects a plain array

    def get_queryset(self):
        # Other people's addresses simply don't exist for this user (404, not 403).
        return Address.objects.filter(user=self.request.user)


@extend_schema_view(
    get=extend_schema(tags=["addresses"], summary="List my saved addresses (plain array)"),
    post=extend_schema(tags=["addresses"], summary="Save a new address"),
)
class AddressListCreateView(OwnAddressesMixin, generics.ListCreateAPIView):
    def perform_create(self, serializer):
        User = get_user_model()
        with transaction.atomic():
            User.objects.select_for_update().get(pk=self.request.user.pk)  # serialise concurrent adds
            if Address.objects.filter(user=self.request.user).count() >= settings.MAX_ADDRESSES_PER_USER:
                raise ValidationError(
                    f"You can save at most {settings.MAX_ADDRESSES_PER_USER} addresses. "
                    "Delete one to add another."
                )
            serializer.save(user=self.request.user)


@extend_schema_view(
    get=extend_schema(tags=["addresses"], summary="Get one of my addresses"),
    put=extend_schema(
        tags=["addresses"],
        summary="Update an address (partial; read-only keys such as `id` are ignored)",
    ),
    patch=extend_schema(exclude=True),
    delete=extend_schema(
        tags=["addresses"],
        summary="Delete an address",
        responses={200: OpenApiResponse(description="Deleted.")},
    ),
)
class AddressDetailView(OwnAddressesMixin, generics.RetrieveUpdateDestroyAPIView):
    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True  # the frontend PUTs the whole edited object; be lenient either way
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return api_response(None, message="Address deleted.")
