"""Prefixed ULID primary keys, e.g. ``usr_01JB3...`` (docs/10-data-model.md)."""

import re

from django.db import models
from django.utils.deconstruct import deconstructible
from ulid import ULID

PREFIX_RE = re.compile(r"^[a-z]{2,5}$")


@deconstructible
class PrefixedULID:
    """Callable default that yields ``<prefix>_<ulid>``. Deconstructible so migrations can serialize it."""

    def __init__(self, prefix: str) -> None:
        if not PREFIX_RE.match(prefix):
            raise ValueError(f"invalid id prefix: {prefix!r}")
        self.prefix = prefix

    def __call__(self) -> str:
        return f"{self.prefix}_{ULID()}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PrefixedULID) and other.prefix == self.prefix

    def __hash__(self) -> int:
        return hash(self.prefix)


class PrefixedIdField(models.CharField):
    """Text primary key generated client-side as a prefixed ULID (sortable by creation time)."""

    def __init__(self, prefix: str | None = None, *args, **kwargs) -> None:
        self.prefix = prefix
        kwargs.setdefault("max_length", 32)  # 5 prefix + "_" + 26 ULID
        kwargs.setdefault("primary_key", True)
        kwargs.setdefault("editable", False)
        if prefix is not None:
            kwargs["default"] = PrefixedULID(prefix)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("default", None)
        kwargs["prefix"] = self.prefix
        for key, value in (("max_length", 32), ("primary_key", True), ("editable", False)):
            if kwargs.get(key) == value:
                kwargs.pop(key)
        return name, path, args, kwargs
