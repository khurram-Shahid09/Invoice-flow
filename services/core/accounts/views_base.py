"""Org context for API views. See common/tenancy.py for the rules."""

from typing import Any, cast

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request

from common.exceptions import ApiError

from .models import ApiToken, Membership, Organization, User

ORG_HEADER = "HTTP_X_ORG_ID"


def resolve_membership(request: Request, path_org_id: str | None = None) -> Membership:
    """Which org this request acts in, and the caller's membership there.

    - PAT: the token's org (a ``X-Org-Id`` header or path org must match it).
    - JWT: the path org, else the ``X-Org-Id`` header, else the caller's oldest membership.
    An org the caller doesn't belong to is reported as not found, so ids can't be probed.
    """
    token = request.auth if isinstance(request.auth, ApiToken) else None
    wanted = path_org_id or request.META.get(ORG_HEADER) or (token.org_id if token else None)

    if token is not None and wanted != token.org_id:
        raise NotFound("Organization not found.")

    user = cast(User, request.user)  # views using this require authentication
    memberships = Membership.objects.select_related("org").filter(user=user)
    membership = (
        memberships.filter(org_id=wanted).first()
        if wanted
        else memberships.order_by("created_at").first()
    )
    if membership is None:
        if wanted:
            raise NotFound("Organization not found.")
        raise ApiError(
            "no_organization", "You are not a member of any organization.", status_code=403
        )
    return membership


class OrgScopedViewMixin:
    """Mix into DRF views over tenant-owned models.

    Sets ``self.org`` / ``self.membership`` and filters ``get_queryset()`` by org.
    ``method_roles`` maps HTTP methods to the roles allowed to call them (any one is enough);
    methods not listed are open to every member (docs/08-approvals-and-workflow.md).
    """

    method_roles: dict[str, frozenset[str]] = {}
    org_url_kwarg: str | None = None  # e.g. "org_id" for /orgs/{org_id}/...
    org: Organization
    membership: Membership

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)  # type: ignore[misc]  # authentication, permissions
        path_org = kwargs.get(self.org_url_kwarg) if self.org_url_kwarg else None
        self.membership = resolve_membership(request, path_org)
        self.org = self.membership.org
        allowed = self.method_roles.get(request.method or "")
        if allowed and not self.membership.has_role(*allowed):
            names = " or ".join(sorted(allowed))
            raise PermissionDenied(f"This needs the {names} role.", code="role_required")

    def get_queryset(self):
        return super().get_queryset().for_org(self.org)  # type: ignore[misc]
