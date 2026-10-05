from drf_spectacular.utils import extend_schema
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.responses import api_response
from apps.orders import services as order_services
from apps.orders.serializers import OrderDetailSerializer
from apps.orders.views import serialize_orders

from . import services
from .serializers import ReturnRequestInputSerializer

TAGS = ["orders"]


def my_order(user, number):
    """The customer's order as `GET /orders/{order_id}/` shows it, now with the new state of its `returns`."""
    return order_services.customer_order(user, number)


class OrderReturnCreateView(APIView):
    """The signed-in customer asks to return some lines of their own delivered order. The default permission applies."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "order"

    @extend_schema(
        tags=TAGS,
        summary="Ask to return items of a delivered order",
        description="Only the customer's own order, only once it is delivered and while the shop's return period (Admin > "
        "Returns > Return settings, 7 days by default, counted from the delivery) is open. `items` are lines of the order "
        "(`items[].id`) with the number of units to send back; units that an earlier request still holds are not free. Every "
        "problem comes back together as a 400 with `errors: [sentence, ...]`, and nothing is written. Answers with the order, "
        "whose `returns` block now lists the request. The shop pays the money back by hand once it has the goods.",
        request=ReturnRequestInputSerializer,
        responses={201: OrderDetailSerializer},
    )
    def post(self, request, number):
        serializer = ReturnRequestInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_return(request.user, number, serializer.validated_data)
        return api_response(
            serialize_orders(OrderDetailSerializer, my_order(request.user, number), request), message="Return requested.", status=201
        )


class OrderReturnCancelView(APIView):
    """The customer calls off their own return request."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "order"

    @extend_schema(
        tags=TAGS,
        summary="Cancel my return request (only until the shop has answered it)",
        description="A request that was already approved, rejected, completed or cancelled is a 400: please contact the shop. "
        "Answers with the order.",
        request=None,
        responses=OrderDetailSerializer,
    )
    def post(self, request, number, request_id):
        services.cancel_request(request.user, number, request_id)
        return api_response(
            serialize_orders(OrderDetailSerializer, my_order(request.user, number), request), message="Return request cancelled."
        )
