from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.pagination import EnvelopePageNumberPagination
from apps.core.responses import api_response

from . import services
from .serializers import (
    CheckoutContentSerializer,
    OrderDetailSerializer,
    OrderPlacedSerializer,
    OrderSummarySerializer,
    OrderTrackingQuerySerializer,
    OrderTrackingSerializer,
    PlaceOrderSerializer,
)

TAGS = ["orders"]


def signed_in_user(request):
    """The customer behind a valid Bearer token, else None. A bad or expired token never gets here: the default JWT
    authentication answers 401 first, so the frontend refreshes it like everywhere else."""
    return request.user if request.user.is_authenticated else None


def serialize_orders(serializer_class, orders, request, many=False):
    """The order serializers need the products' pictures and the payments: fetched once for the whole page."""
    context = {"request": request, **services.order_extras(orders if many else [orders])}
    return serializer_class(orders, many=many, context=context).data


class OrderListCreateView(APIView):
    """`POST`: public, guests check out too (a valid Bearer token attaches the order to that customer).
    `GET`: the signed-in customer's own orders."""

    throttle_classes = [ScopedRateThrottle]  # for POST, scope "order"
    throttle_scope = "order"

    def get_permissions(self):
        return [AllowAny() if self.request.method == "POST" else IsAuthenticated()]

    def get_throttles(self):
        if self.request.method in SAFE_METHODS:  # reading is only held to the generous limits every view has
            return [throttle() for throttle in api_settings.DEFAULT_THROTTLE_CLASSES]
        return super().get_throttles()

    @extend_schema(
        tags=TAGS,
        operation_id="orders_list",
        summary="My orders, newest first",
        description="Only the signed-in customer's own orders (a guest order belongs to nobody). Paginated like the "
        "product lists (`?page=&page_size=`).",
        responses=inline_serializer(
            "OrderPage",
            {
                "count": serializers.IntegerField(),
                "next": serializers.URLField(allow_null=True),
                "previous": serializers.URLField(allow_null=True),
                "results": OrderSummarySerializer(many=True),
            },
        ),
    )
    def get(self, request):
        paginator = EnvelopePageNumberPagination()
        page = paginator.paginate_queryset(services.customer_orders(request.user), request, view=self)
        return paginator.get_paginated_response(serialize_orders(OrderSummarySerializer, page, request, many=True))

    @extend_schema(
        tags=TAGS,
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
        placed = {
            "order_id": order.number,
            "status": order.status,
            "created_at": order.created_at,
            "subtotal": order.subtotal,
            "delivery_charge": order.delivery_charge,
            "total": order.total,
        }
        return api_response(OrderPlacedSerializer(placed).data, message="Order placed.", status=201)


class OrderDetailView(APIView):
    """One of the customer's own orders. The default permission (IsAuthenticated) applies."""

    @extend_schema(
        tags=TAGS,
        summary="One of my orders: items, address, totals, payment and status history",
        description="Somebody else's order, a guest order and an unknown number are all a 404.",
        responses=OrderDetailSerializer,
    )
    def get(self, request, number):
        order = services.customer_order(request.user, number)
        return Response(serialize_orders(OrderDetailSerializer, order, request))


class OrderCancelView(APIView):
    """The customer cancels their own pending order."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "order"

    @extend_schema(
        tags=TAGS,
        summary="Cancel my order (only while it is pending)",
        description="The goods go back into stock and the payment is cancelled. An order that is already paid, "
        "shipped, delivered, cancelled or refunded is a 400: a person has to handle it. Answers with the order.",
        request=None,
        responses=OrderDetailSerializer,
    )
    def post(self, request, number):
        order = services.cancel_order(request.user, number)
        return api_response(serialize_orders(OrderDetailSerializer, order, request), message="Order cancelled.")


class OrderTrackingView(APIView):
    """Public: a guest follows an order with its number and the phone number it was placed with."""

    authentication_classes = []  # who is asking does not matter, so a stale token can not turn this into a 401
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "order_track"

    @extend_schema(
        tags=TAGS,
        summary="Track an order by its number and phone number (guests too)",
        description="Progress and contents only: not the name, address, phone or e-mail. A wrong number or phone is "
        "the same 404 (`No order matches these details.`). Rate limited per client IP, misses count too.",
        parameters=[
            OpenApiParameter("order_id", str, required=True, description="e.g. GC-20260923-0001 (any case)."),
            OpenApiParameter("phone_number", str, required=True, description="+880 and 10 digits, as at checkout."),
        ],
        responses=OrderTrackingSerializer,
        auth=[],
    )
    def get(self, request):
        query = OrderTrackingQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        order = services.tracked_order(query.validated_data["order_id"], query.validated_data["phone_number"])
        return Response(serialize_orders(OrderTrackingSerializer, order, request))


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
