from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.queries import visible_products, with_list_fields
from apps.catalog.serializers import ProductListSerializer
from apps.core.responses import api_response

from . import services
from .serializers import ProductRefSerializer

TAGS = ["wishlist"]
MAX_REMOVE_ITEMS = 500


class FavouriteView(APIView):
    """The signed-in customer's saved products. The default permission (IsAuthenticated) applies."""

    @extend_schema(
        tags=TAGS,
        summary="My favourites: a plain array of product cards, newest first",
        responses=ProductListSerializer(many=True),
    )
    def get(self, request):
        ids = services.saved_product_ids(request.user)
        products = {p.pk: p for p in with_list_fields(visible_products().filter(pk__in=ids))}
        ordered = [products[pk] for pk in ids if pk in products]
        context = {"request": request, "favourite_ids": frozenset(products)}  # every one of them is a favourite
        return Response(ProductListSerializer(ordered, many=True, context=context).data)

    @extend_schema(
        tags=TAGS,
        summary="Save a product (saving it twice is fine)",
        request=ProductRefSerializer,
        responses={200: OpenApiResponse(description="Saved.")},
    )
    def post(self, request):
        serializer = ProductRefSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_favourite(request.user, serializer.validated_data["product_id"])
        return api_response(None, message="Added to your favourites.")

    @extend_schema(
        tags=TAGS,
        summary="Remove products from my favourites (one `{product_id}` or an array of them)",
        request=ProductRefSerializer(many=True),
        responses={200: OpenApiResponse(description="Removed.")},
    )
    def put(self, request):
        data = request.data
        many = isinstance(data, list)
        if many and len(data) > MAX_REMOVE_ITEMS:
            raise ValidationError(f"Send at most {MAX_REMOVE_ITEMS} products at a time.")
        serializer = ProductRefSerializer(data=data, many=many)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data if many else [serializer.validated_data]
        services.remove_favourites(request.user, [item["product_id"] for item in items])
        return api_response(None, message="Removed from your favourites.")
