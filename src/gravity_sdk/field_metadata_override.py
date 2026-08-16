"""Context-local FieldPolicy metadata sources for pinned Plan execution."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


MetadataLoader = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
_ACTIVE_LOADER: ContextVar[MetadataLoader | None] = ContextVar(
    "gravity_field_metadata_loader", default=None
)


def selected_metadata_loader(default: MetadataLoader) -> MetadataLoader:
    """Return the context-pinned loader or the client's normal live loader."""

    return _ACTIVE_LOADER.get() or default


@contextmanager
def use_field_metadata_loader(loader: MetadataLoader) -> Iterator[None]:
    """Bind one loader to the current execution context and restore it safely."""

    if not callable(loader):
        raise TypeError("field metadata loader must be callable")
    token = _ACTIVE_LOADER.set(loader)
    try:
        yield
    finally:
        _ACTIVE_LOADER.reset(token)


__all__ = ["MetadataLoader", "selected_metadata_loader", "use_field_metadata_loader"]
