"""Error reporting to Sentry, only when SENTRY_DSN_API is set (docs/12-security-privacy.md).

Nothing personal or sensitive leaves: no default PII, no request bodies (invoice
fields, bank details, uploads), no cookies or auth headers, no local variables.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentry_sdk.types import Event

SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-admin-token"}


def _scrub(event: "Event", hint: dict[str, Any]) -> "Event | None":
    request: dict[str, Any] = event.get("request") or {}
    request.pop("data", None)
    request.pop("cookies", None)
    headers = request.get("headers") or {}
    for key in list(headers):
        if key.lower() in SENSITIVE_HEADERS:
            headers[key] = "[removed]"
    return event


def init_sentry(dsn: str, environment: str, release: str = "") -> None:
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release or None,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,  # locals can hold invoice data and bank details
        traces_sample_rate=0.0,
        before_send=_scrub,
        integrations=[DjangoIntegration(), CeleryIntegration()],
    )
