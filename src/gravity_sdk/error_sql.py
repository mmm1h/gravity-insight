"""SQL request, response, and export error types."""

from __future__ import annotations

from .error_models import ErrorCode, GravityInsightError
from .error_types import InputValidationError


class SqlValidationError(InputValidationError):
    """A SQL request is malformed or exceeds a local safety bound."""


class SqlResponseError(GravityInsightError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE


class GravityExportError(GravityInsightError):
    code = ErrorCode.EXPORT_TIMEOUT


class ExportTimeoutError(GravityExportError):
    code = ErrorCode.EXPORT_TIMEOUT


for _compat_symbol in (
    SqlValidationError,
    SqlResponseError,
    GravityExportError,
    ExportTimeoutError,
):
    _compat_symbol.__module__ = "gravity_sdk.errors"
del _compat_symbol
