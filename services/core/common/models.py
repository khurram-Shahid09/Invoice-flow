from django.db import models


class TimeStampedModel(models.Model):
    """Every table has ``created_at`` and ``updated_at`` (docs/10-data-model.md)."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
