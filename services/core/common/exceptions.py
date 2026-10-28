"""Uniform API errors: ``{"error": {"code", "message", "details"}}`` (docs/11-api-spec.md)."""

from typing import Any

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class ApiError(exceptions.APIException):
    """Raise with a stable machine-readable ``code``, e.g. ``ApiError("invoice_not_found", ...)``."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail=message, code=code)
        self.status_code = status_code
        self.error_code = code
        self.details = details or {}


def _code_for(exc: exceptions.APIException) -> str:
    if isinstance(exc, ApiError):
        return exc.error_code
    if isinstance(exc, exceptions.ValidationError):
        return "validation_error"
    # A specific code given at raise time, e.g. PermissionDenied(..., code="owner_required").
    return str(getattr(exc.detail, "code", None) or exc.default_code)


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    response = exception_handler(exc, context)
    if response is None or not isinstance(exc, exceptions.APIException):
        return response  # unhandled -> 500 via Django (and Sentry)

    if isinstance(exc, ApiError):
        message, details = str(exc.detail), exc.details
    elif isinstance(exc, exceptions.ValidationError):
        message, details = "Request validation failed.", {"fields": response.data}
    else:
        detail = response.data.get("detail", "") if isinstance(response.data, dict) else ""
        message, details = str(detail) or str(exc), {}

    response.data = {"error": {"code": _code_for(exc), "message": message, "details": details}}
    return response
