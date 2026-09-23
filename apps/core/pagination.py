from collections import OrderedDict

from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param


class EnvelopePageNumberPagination(PageNumberPagination):
    """`?page=&page_size=` pagination. The renderer wraps the result as `data`:

        {"success": true, "message": "OK", "data": {"count", "next", "previous", "results": [...]}}

    The UI offers page sizes 30/60/90/120. A page past the end returns an empty `results` list (200)
    instead of DRF's 404, so infinite-scroll clients that ask for one page too many don't error out.
    """

    page_size = 30
    page_size_query_param = "page_size"
    max_page_size = 120

    def paginate_queryset(self, queryset, request, view=None):
        self._past_end = False
        try:
            return super().paginate_queryset(queryset, request, view)
        except NotFound:
            paginator = self.django_paginator_class(queryset, self.get_page_size(request))
            raw_page = str(request.query_params.get(self.page_query_param, ""))
            if raw_page.isdigit() and int(raw_page) > paginator.num_pages:
                self._past_end = True
                self._count = paginator.count
                self._last_page = paginator.num_pages
                return []
            raise

    def get_paginated_response(self, data):
        if self._past_end:
            previous = replace_query_param(
                self.request.build_absolute_uri(), self.page_query_param, self._last_page
            )
            return Response(
                OrderedDict(count=self._count, next=None, previous=previous, results=[])
            )
        return Response(
            OrderedDict(
                count=self.page.paginator.count,
                next=self.get_next_link(),
                previous=self.get_previous_link(),
                results=data,
            )
        )
