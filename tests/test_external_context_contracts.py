from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from gravity_insight.external_context_contract import (
    ExternalContextContractError,
    build_rpc_request,
    compile_external_provider,
    compile_rpc_response,
    compile_rpc_result,
    decode_rpc_response,
    normalize_external_context_item,
)
def provider_descriptor(
    *,
    transport: str = "host",
    source_trust: str = "reviewed",
    alignment: str = "full",
    authority_ceiling: str | None = None,
    operations: tuple[str, ...] = ("list", "list_changed", "read", "search"),
    subprocess_binding: dict | None = None,
) -> dict:
    selected_ceiling = authority_ceiling or (
        "canonical"
        if source_trust == "reviewed" and alignment == "full"
        else "unverified"
    )
    return {
        "artifact_kind": "external_context_provider",
        "schema_version": "gravity.external-context-provider.v1",
        "uri": "context-provider://team/knowledge@1",
        "version": 1,
        "provider_id": "knowledge",
        "owner": "team-context",
        "transport": transport,
        "effects": ["read"],
        "auth_scope": "project",
        "resource_types": ["release", "document"],
        "allowed_resource_prefixes": ["provider://team/releases/", "provider://team/docs/"],
        "capabilities": {
            "operations": list(operations),
            "supports_cancellation": True,
            "supports_cache": True,
            "output_formats": ["json"],
            "freshness_model": "provider_revision",
            "entity_time_alignment": alignment,
        },
        "rpc": {
            "max_concurrency": 2,
            "max_calls_per_session": 10,
            "timeout_ms": 20_000,
            "cancellation_grace_ms": 25,
            "max_attempts": 2,
            "max_output_bytes": 65536,
            "max_output_tokens": 65536,
            "circuit_failure_threshold": 2,
            "circuit_cooldown_ms": 100,
        },
        "deployment": {
            "sandbox_owner": "provider-platform",
            "declared_egress_hosts": ["issues.example.invalid:443"],
            "inherits_gravity_credentials": False,
            "subprocess": subprocess_binding,
        },
        "source_trust": source_trust,
        "authority_ceiling": selected_ceiling,
        "role": "data",
    }


