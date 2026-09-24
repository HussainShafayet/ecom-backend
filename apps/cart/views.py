from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.favourites import favourite_product_ids
from apps.core.responses import api_response

from . import services
from .serializers import CartAddSerializer, CartItemSerializer, CartRefSerializer, cart_items

TAGS = ["cart"]
MAX_REMOVE_ITEMS = 200


class CartView(APIView):
    """The signed-in customer's cart. The default permission (IsAuthenticated) applies."""

    @extend_schema(
        tags=TAGS,
        summary="My cart: a plain array, one entry per line (`id` is the product id)",
        responses=CartItemSerializer(many=True),
    )
    def get(self, request):
        items = cart_items(services.cart_lines(request.user))
        context = {
            "request": request,
            "favourite_ids": favourite_product_ids(request.user, [item.pk for item in items]),
        }
        return Response(CartItemSerializer(items, many=True, context=context).data)

    @extend_schema(
        tags=TAGS,
        summary="Add to or take from a line. `quantity` is a delta; taking it to 0 removes the line",
        request=CartAddSerializer,
        responses={200: OpenApiResponse(description="Done.")},
    )
    def post(self, request):
        serializer = CartAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        change = services.add_to_cart if data["action"] == "increase" else services.decrease_in_cart
        change(request.user, data["product_id"], data["quantity"], data.get("variant_id"))
        return api_response(None, message="Your cart was updated.")

    @extend_schema(
        tags=TAGS,
        summary="Remove lines: one `{product_id, variant_id?}` or an array of them",
        description="Without `variant_id`, every line of that product is removed. What is not in the cart is ignored.",
        request=CartRefSerializer(many=True),
        responses={200: OpenApiResponse(description="Removed.")},
    )
    def put(self, request):
        data = request.data
        many = isinstance(data, list)
        if many and len(data) > MAX_REMOVE_ITEMS:
            raise ValidationError(f"Send at most {MAX_REMOVE_ITEMS} items at a time.")
        serializer = CartRefSerializer(data=data, many=many)
        serializer.is_valid(raise_exception=True)
        refs = serializer.validated_data if many else [serializer.validated_data]
        services.remove_from_cart(request.user, [(ref["product_id"], ref.get("variant_id")) for ref in refs])
        return api_response(None, message="Removed from your cart.")
