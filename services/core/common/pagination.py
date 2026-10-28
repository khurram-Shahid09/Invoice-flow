from rest_framework.pagination import CursorPagination as BaseCursorPagination


class CursorPagination(BaseCursorPagination):
    """``?cursor=&limit=`` newest first (docs/11-api-spec.md conventions)."""

    ordering = ("-created_at", "-id")  # id breaks ties between rows written in the same instant
    page_size = 50
    page_size_query_param = "limit"
    max_page_size = 200
