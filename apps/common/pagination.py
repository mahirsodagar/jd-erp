"""Shared pagination class + APIView mixin.

DRF's APIView doesn't auto-paginate; only Generic/List views do. The
existing list endpoints all subclass APIView, so this mixin gives them
a tiny `paginate(qs, serializer_cls)` helper without a wholesale
rewrite.
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class PaginatedAPIViewMixin:
    """Drop-in helper. Usage:

        class MyView(PaginatedAPIViewMixin, APIView):
            def get(self, request):
                qs = Thing.objects.all()
                return self.paginate(qs, ThingSerializer)
    """

    pagination_class = StandardPagination

    def paginate(self, queryset, serializer_class, *,
                 serializer_context=None, **serializer_kwargs):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        ctx = serializer_context or {"request": self.request}
        if page is not None:
            data = serializer_class(page, many=True, context=ctx,
                                     **serializer_kwargs).data
            return paginator.get_paginated_response(data)
        data = serializer_class(queryset, many=True, context=ctx,
                                 **serializer_kwargs).data
        return Response(data)
