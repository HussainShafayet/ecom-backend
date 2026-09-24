from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.catalog.queries import visible_products
from apps.core.pagination import EnvelopePageNumberPagination
from apps.core.responses import api_response

from . import services
from .serializers import EditReviewSerializer, ReviewQuerySerializer, ReviewSerializer, WriteReviewSerializer

TAGS = ["reviews"]
MULTIPART = "multipart/form-data"


class ReviewPagination(EnvelopePageNumberPagination):
    """The usual `count/next/previous/results`, plus `can_review` for the signed-in customer."""

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["can_review"] = self.can_review
        return response


class ReviewListCreateView(APIView):
    # Reading is public (a valid Bearer token only fills in `can_review` and `can_edited`); writing needs a
    # signed-in customer, throttled per customer.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "review"

    def get_permissions(self):
        return [AllowAny() if self.request.method in SAFE_METHODS else IsAuthenticated()]

    def get_throttles(self):
        if self.request.method in SAFE_METHODS:  # reading is only held to the generous limits every view has
            return [throttle() for throttle in api_settings.DEFAULT_THROTTLE_CLASSES]
        return super().get_throttles()

    @extend_schema(
        tags=TAGS,
        summary="Reviews of a product, newest first, and whether the signed-in customer may write one",
        parameters=[OpenApiParameter("product_id", int, required=True)],
        responses=inline_serializer(
            "ReviewPage",
            {
                "count": serializers.IntegerField(),
                "next": serializers.URLField(allow_null=True),
                "previous": serializers.URLField(allow_null=True),
                "results": ReviewSerializer(many=True),
                "can_review": serializers.BooleanField(
                    help_text="A delivered order of theirs contains the product and they have not reviewed it yet."
                ),
            },
        ),
    )
    def get(self, request):
        query = ReviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        product_id = query.validated_data["product_id"]
        if not visible_products().filter(pk=product_id).exists():
            raise NotFound("Product not found.")

        paginator = ReviewPagination()
        page = paginator.paginate_queryset(services.shown_reviews(product_id), request, view=self)
        paginator.can_review = services.can_review(request.user, product_id)
        return paginator.get_paginated_response(ReviewSerializer(page, many=True, context={"request": request}).data)

    @extend_schema(
        tags=TAGS,
        summary="Write a review of a product you received (multipart)",
        description=(
            "Needs a delivered order of the customer that contains the product; one review per product. Up to "
            "`MAX_REVIEW_FILES` (5) photos or videos in repeated `media` parts."
        ),
        request={MULTIPART: WriteReviewSerializer},
        responses={201: ReviewSerializer},
    )
    def post(self, request):
        serializer = WriteReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        review = services.create_review(
            request.user, data["product_id"], data["rating"], data["comment"], data.get("media", ())
        )
        review = services.shown_reviews(review.product_id).get(pk=review.pk)  # with its user and media
        return api_response(
            ReviewSerializer(review, context={"request": request}).data, message="Review added.", status=201
        )


class ReviewDetailView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "review"

    @extend_schema(
        tags=TAGS,
        summary="Edit your review: rating, comment, and more media (multipart)",
        description=(
            "Every field is optional. Files are ADDED to the review's media (5 in all); text values under `media` "
            "(the frontend re-sends the existing ones as `[object Object]`) are ignored. Someone else's review, or a "
            "hidden one, is a 404."
        ),
        request={MULTIPART: EditReviewSerializer},
        responses={200: ReviewSerializer},
    )
    def put(self, request, pk):
        serializer = EditReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        changes = {field: data[field] for field in ("rating", "comment") if field in data}
        review = services.update_review(
            request.user, pk, changes, data.get("media", ()), product_id=data.get("product_id")
        )
        review = services.shown_reviews(review.product_id).get(pk=review.pk)
        return api_response(ReviewSerializer(review, context={"request": request}).data, message="Review updated.")
