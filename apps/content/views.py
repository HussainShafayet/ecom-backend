from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Page
from .serializers import PagePayloadSerializer
from .services import page_content


@extend_schema(
    tags=["content"],
    summary="The sliders and banners of one page",
    parameters=[OpenApiParameter("page", OpenApiTypes.STR, OpenApiParameter.PATH, enum=list(Page.values))],
    responses=PagePayloadSerializer,
)
class PageContentView(APIView):
    """Public. A page nobody has filled in yet answers with empty lists and null banners (200), never an error."""

    permission_classes = [AllowAny]

    def get(self, request, page):
        if page not in Page.values:
            raise NotFound("There is no such page.")
        return Response({"page_content": page_content(page, request)})
