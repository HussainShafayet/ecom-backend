from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.responses import api_response

from . import services
from .serializers import (
    ContactMessageSerializer,
    FaqPayloadSerializer,
    NewsletterSerializer,
    StaticPagePayloadSerializer,
    SitePayloadSerializer,
)

TAGS = ["site"]


class PublicView(APIView):
    """Everything here is public. Who is asking does not matter, so a stale token can not turn a call into a 401."""

    authentication_classes = []
    permission_classes = [AllowAny]


@extend_schema(tags=TAGS, summary="The shop's name, logo, contact details, social links, announcement and footer pages", responses=SitePayloadSerializer, auth=[])
class SiteView(PublicView):
    """The storefront reads this once when it opens: the header, the footer and the contact page draw from it."""

    def get(self, request):
        return Response({"site": services.site_payload(request)})


@extend_schema(tags=TAGS, summary="One page an admin wrote (About us, Privacy policy, ...)", responses=StaticPagePayloadSerializer, auth=[])
class StaticPageView(PublicView):
    def get(self, request, slug):
        page = services.published_page(slug)
        if page is None:
            raise NotFound("There is no such page.")
        return Response({"page": page})


@extend_schema(tags=TAGS, summary="The frequently asked questions", responses=FaqPayloadSerializer, auth=[])
class FaqView(PublicView):
    def get(self, request):
        return Response({"faqs": services.faq_items()})


class ContactView(PublicView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "contact"

    @extend_schema(
        tags=TAGS,
        summary="Send the shop a message (guests too)",
        description="Stored for the staff to read in the admin. Rate limited per client IP.",
        request=ContactMessageSerializer,
        responses={201: None},
        auth=[],
    )
    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return api_response(None, message="Thank you. We have your message and will get back to you soon.", status=201)


class NewsletterView(PublicView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "newsletter"

    @extend_schema(
        tags=TAGS,
        summary="Subscribe an e-mail address to the newsletter (guests too)",
        description="Always answers 200 with the same message, whether the address was new or already on the list. "
        "Rate limited per client IP.",
        request=NewsletterSerializer,
        responses={200: None},
        auth=[],
    )
    def post(self, request):
        serializer = NewsletterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.subscribe(serializer.validated_data["email"])
        return api_response(None, message="Thank you for subscribing.")
