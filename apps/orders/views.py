from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.responses import api_response

from . import services
from .serializers import CheckoutContentSerializer, OrderPlacedSerializer, PlaceOrderSerializer


def signed_in_user(request):
    """The customer behind a valid Bearer token, else None. A bad or expired token never gets here: the default JWT
    authentication answers 401 first, so the frontend refreshes it like everywhere else."""
    return request.user if request.user.is_authenticated else None


class PlaceOrderView(APIView):
    """Public: guests check out too. A valid Bearer token attaches the order to that customer."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "order"

    @extend_schema(
        tags=["orders"],
        summary="Place an order (guest or signed in)",
        description=(
            "Prices and totals in the body are ignored: the server prices every line from the catalog and adds the "
            "configured delivery charge. Every problem (unknown or hidden product, stock, minimum order quantity, "
            "...) comes back together as a 400 with `errors: [sentence, ...]`, and nothing is written. "
            "A signed-in customer's ordered lines leave their server cart."
        ),
        request=PlaceOrderSerializer,
        responses={201: OrderPlacedSerializer},
    )
    def post(self, request):
        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.place_order(user=signed_in_user(request), data=serializer.validated_data)
        return api_response({"order_id": order.number}, message="Order placed.", status=201)


class CheckoutContentView(APIView):
    """Public (Bearer optional): what the checkout page needs before the customer fills in the form."""

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["content"],
        summary="Delivery charges, and for a signed-in customer their saved addresses and details",
        responses=CheckoutContentSerializer,
    )
    def get(self, request):
        return Response(CheckoutContentSerializer(services.checkout_content(signed_in_user(request))).data)
