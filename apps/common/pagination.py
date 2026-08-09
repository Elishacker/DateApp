"""Pagination classes with a consistent response envelope."""
from collections import OrderedDict

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("success", True),
                    ("count", self.page.paginator.count),
                    ("pages", self.page.paginator.num_pages),
                    ("page", self.page.number),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )


class MessageCursorPagination(CursorPagination):
    """Chat history is append-heavy; cursors avoid skipped/duplicated rows."""

    page_size = 40
    max_page_size = 100
    page_size_query_param = "page_size"
    ordering = "-created_at"


class CompactPagination(StandardPagination):
    page_size = 10
    max_page_size = 50
