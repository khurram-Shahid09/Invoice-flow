"""Tenant scoping. Every tenant-owned table has ``org`` and every query filters by it
(docs/10-data-model.md, threat T7 in docs/12-security-privacy.md).

- Models: subclass ``OrgOwnedModel``. ``Model.objects.for_org(org)`` is the only intended
  way to query them from API code.
- Views: subclass ``accounts.views_base.OrgScopedViewMixin``, which resolves ``self.org``
  and filters ``get_queryset()`` by it.
A meta-test (accounts/tests/test_tenant_isolation.py) fails if a model with an ``org``
field skips ``OrgOwnedModel``, or if an API view over such a model skips the mixin.
"""

from typing import TYPE_CHECKING, Self

from django.db import models

if TYPE_CHECKING:
    from accounts.models import Organization


class OrgScopedQuerySet(models.QuerySet):
    def for_org(self, org: "Organization") -> Self:
        if org is None or not getattr(org, "pk", None):
            raise ValueError("for_org() needs a saved organization")
        return self.filter(org=org)


class OrgOwnedModel(models.Model):
    org = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="+")

    objects = OrgScopedQuerySet.as_manager()

    class Meta:
        abstract = True
