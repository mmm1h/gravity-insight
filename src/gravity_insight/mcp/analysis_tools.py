"""Thin MCP delegates for Runtime inspection, readiness and execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..skill_hub_client import SkillHubClient
from ..credential_sanitization import sanitize_credentials
from ..json_output import dumps
from ..result_output import output_file, result_is_persistable, terminal_result_exit_code, write_rendered_result
from ..contracts.envelope_obligations import EnvelopeObligations, serialize_envelope
from .schemas import MCPInputError


class AnalysisTools:
    def __init__(
        self,
        sdk: Any,
        *,
        metadata: Callable[[], Mapping[str, Any]],
    ) -> None:
        self._sdk = sdk
        self._metadata = metadata
        workspace = getattr(sdk, "workspace", None)
        self._skill_state_root = getattr(workspace, "state_root", None)

    def inspect(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        kind = arguments["kind"]
        identifier = arguments.get("identifier")
        if kind == "server":
            return dict(self._metadata())
        if kind == "journey":
            return (
                self._sdk.journeys.describe(identifier)
                if identifier is not None
                else self._sdk.journeys.list()
            )
        skills = SkillHubClient(self._skill_state_root)
        return skills.show(identifier) if identifier is not None else skills.list()

    def journey_can_run(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return self._sdk.journeys.can_run(
            arguments["journey_id"], arguments.get("inputs", {})
        )

    def capability_describe(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return self._sdk.capability_trust.trust(
            arguments["identity_kind"], arguments["selector"]
        )

    def execute(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        output = arguments.get("output")
        if output is not None and (not isinstance(output, Mapping) or output.get("confirm") is not True):
            raise MCPInputError("Complete file delivery requires explicit output.confirm=true")
        destination = output_file(output["destination"]) if output is not None else None
        result = self._sdk.journeys.run(
            arguments["journey_id"], arguments["inputs"]
        )
        if destination is None or not result_is_persistable(result):
            return result
        rendered = dumps(sanitize_credentials(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        publication = write_rendered_result(destination, rendered)
        return _file_result(result, publication)


def _file_result(result: Mapping[str, Any], publication: Mapping[str, Any]) -> dict[str, Any]:
    """Publication facts describe file bytes; source facts keep their own layer."""
    fields = (
        "schema_version", "ok", "status", "exit_code", "completeness", "obligations",
        "result_source", "result_audit", "allowed_claims", "forbidden_claims", "network_called",
    )
    source = {key: result[key] for key in fields if key in result}
    ok = result.get("ok") is not False and result.get("exit_code", 0) == 0
    return serialize_envelope({
        "schema_version": "gravity.journey-file-result.v1",
        "ok": ok,
        "status": result.get("status", "success" if ok else "error"),
        "exit_code": result.get("exit_code", 0 if ok else terminal_result_exit_code(result)),
        "publication": dict(publication),
        "source_result": source,
        "full_result_in_file": True,
        "network_called": result.get("network_called") if type(result.get("network_called")) is bool else None,
    }, EnvelopeObligations.from_dict(publication["obligations"]))


__all__ = ["AnalysisTools"]
