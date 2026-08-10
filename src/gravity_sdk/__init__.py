"""Governed Insight and SQL SDK for Gravity private APIs."""

__version__ = "0.1.0"

from .cache import DEFAULT_METADATA_TTL_SECONDS, MetadataCache, is_metadata_operation
from .catalog import CapabilityCatalog, CapabilityProbe
from .client import GravityInsightClient
from .composite import CompositeService
from .credentials import Credential, CredentialConfig, CredentialProvider
from .errors import (
    AuthenticationError,
    CredentialError,
    GravityInsightError,
    GravityExportError,
    InputValidationError,
    ManifestError,
    PaginationError,
    ParentRequiredError,
    PermissionUnavailableError,
    PolicyViolation,
    SqlResponseError,
    SqlValidationError,
    TransportError,
    UnknownOperationError,
    UpstreamError,
)
from .export_contracts import ExportContractRegistry, ExportRouteContract
from .export_runtime import (
    ExportCreationRequest,
    ExportJobSnapshot,
    ExportOrchestrator,
    ExportPollingPolicy,
    ExportPrivacyContract,
    ExportResult,
    ExportRuntimeError,
    ExportState,
)
from .sql import GravityClient, SqlBatchRequest, SqlBatchResult, build_sql_client

__all__ = [
    "AuthenticationError",
    "Credential",
    "CredentialConfig",
    "CredentialError",
    "CredentialProvider",
    "ExportContractRegistry",
    "ExportCreationRequest",
    "ExportJobSnapshot",
    "ExportOrchestrator",
    "ExportPollingPolicy",
    "ExportPrivacyContract",
    "ExportResult",
    "ExportRouteContract",
    "ExportRuntimeError",
    "ExportState",
    "CapabilityCatalog",
    "CapabilityProbe",
    "CompositeService",
    "DEFAULT_METADATA_TTL_SECONDS",
    "GravityInsightClient",
    "GravityInsightError",
    "GravityClient",
    "GravityExportError",
    "InputValidationError",
    "ManifestError",
    "MetadataCache",
    "PaginationError",
    "ParentRequiredError",
    "PermissionUnavailableError",
    "PolicyViolation",
    "SqlResponseError",
    "SqlBatchRequest",
    "SqlBatchResult",
    "SqlValidationError",
    "TransportError",
    "UnknownOperationError",
    "UpstreamError",
    "is_metadata_operation",
    "build_sql_client",
    "__version__",
]
