"""Namespaced sub-resources: ``client.documents.upload_etd(...)``.

The ``ab`` package already trained everyone on this shape
(``api.jobs.shipment.book``), and a flat client with sixty methods on it does
not scale. Each resource is a thin object bound to its client; every method
is still a one-line call to ``client.request``.
"""
from __future__ import annotations

from typing import Any, Generic, Type, TypeVar


class Resource:
    """Base for a group of related endpoints on one carrier."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        return self._client

    @property
    def config(self) -> Any:
        return self._client.config

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self._client.carrier_name}>"


R = TypeVar("R", bound=Resource)


class resource(Generic[R]):  # noqa: N801 - used as a lowercase descriptor
    """Lazily attach a :class:`Resource` to a client, once per instance.

    ``documents = resource(DocumentsResource)`` on the client class gives
    ``client.documents`` without constructing every namespace up front.
    """

    def __init__(self, resource_class: Type[R]) -> None:
        self._resource_class = resource_class
        self._name = f"_resource_{resource_class.__name__}"

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = f"_resource_{name}"

    def __get__(self, instance: Any, owner: type) -> Any:
        if instance is None:
            return self
        existing = instance.__dict__.get(self._name)
        if existing is None:
            existing = self._resource_class(instance)
            instance.__dict__[self._name] = existing
        return existing


__all__ = ["Resource", "resource"]
