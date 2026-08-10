"""Governed Insight and SQL SDK for Gravity private APIs.

Public exports are loaded lazily so the CLI can select a business workspace
before any workspace-dependent module is imported.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


__version__ = "0.2.0"

_EXPORTS = {
    "DEFAULT_METADATA_TTL_SECONDS": (".cache", "DEFAULT_METADATA_TTL_SECONDS"),
    "MetadataCache": (".cache", "MetadataCache"),
    "is_metadata_operation": (".cache", "is_metadata_operation"),
    "OperationCatalog": (".catalog", "OperationCatalog"),
    "OperationProbe": (".catalog", "OperationProbe"),
    "GravityInsightClient": (".client", "GravityInsightClient"),
    "CompositeService": (".composite", "CompositeService"),
    "Credential": (".credentials", "Credential"),
    "CredentialConfig": (".credentials", "CredentialConfig"),
    "CredentialProvider": (".credentials", "CredentialProvider"),
    "ExportContractRegistry": (".export_contracts", "ExportContractRegistry"),
    "ExportRouteContract": (".export_contracts", "ExportRouteContract"),
    "ExportCreationRequest": (".export_runtime", "ExportCreationRequest"),
    "ExportJobSnapshot": (".export_runtime", "ExportJobSnapshot"),
    "ExportOrchestrator": (".export_runtime", "ExportOrchestrator"),
    "ExportPollingPolicy": (".export_runtime", "ExportPollingPolicy"),
    "ExportPrivacyContract": (".export_runtime", "ExportPrivacyContract"),
    "ExportResult": (".export_runtime", "ExportResult"),
    "ExportRuntimeError": (".export_runtime", "ExportRuntimeError"),
    "ExportState": (".export_runtime", "ExportState"),
    "GravityClient": (".sql", "GravityClient"),
    "SqlBatchRequest": (".sql", "SqlBatchRequest"),
    "SqlBatchResult": (".sql", "SqlBatchResult"),
    "build_sql_client": (".sql", "build_sql_client"),
}

for _error_name in (
    "AuthenticationError",
    "CredentialError",
    "GravityInsightError",
    "GravityExportError",
    "InputValidationError",
    "ManifestError",
    "PaginationError",
    "ParentRequiredError",
    "PermissionUnavailableError",
    "PolicyViolation",
    "SqlResponseError",
    "SqlValidationError",
    "TransportError",
    "UnknownOperationError",
    "UpstreamError",
):
    _EXPORTS[_error_name] = (".errors", _error_name)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})


__all__ = [*_EXPORTS, "__version__"]