def resource(*, content: str = "External fact.", revision: str = "release-2026.08.22") -> dict:
    return {
        "uri": "provider://team/docs/fact",
        "title": "External fact",
        "resource_type": "document",
        "source_revision": revision,
        "item_id": "external-fact",
        "fact_id": "fact.external",
        "entity_refs": ["entity://gravity/app@1"],
        "valid_time": {"start": None, "end": None, "timezone": "Asia/Shanghai"},
        "effective_range": {"start": None, "end": None},
        "observed_at": "2026-08-22T00:00:00Z",
        "authority": "canonical",
        "freshness": "current",
        "supersedes": [],
        "sensitivity": "internal",
        "citation": {"path": "team/docs/fact", "line_start": 1, "line_end": 1},
        "content": content,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def response(request_id: str, *, resources: list[dict] | None = None, status: str = "success") -> dict:
    return {
        "schema_version": "gravity.provider-rpc-response.v1",
        "request_id": request_id,
        "status": status,
        "resources": [resource()] if resources is None else resources,
        "next_cursor": None,
        "stats": {"internal_requests": 2, "retries": 1, "cache_hits": 0},
    }


def command_descriptor() -> dict:
    descriptor = provider_descriptor(
        transport="subprocess",
        source_trust="observed",
        alignment="partial",
        authority_ceiling="declared_intent",
        operations=("read",),
        subprocess_binding={
            "executable": str(Path(sys.executable).resolve()),
            "arguments": [],
            "working_directory": str(Path.cwd().resolve()),
            "protocol": "command",
            "command": {
                "routes": [
                    {
                        "route_id": "fixture-document",
                        "resource_prefix": "provider://team/docs/",
                        "path_segment_count": 1,
                        "arguments": [{"uri_path_segment": 0}],
                        "resource": {
                            "item_id": "command-fixture",
                            "fact_id": "fact.command-fixture",
                            "title": "Command fixture",
                            "resource_type": "document",
                            "entity_refs": ["entity://gravity/app@1"],
                            "valid_time": {
                                "start": None,
                                "end": None,
                                "timezone": "Asia/Shanghai",
                            },
                            "effective_range": {"start": None, "end": None},
                            "sensitivity": "internal",
                            "citation_path": "command/fixture",
                        },
                        "failure_rules": [],
                        "freshness": None,
                    }
                ],
                "guidance": {
                    key: {
                        "missing": key,
                        "message": f"{key} fixture",
                        "user_actions": ["Repair the fixture command."],
                    }
                    for key in (
                        "source_unavailable",
                        "resource_unavailable",
                        "content_stale",
                    )
                },
            },
        },
    )
    descriptor["allowed_resource_prefixes"] = ["provider://team/docs/"]
    descriptor["resource_types"] = ["document"]
    descriptor["capabilities"]["freshness_model"] = "content_hash"
    return descriptor


class ExternalContextContractTests(unittest.TestCase):
    def test_descriptor_is_exact_normalized_and_separates_runtime_from_internal_io(self) -> None:
        first = compile_external_provider(provider_descriptor())
        second = compile_external_provider(provider_descriptor())

        self.assertEqual(first, second)
        self.assertEqual(
            ["document", "release"], first["contract"]["resource_types"]
        )
        self.assertEqual(
            ["list", "list_changed", "read", "search"],
            first["contract"]["capabilities"]["operations"],
        )
        self.assertFalse(
            first["contract"]["deployment"]["inherits_gravity_credentials"]
        )
        self.assertRegex(first["digest"], r"^[0-9a-f]{64}$")

    def test_descriptor_rejects_identity_effect_prefix_and_transport_drift(self) -> None:
        cases = []
        changed = provider_descriptor()
        changed["provider_id"] = "other"
        cases.append(changed)
        changed = provider_descriptor()
        changed["effects"] = ["write"]
        cases.append(changed)
        changed = provider_descriptor()
        changed["allowed_resource_prefixes"] = ["https://user@example.invalid/private/"]
        cases.append(changed)
        changed = provider_descriptor()
        changed["allowed_resource_prefixes"] = ["provider://team/docs/../private/"]
        cases.append(changed)
        changed = provider_descriptor()
        changed["allowed_resource_prefixes"] = ["provider://team/docs/%2e%2e/private/"]
        cases.append(changed)
        changed = provider_descriptor()
        changed["deployment"]["declared_egress_hosts"] = [
            "issues.example.invalid:99999"
        ]
        cases.append(changed)
        changed = provider_descriptor()
        changed["deployment"]["subprocess"] = {
            "executable": str(Path(sys.executable).resolve()),
            "arguments": [],
            "working_directory": str(Path.cwd().resolve()),
        }
        cases.append(changed)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                ExternalContextContractError
            ):
                compile_external_provider(value)

        no_revision = provider_descriptor(operations=("list_changed", "read"))
        no_revision["capabilities"]["freshness_model"] = "none"
        with self.assertRaisesRegex(
            ExternalContextContractError, "PROVIDER_DESCRIPTOR_INVALID"
        ):
            compile_external_provider(no_revision)

    def test_authority_ceiling_is_bound_to_trust_and_clamps_provider_self_report(self) -> None:
        declared = provider_descriptor(
            source_trust="observed",
            alignment="partial",
            authority_ceiling="declared_intent",
        )
        reported = resource()
        reported["authority"] = "project_authoritative"

        item = normalize_external_context_item(declared, reported)

        self.assertEqual("declared_intent", item["authority"])
        invalid = provider_descriptor(
            source_trust="observed",
            alignment="partial",
            authority_ceiling="canonical",
        )
        with self.assertRaisesRegex(
            ExternalContextContractError, "PROVIDER_DESCRIPTOR_INVALID"
        ):
            compile_external_provider(invalid)

    def test_command_descriptor_is_read_only_and_declared_intent(self) -> None:
        compiled = compile_external_provider(command_descriptor())["contract"]

        self.assertEqual(["read"], compiled["effects"])
        self.assertEqual(["read"], compiled["capabilities"]["operations"])
        self.assertEqual("command", compiled["deployment"]["subprocess"]["protocol"])
        self.assertEqual("declared_intent", compiled["authority_ceiling"])
        self.assertFalse(compiled["deployment"]["inherits_gravity_credentials"])

    def test_command_descriptor_rejects_unbounded_argument_shapes(self) -> None:
        descriptor = command_descriptor()
        descriptor["deployment"]["subprocess"]["command"]["routes"][0][
            "arguments"
        ] = [{"shell": "echo unsafe"}]

        with self.assertRaisesRegex(
            ExternalContextContractError, "PROVIDER_DESCRIPTOR_INVALID"
        ):
            compile_external_provider(descriptor)

        for protocol, command in (("command", None), ("provider_rpc", {})):
            with self.subTest(protocol=protocol):
                invalid = command_descriptor()
                invalid["deployment"]["subprocess"]["protocol"] = protocol
                invalid["deployment"]["subprocess"]["command"] = command
                with self.assertRaisesRegex(
                    ExternalContextContractError, "PROVIDER_DESCRIPTOR_INVALID"
                ):
                    compile_external_provider(invalid)

    def test_checked_command_source_descriptors_compile_without_source_code(self) -> None:
        root = Path(__file__).resolve().parents[1]
        contract_root = (
            root / "src" / "gravity_insight" / "contracts" / "context-providers"
        )
        descriptors = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(contract_root.glob("*.v1.json"))
        ]
        command_descriptors = [
            descriptor
            for descriptor in descriptors
            if descriptor["artifact_kind"] == "external_context_provider"
        ]
        self.assertGreaterEqual(len(command_descriptors), 2)
        for descriptor in command_descriptors:
            with self.subTest(provider_id=descriptor["provider_id"]):
                compiled = compile_external_provider(descriptor)["contract"]
                self.assertEqual(["read"], compiled["capabilities"]["operations"])
                self.assertEqual(
                    "command", compiled["deployment"]["subprocess"]["protocol"]
                )

    def test_subprocess_descriptor_requires_absolute_fixed_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding = {
                "executable": str(Path(sys.executable).resolve()),
                "arguments": ["provider.py"],
                "working_directory": str(Path(directory).resolve()),
            }
            compiled = compile_external_provider(
                provider_descriptor(
                    transport="subprocess", subprocess_binding=binding
                )
            )
            self.assertEqual(
                str(Path(sys.executable).resolve()),
                compiled["contract"]["deployment"]["subprocess"]["executable"],
            )

            for executable, working_directory in (
                ("/opt/gravity/provider", "/var/lib/gravity"),
                ("C:/Program Files/Gravity/provider.exe", "D:/gravity/project"),
                (r"C:\Program Files\Gravity\provider.exe", r"D:\gravity\project"),
            ):
                with self.subTest(
                    executable=executable, working_directory=working_directory
                ):
                    host_binding = copy.deepcopy(binding)
                    host_binding["executable"] = executable
                    host_binding["working_directory"] = working_directory
                    compile_external_provider(
                        provider_descriptor(
                            transport="subprocess",
                            subprocess_binding=host_binding,
                        )
                    )

            for field, value in (
                ("executable", "bin/provider"),
                ("working_directory", "relative"),
                ("executable", "C:provider.exe"),
                ("working_directory", r"D:gravity\project"),
            ):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(
                    ExternalContextContractError, "PROVIDER_DESCRIPTOR_INVALID"
                ):
                    relative = copy.deepcopy(binding)
                    relative[field] = value
                    compile_external_provider(
                        provider_descriptor(
                            transport="subprocess", subprocess_binding=relative
                        )
                    )

            credentials = copy.deepcopy(binding)
            credentials["arguments"] = ["--token=must-not-be-in-descriptor"]
            with self.assertRaisesRegex(
                ExternalContextContractError, "PROVIDER_DESCRIPTOR_INVALID"
            ):
                compile_external_provider(
                    provider_descriptor(
                        transport="subprocess", subprocess_binding=credentials
                    )
                )

    def test_rpc_request_allows_only_operation_specific_read_fields(self) -> None:
        request_id = "12345678-1234-4abc-8def-1234567890ab"
        request = build_rpc_request(
            "context-provider://team/knowledge@1",
            "read",
            {"resource_uri": "provider://team/docs/fact"},
            request_id=request_id,
        )
        self.assertEqual("read", request["operation"])

        for operation, payload in (
            ("read", {"resource_uri": "provider://team/docs/fact", "query": "x"}),
            ("search", {"cursor": None}),
            ("list", {"resource_uri": "provider://team/docs/fact"}),
        ):
            with self.subTest(operation=operation), self.assertRaisesRegex(
                ExternalContextContractError, "PROVIDER_RPC_REQUEST_INVALID"
            ):
                build_rpc_request(
                    "context-provider://team/knowledge@1",
                    operation,
                    payload,
                    request_id=request_id,
                )

    def test_rpc_response_is_strict_hash_bound_and_rank_independent(self) -> None:
        request_id = "12345678-1234-4abc-8def-1234567890ab"
        later = resource()
        later["uri"] = "provider://team/docs/z"
        earlier = resource()
        earlier["uri"] = "provider://team/docs/a"
        compiled = compile_rpc_response(
            response(request_id, resources=[later, earlier]),
            expected_request_id=request_id,
        )
        self.assertEqual(
            ["provider://team/docs/a", "provider://team/docs/z"],
            [item["uri"] for item in compiled["resources"]],
        )

        bad_hash = response(request_id)
        bad_hash["resources"][0]["content_hash"] = "0" * 64
        with self.assertRaisesRegex(
            ExternalContextContractError, "PROVIDER_RESOURCE_HASH_MISMATCH"
        ):
            compile_rpc_response(bad_hash, expected_request_id=request_id)

    def test_decode_rejects_duplicate_nonfinite_byte_and_token_bombs(self) -> None:
        request_id = "12345678-1234-4abc-8def-1234567890ab"
        valid = json.dumps(response(request_id), separators=(",", ":")).encode()
        decoded, tokens = decode_rpc_response(
            valid,
            expected_request_id=request_id,
            max_output_bytes=len(valid),
            max_output_tokens=len(valid),
        )
        self.assertEqual("success", decoded["status"])
        self.assertEqual(len(valid), tokens)

        duplicate = b'{"schema_version":"gravity.provider-rpc-response.v1","schema_version":"gravity.provider-rpc-response.v1"}'
        nonfinite = b'{"value":NaN}'
        for content in (duplicate, nonfinite):
            with self.subTest(content=content), self.assertRaisesRegex(
                ExternalContextContractError, "PROVIDER_RPC_MALFORMED"
            ):
                decode_rpc_response(
                    content,
                    expected_request_id=request_id,
                    max_output_bytes=1024,
                    max_output_tokens=1024,
                )
        with self.assertRaisesRegex(
            ExternalContextContractError, "PROVIDER_RPC_OUTPUT_LIMIT"
        ):
            decode_rpc_response(
                valid,
                expected_request_id=request_id,
                max_output_bytes=len(valid) - 1,
                max_output_tokens=len(valid),
            )
        with self.assertRaisesRegex(
            ExternalContextContractError, "PROVIDER_RPC_TOKEN_LIMIT"
        ):
            decode_rpc_response(
                valid,
                expected_request_id=request_id,
                max_output_bytes=len(valid),
                max_output_tokens=len(valid) - 1,
            )

    def test_context_normalization_preserves_exact_revision_and_downgrades_observed(self) -> None:
        reviewed = normalize_external_context_item(
            provider_descriptor(), resource(revision="release-2026.08.22")
        )
        observed = normalize_external_context_item(
            provider_descriptor(source_trust="observed"), resource()
        )

        self.assertEqual("release-2026.08.22", reviewed["source_revision"])
        self.assertEqual("canonical", reviewed["authority"])
        self.assertEqual("reviewed", reviewed["source_trust"])
        self.assertEqual("data", reviewed["role"])
        self.assertEqual("unverified", observed["authority"])
        self.assertEqual("observed", observed["source_trust"])

        incomplete = resource()
        incomplete.pop("entity_refs")
        with self.assertRaisesRegex(
            ExternalContextContractError, "CONTEXT_ALIGNMENT_UNSUPPORTED"
        ):
            normalize_external_context_item(provider_descriptor(), incomplete)

    def test_public_result_rejects_gap_success_contradictions(self) -> None:
        base = {
            "schema_version": "gravity.provider-rpc-result.v1",
            "status": "context_gap",
            "ok": False,
            "provider_uri": "context-provider://team/knowledge@1",
            "provider_digest": "0" * 64,
            "operation": "read",
            "request_id": None,
            "resources": [],
            "context_items": [],
            "next_cursor": None,
            "reason_codes": ["PROVIDER_RPC_UNAVAILABLE"],
            "exit_code": 4,
            "enforced_rpc": {
                "logical_calls": 0,
                "transport_attempts": 0,
                "successes": 0,
                "gaps": 1,
                "retries": 0,
                "timeouts": 0,
                "cancellations": 0,
                "unavailable": 0,
                "malformed": 0,
                "oversize": 0,
                "busy": 0,
                "permission_filtered": 0,
                "output_bytes": 0,
                "output_tokens": 0,
                "active": 0,
                "peak_active": 0,
                "max_concurrency": 1,
                "process_capacity": 8,
                "max_calls_per_session": 1,
            },
            "provider_reported": {
                "internal_requests": None,
                "retries": None,
                "cache_hits": None,
                "enforced": False,
            },
            "circuit": {
                "state": "closed",
                "consecutive_failures": 0,
                "open_count": 0,
                "cooldown_remaining_ms": 0,
            },
            "provider_rpc_called": False,
            "provider_internal_io_controlled": False,
            "provider_internal_network": "not_observable",
        }
        self.assertEqual(base, compile_rpc_result(base))
        wrong = copy.deepcopy(base)
        wrong["ok"] = True
        with self.assertRaisesRegex(
            ExternalContextContractError, "PROVIDER_RPC_RESULT_INVALID"
        ):
            compile_rpc_result(wrong)


if __name__ == "__main__":
    unittest.main()
