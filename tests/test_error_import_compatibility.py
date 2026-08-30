"""Lock the complete errors.py import surface from dev@b7c15ed."""

from __future__ import annotations

import unittest

import gravity_insight
import gravity_insight.errors as errors


# Generated from `git show b7c15ed:src/gravity_insight/errors.py`, not sampled.
BASELINE_IMPORT_NAMES = {
    "Any", "AuthMissingError", "AuthenticationError", "CALLER_ERROR_EXIT",
    "ConcurrentModificationError", "ContractChangedError", "CredentialError",
    "Enum", "ErrorCategory", "ErrorCode", "ErrorDetail", "ErrorEnvelope",
    "ExportTimeoutError", "GravityExportError", "GravityInsightError",
    "InputValidationError", "LOCAL_ERROR_EXIT", "LocalIOError", "ManifestError",
    "Mapping", "MutationReadbackError", "ObjectAlreadyExistsError",
    "ObjectReferencedError", "OperationNotImplementedError",
    "OwnershipMarkerRequiredError", "PaginationError", "PaginationLimitError",
    "ParentRequiredError", "PermissionUnavailableError", "PolicyViolation",
    "QuotaExceededError", "RateLimitedError", "SUCCESS_STATUSES",
    "SemanticRejectedError", "SqlResponseError", "SqlValidationError",
    "TransportError", "UPSTREAM_ERROR_EXIT", "UnknownOperationError",
    "UnsupportedOperationError", "UpstreamContradictedRequestError",
    "UpstreamError", "UpstreamUnavailableError", "_CODE_DEFAULTS",
    "_EXTENSION_CODE_RE", "_code_value", "_default_next_action", "_input_field",
    "_single_line", "annotations", "dataclass", "error_detail_from_exception",
    "error_envelope", "error_for_status", "exit_code_for_category",
    "exit_code_for_error", "exit_code_for_status", "is_success_status", "re",
    "semantic_envelope_ok",
}

BASELINE_ERROR_CONTRACTS = {
    "AuthMissingError": (("CredentialError",), "AUTH_MISSING", "caller", False),
    "AuthenticationError": (("CredentialError",), "AUTH_REJECTED", "caller", False),
    "ConcurrentModificationError": (("UpstreamError",), "CONCURRENT_MODIFICATION", "upstream", True),
    "ContractChangedError": (("GravityInsightError",), "CONTRACT_CHANGED", "upstream", False),
    "CredentialError": (("GravityInsightError",), "AUTH_MISSING", "caller", False),
    "ExportTimeoutError": (("GravityExportError",), "EXPORT_TIMEOUT", "upstream", True),
    "GravityExportError": (("GravityInsightError",), "EXPORT_TIMEOUT", "upstream", True),
    "GravityInsightError": (("RuntimeError",), "UPSTREAM_UNAVAILABLE", "upstream", True),
    "InputValidationError": (("GravityInsightError", "ValueError"), "INPUT_INVALID", "caller", False),
    "LocalIOError": (("GravityInsightError", "OSError"), "LOCAL_IO_ERROR", "local", False),
    "ManifestError": (("GravityInsightError", "ValueError"), "CONTRACT_CHANGED", "upstream", False),
    "MutationReadbackError": (("UpstreamError",), "MUTATION_READBACK_FAILED", "upstream", True),
    "ObjectAlreadyExistsError": (("InputValidationError",), "OBJECT_ALREADY_EXISTS", "caller", False),
    "ObjectReferencedError": (("InputValidationError",), "OBJECT_REFERENCED", "caller", False),
    "OperationNotImplementedError": (("PolicyViolation",), "NOT_IMPLEMENTED", "local", False),
    "OwnershipMarkerRequiredError": (("InputValidationError",), "OWNERSHIP_MARKER_REQUIRED", "caller", False),
    "PaginationError": (("GravityInsightError",), "PAGINATION_LIMIT", "caller", False),
    "PaginationLimitError": (("PaginationError",), "PAGINATION_LIMIT", "caller", False),
    "ParentRequiredError": (("InputValidationError",), "PARENT_REQUIRED", "caller", False),
    "PermissionUnavailableError": (("GravityInsightError", "PermissionError"), "PERMISSION_UNAVAILABLE", "upstream", False),
    "PolicyViolation": (("GravityInsightError", "PermissionError"), "UNSUPPORTED", "local", False),
    "QuotaExceededError": (("InputValidationError",), "QUOTA_EXCEEDED", "caller", False),
    "RateLimitedError": (("TransportError",), "RATE_LIMITED", "upstream", True),
    "SemanticRejectedError": (("UpstreamError",), "INPUT_INVALID", "caller", False),
    "SqlResponseError": (("GravityInsightError",), "UPSTREAM_UNAVAILABLE", "upstream", True),
    "SqlValidationError": (("InputValidationError",), "INPUT_INVALID", "caller", False),
    "TransportError": (("GravityInsightError",), "UPSTREAM_UNAVAILABLE", "upstream", True),
    "UnknownOperationError": (("GravityInsightError", "LookupError"), "UNKNOWN_OPERATION", "caller", False),
    "UnsupportedOperationError": (("PolicyViolation",), "UNSUPPORTED", "local", False),
    "UpstreamContradictedRequestError": (("SemanticRejectedError",), "UPSTREAM_UNAVAILABLE", "upstream", True),
    "UpstreamError": (("GravityInsightError",), "UPSTREAM_UNAVAILABLE", "upstream", True),
    "UpstreamUnavailableError": (("TransportError",), "UPSTREAM_UNAVAILABLE", "upstream", True),
}

ROOT_ERROR_EXPORTS = {
    "AuthenticationError", "CredentialError", "GravityInsightError",
    "GravityExportError", "InputValidationError", "ManifestError",
    "PaginationError", "ParentRequiredError", "PermissionUnavailableError",
    "PolicyViolation", "SemanticRejectedError", "SqlResponseError",
    "SqlValidationError", "TransportError", "UnknownOperationError",
    "UpstreamContradictedRequestError", "UpstreamError",
}


class ErrorImportCompatibilityTests(unittest.TestCase):
    def test_every_baseline_errors_symbol_remains_explicitly_importable(self) -> None:
        current = {
            name for name in vars(errors)
            if not (name.startswith("__") and name.endswith("__"))
        }
        self.assertEqual(BASELINE_IMPORT_NAMES, current)
        for name in BASELINE_IMPORT_NAMES:
            with self.subTest(name=name):
                self.assertIsNotNone(getattr(errors, name))

    def test_every_error_type_preserves_hierarchy_and_normalized_attributes(self) -> None:
        for name, expected in BASELINE_ERROR_CONTRACTS.items():
            with self.subTest(name=name):
                error_type = getattr(errors, name)
                self.assertEqual("gravity_insight.errors", error_type.__module__)
                detail = error_type("first\nsecond").to_error_detail(
                    operation_id="operation.test"
                )
                actual = (
                    tuple(base.__name__ for base in error_type.__bases__),
                    detail.code,
                    detail.category,
                    detail.retryable,
                )
                self.assertEqual(expected, actual)
                self.assertEqual("first second", detail.message)

    def test_root_lazy_error_exports_still_resolve_to_facade_symbols(self) -> None:
        for name in ROOT_ERROR_EXPORTS:
            with self.subTest(name=name):
                self.assertIs(getattr(errors, name), getattr(gravity_insight, name))


if __name__ == "__main__":
    unittest.main()
