"""Versioned Resource URIs, pagination, access filtering and scoped caching."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import secrets
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from ..agent_runtime_contracts import canonical_digest
from ..skill_hub_client import SkillHubClient


RESOURCE_CATALOG_SCHEMA_VERSION = "gravity.mcp-resource-catalog.v1"
RESOURCE_CONTENT_SCHEMA_VERSION = "gravity.mcp-resource-content.v1"
MAX_RESOURCE_BYTES = 100_000
_STATIC_RESOURCES = (
    ("gravity://server/metadata", "Gravity MCP server metadata"),
    ("gravity://catalog/capabilities", "Governed Capability catalog"),
    ("gravity://catalog/journeys", "Registered Journey catalog"),
    ("gravity://catalog/skills", "Synced Skill Hub catalog"),
    ("gravity://workspace/apps", "Configured workspace App aliases"),
    ("gravity://catalog/sql-products", "Registered SQL product catalog"),
    ("gravity://receipts", "Principal-scoped Runtime receipt page"),
)
_TEMPLATES = (
    (
        "gravity://apps/{app}/saved-analyses",
        "Saved Analysis directory for one authorized workspace App alias",
    ),
    (
        "gravity://metadata/table-lineage/{query}",
        "Offline synchronized table-lineage search",
    ),
    (
        "gravity://workspace/analysis-vocabulary/{query}",
        "Offline workspace-scoped Analysis vocabulary search",
    ),
)


class ResourceError(ValueError):
    """A Resource is unknown, denied, malformed, or over budget."""


class ResourceAccessPolicy:
    def __init__(
        self,
        *,
        uri_filter: Callable[[str], bool] | None = None,
        app_filter: Callable[[str], bool] | None = None,
    ) -> None:
        self._uri_filter = uri_filter or (lambda _uri: True)
        self._app_filter = app_filter or (lambda _app: True)

    def allows_uri(self, uri: str) -> bool:
        return bool(self._uri_filter(uri))

    def allows_app(self, alias: str) -> bool:
        return bool(self._app_filter(alias))


class ScopedResourceCache:
    """Small in-memory cache that never shares values across opaque scopes."""

    def __init__(self, *, max_entries: int = 64) -> None:
        if not 1 <= max_entries <= 1_024:
            raise ValueError("Resource cache size is outside its fixed boundary")
        self._maximum = max_entries
        self._values: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    def get(self, scope: str, uri: str) -> dict[str, Any] | None:
        key = (scope, uri)
        selected = self._values.get(key)
        if selected is None:
            return None
        self._values.move_to_end(key)
        return copy.deepcopy(selected)

    def put(self, scope: str, uri: str, value: Mapping[str, Any]) -> None:
        key = (scope, uri)
        self._values[key] = copy.deepcopy(dict(value))
        self._values.move_to_end(key)
        while len(self._values) > self._maximum:
            self._values.popitem(last=False)


def resource_contract() -> dict[str, Any]:
    payload = {
        "schema_version": RESOURCE_CATALOG_SCHEMA_VERSION,
        "static_uris": [uri for uri, _title in _STATIC_RESOURCES],
        "uri_templates": [uri for uri, _title in _TEMPLATES],
    }
    payload["fingerprint"] = canonical_digest(payload)
    return payload


class ResourceCatalog:
    def __init__(
        self,
        sdk: Any,
        *,
        metadata: Callable[[], Mapping[str, Any]],
        access: ResourceAccessPolicy | None = None,
        cache: ScopedResourceCache | None = None,
        principal_scope: str | None = None,
        page_size: int = 5,
    ) -> None:
        if not 1 <= page_size <= 50:
            raise ValueError("Resource page size is outside its fixed boundary")
        self._sdk = sdk
        self._metadata = metadata
        self._access = access or ResourceAccessPolicy()
        self._cache = cache or ScopedResourceCache()
        self._page_size = page_size
        workspace = getattr(sdk, "workspace", None)
        self._skill_state_root = getattr(workspace, "state_root", None)
        workspace_identity = str(
            getattr(workspace, "state_root", None)
            or getattr(workspace, "root", None)
            or "unconfigured"
        )
        principal = principal_scope or secrets.token_hex(32)
        self._scope = hashlib.sha256(
            f"{principal}\0{workspace_identity}".encode("utf-8")
        ).hexdigest()

    def list(self, cursor: str | None = None) -> dict[str, Any]:
        resources = self._descriptors()
        offset = _decode_cursor(cursor, resource_contract()["fingerprint"])
        if offset > len(resources):
            raise ResourceError("Resource cursor is outside the current catalog")
        selected = resources[offset : offset + self._page_size]
        next_offset = offset + len(selected)
        result: dict[str, Any] = {"resources": selected}
        if next_offset < len(resources):
            result["nextCursor"] = _encode_cursor(
                next_offset, resource_contract()["fingerprint"]
            )
        return result

    def templates(self) -> dict[str, Any]:
        rows = [
            {
                "uriTemplate": uri,
                "name": title,
                "description": title,
                "mimeType": "application/json",
            }
            for uri, title in _TEMPLATES
            if self._access.allows_uri(uri)
        ]
        return {"resourceTemplates": rows}

    def read(self, uri: str) -> dict[str, Any]:
        selected = _valid_uri(uri)
        if not self._access.allows_uri(selected):
            raise ResourceError("Resource is unavailable")
        app = _saved_analysis_app(selected)
        if app is not None:
            workspace = getattr(self._sdk, "workspace", None)
            apps = getattr(workspace, "apps", {})
            if app not in apps or not self._access.allows_app(app):
                raise ResourceError("Resource is unavailable")
        cached = self._cache.get(self._scope, selected)
        if cached is not None:
            return cached
        value = self._read_uncached(selected, app)
        content = {
            "schema_version": RESOURCE_CONTENT_SCHEMA_VERSION,
            "uri": selected,
            "value": value,
        }
        if len(_canonical_text(content).encode("utf-8")) > MAX_RESOURCE_BYTES:
            raise ResourceError("Resource exceeds the MCP output byte budget")
        self._cache.put(self._scope, selected, content)
        return content

    def _descriptors(self) -> list[dict[str, Any]]:
        rows = [
            _descriptor(uri, title)
            for uri, title in _STATIC_RESOURCES
            if self._access.allows_uri(uri)
        ]
        workspace = getattr(self._sdk, "workspace", None)
        apps = getattr(workspace, "apps", {})
        for alias in sorted(apps):
            uri = f"gravity://apps/{quote(alias, safe='')}/saved-analyses"
            if self._access.allows_app(alias) and self._access.allows_uri(uri):
                rows.append(_descriptor(uri, f"Saved Analyses for {alias}"))
        return sorted(rows, key=lambda item: item["uri"])

    def _read_uncached(self, uri: str, app: str | None) -> dict[str, Any]:
        readers: dict[str, Callable[[], Any]] = {
            "gravity://server/metadata": lambda: dict(self._metadata()),
            "gravity://catalog/capabilities": lambda: self._sdk.capabilities(limit=50),
            "gravity://catalog/journeys": self._sdk.journeys.list,
            "gravity://catalog/skills": self._skill_list,
            "gravity://workspace/apps": self._workspace_apps,
            "gravity://catalog/sql-products": self._sql_products,
            "gravity://receipts": lambda: self._sdk.list_http_receipts(limit=100),
        }
        reader = readers.get(uri)
        if reader is not None:
            return dict(reader())
        if app is not None:
            return dict(
                self._sdk.saved_analyses(app, max_pages=5, max_items=200)
            )
        lineage_query = _template_value(uri, "metadata", "table-lineage")
        if lineage_query is not None:
            return dict(self._sdk.table_lineage(lineage_query, limit=50))
        vocabulary_query = _template_value(
            uri, "workspace", "analysis-vocabulary"
        )
        if vocabulary_query is not None:
            return dict(self._sdk.analysis_vocabulary(vocabulary_query, limit=50))
        raise ResourceError("Resource is unavailable")

    def _skill_list(self) -> dict[str, Any]:
        return SkillHubClient(self._skill_state_root).list()

    def _workspace_apps(self) -> dict[str, Any]:
        workspace = getattr(self._sdk, "workspace", None)
        apps = getattr(workspace, "apps", {})
        rows = [
            {"alias": alias, "app_id": app_id}
            for alias, app_id in sorted(apps.items())
            if self._access.allows_app(alias)
        ]
        return {
            "schema_version": "gravity.mcp-workspace-apps.v1",
            "status": "success",
            "count": len(rows),
            "apps": rows,
            "network_called": False,
        }

    def _sql_products(self) -> dict[str, Any]:
        products = self._sdk.describe_sql_products()
        return {
            "schema_version": "gravity.mcp-sql-products.v1",
            "status": "success",
            "count": len(products),
            "products": products,
            "network_called": False,
        }


def _descriptor(uri: str, title: str) -> dict[str, Any]:
    return {
        "uri": uri,
        "name": title,
        "description": title,
        "mimeType": "application/json",
    }


def _valid_uri(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 2_048:
        raise ResourceError("Resource URI is invalid")
    parsed = urlsplit(value)
    if parsed.scheme != "gravity" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ResourceError("Resource URI is invalid")
    return value


def _saved_analysis_app(uri: str) -> str | None:
    parsed = urlsplit(uri)
    if parsed.netloc != "apps":
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2 or parts[1] != "saved-analyses":
        return None
    alias = unquote(parts[0])
    return alias if alias and "/" not in alias and "\\" not in alias else None


def _template_value(uri: str, authority: str, prefix: str) -> str | None:
    parsed = urlsplit(uri)
    parts = parsed.path.strip("/").split("/", 1)
    if parsed.netloc != authority or len(parts) != 2 or parts[0] != prefix:
        return None
    value = unquote(parts[1])
    if not value or len(value) > 512:
        raise ResourceError("Resource URI template value is invalid")
    return value


def _encode_cursor(offset: int, fingerprint: str) -> str:
    raw = f"{fingerprint}:{offset}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None, fingerprint: str) -> int:
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or not cursor or len(cursor) > 256:
        raise ResourceError("Resource cursor is invalid")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
        selected_fingerprint, offset = raw.rsplit(":", 1)
        value = int(offset)
    except (ValueError, UnicodeError) as exc:
        raise ResourceError("Resource cursor is invalid") from exc
    if selected_fingerprint != fingerprint or value < 0:
        raise ResourceError("Resource cursor is stale or invalid")
    return value


def _canonical_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = [
    "MAX_RESOURCE_BYTES",
    "RESOURCE_CATALOG_SCHEMA_VERSION",
    "RESOURCE_CONTENT_SCHEMA_VERSION",
    "ResourceAccessPolicy",
    "ResourceCatalog",
    "ResourceError",
    "ScopedResourceCache",
    "resource_contract",
]
