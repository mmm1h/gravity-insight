"""Resolve explicit external Context dependencies through injected Providers."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import is_sha256
from .context_contract import public_context_reference
from .external_context_binding_contract import (
    BINDINGS_FILENAME,
    SCHEMA_VERSION,
    ExternalContextBindingError,
    compile_external_context_bindings,
    load_external_context_bindings,
    verify_external_context_binding_revision,
)
from .external_context_pack import assemble_external_context_pack


RESOLUTION_SCHEMA_VERSION = "gravity.external-context-binding-resolution.v1"


class ExternalContextBindingResolver:
    """Bind exact project requirements to explicit Provider instances."""

    def __init__(
        self,
        *,
        workspace: Any,
        providers: Sequence[Any] = (),
    ) -> None:
        self._workspace = workspace
        self._providers = _provider_instances(providers)

    def resolve(
        self,
        *,
        required: Sequence[str],
        optional: Sequence[str],
        skill_uri: str,
        journey_id: str,
        aliases: Mapping[str, str],
        windows: Mapping[str, Mapping[str, str]],
        project_revision: str,
    ) -> dict[str, Any]:
        required_set = _dependency_set(required, "required")
        optional_set = _dependency_set(optional, "optional")
        if required_set.intersection(optional_set):
            raise ExternalContextBindingError(
                "EXTERNAL_CONTEXT_BINDING_INVALID",
                "Context dependency cannot be required and optional",
            )
        if not isinstance(skill_uri, str) or not skill_uri or not isinstance(journey_id, str) or not journey_id:
            raise ExternalContextBindingError(
                "EXTERNAL_CONTEXT_BINDING_INVALID", "Skill or Journey identity is invalid"
            )
        target = required_set | optional_set
        if not target:
            return _resolution([], [], [], True, False)
        root = _project_root(self._workspace)
        bindings = _load_bindings(root, sorted(required_set), sorted(optional_set))
        if not _is_binding_registry(bindings):
            return bindings
        if bindings["source_revision"] != project_revision:
            raise ExternalContextBindingError(
                "EXTERNAL_CONTEXT_BINDING_SNAPSHOT_CHANGED",
                "External Context binding and Project Overlay revisions disagree",
            )
        selected = _selected_requirements(
            bindings,
            target,
            skill_uri=skill_uri,
            journey_id=journey_id,
        )
        packs, reasons, complete, called = self._resolve_selected(
            selected,
            bindings,
            required=required_set,
            optional=optional_set,
            aliases=aliases,
            windows=windows,
        )
        selected_ids = {item["contract"]["requirement_id"] for item in selected}
        if required_set - selected_ids:
            reasons.append("CONTEXT_REQUIRED_MISSING")
        if optional_set - selected_ids:
            complete = False
        verify_external_context_binding_revision(root, bindings["source_revision"])
        return _resolution(
            packs,
            sorted(selected_ids),
            list(dict.fromkeys(reasons)),
            complete,
            called,
        )

    def _resolve_selected(
        self,
        selected: Sequence[Mapping[str, Any]],
        bindings: Mapping[str, Any],
        *,
        required: set[str],
        optional: set[str],
        aliases: Mapping[str, str],
        windows: Mapping[str, Mapping[str, str]],
    ) -> tuple[list[dict[str, Any]], list[str], bool, bool]:
        packs: list[dict[str, Any]] = []
        reasons: list[str] = []
        complete = True
        called = False
        for artifact in selected:
            contract = artifact["contract"]
            provider_artifact = bindings["providers"][contract["provider_uri"]]
            pack, pack_called = assemble_external_context_pack(
                artifact,
                provider_artifact,
                self._providers.get(contract["provider_uri"]),
                aliases=aliases,
                requested_time=windows,
            )
            packs.append(public_context_reference(pack))
            called = called or pack_called
            identity = contract["requirement_id"]
            if identity in required:
                reasons.extend(_required_pack_reasons(pack))
            if not pack["claims"]["optional_context_complete"]:
                complete = False
            if identity in optional and not _optional_pack_complete(pack):
                complete = False
        return packs, reasons, complete, called


def _project_root(workspace: Any) -> Path:
    supplied = getattr(workspace, "root", None)
    if supplied is None:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID", "Project root is unavailable"
        )
    return Path(supplied).resolve()


def _dependency_set(values: Sequence[str], label: str) -> set[str]:
    if (
        isinstance(values, (str, bytes))
        or any(not isinstance(item, str) or not item for item in values)
        or len(values) != len(set(values))
    ):
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_BINDING_INVALID",
            f"External {label} Context dependencies are invalid",
        )
    return set(values)


def _load_bindings(
    root: Path, required: Sequence[str], optional: Sequence[str]
) -> dict[str, Any]:
    try:
        return load_external_context_bindings(root)
    except ExternalContextBindingError as exc:
        if exc.reason_code != "EXTERNAL_CONTEXT_BINDING_MISSING":
            raise
        return _resolution(
            [],
            [],
            ["CONTEXT_REQUIRED_MISSING"] if required else [],
            not bool(optional),
            False,
        )


def _is_binding_registry(value: Mapping[str, Any]) -> bool:
    return "requirements" in value and "providers" in value and "source_revision" in value


def _selected_requirements(
    bindings: Mapping[str, Any],
    target: set[str],
    *,
    skill_uri: str,
    journey_id: str,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for identity in sorted(target):
        artifact = bindings["requirements"].get(identity)
        if artifact is None:
            continue
        contract = artifact["contract"]
        if contract["skill_uri"] != skill_uri or contract["journey_id"] != journey_id:
            raise ExternalContextBindingError(
                "EXTERNAL_CONTEXT_BINDING_CONFLICT",
                "External requirement exceeds its exact Skill/Journey boundary",
            )
        selected.append(artifact)
    return selected


def _required_pack_reasons(pack: Mapping[str, Any]) -> list[str]:
    reasons = (
        [gap["reason_code"] for gap in pack["gaps"] if gap["required"]]
        if pack["status"] == "blocked"
        else []
    )
    if not pack["claims"]["confirmed_claims_allowed"]:
        reasons.append("CONTEXT_AUTHORITY_INSUFFICIENT")
    return reasons


def _optional_pack_complete(pack: Mapping[str, Any]) -> bool:
    return pack["status"] == "available" and pack["claims"]["confirmed_claims_allowed"]


def _provider_instances(providers: Sequence[Any]) -> dict[str, Any]:
    if isinstance(providers, (str, bytes)):
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_PROVIDER_INVALID", "Providers must be explicit instances"
        )
    result: dict[str, Any] = {}
    for provider in providers:
        identity, digest = _provider_identity(provider)
        if identity in result:
            raise ExternalContextBindingError(
                "EXTERNAL_CONTEXT_PROVIDER_CONFLICT", "Provider identity is duplicated"
            )
        result[identity] = {"provider": provider, "digest": digest}
    return result


def _provider_identity(provider: Any) -> tuple[str, str]:
    try:
        description = provider.describe()
        identity = description["provider"]["uri"]
        digest = description["provider_digest"]
    except (AttributeError, KeyError, TypeError) as exc:
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_PROVIDER_INVALID", "Provider description is invalid"
        ) from exc
    if not isinstance(identity, str) or not is_sha256(digest):
        raise ExternalContextBindingError(
            "EXTERNAL_CONTEXT_PROVIDER_INVALID", "Provider identity or digest is invalid"
        )
    return identity, digest


def _resolution(
    packs: Sequence[Mapping[str, Any]],
    bound: Sequence[str],
    reasons: Sequence[str],
    optional_complete: bool,
    provider_rpc_called: bool,
) -> dict[str, Any]:
    selected_reasons = list(dict.fromkeys(reasons))
    return {
        "schema_version": RESOLUTION_SCHEMA_VERSION,
        "status": "resolved" if not selected_reasons else "blocked",
        "ok": not selected_reasons,
        "context_packs": [copy.deepcopy(dict(item)) for item in packs],
        "bound_dependencies": sorted(bound),
        "reason_codes": selected_reasons,
        "optional_context_complete": optional_complete,
        "provider_rpc_called": provider_rpc_called,
        "provider_internal_io_controlled": False,
        "provider_internal_network": "not_observable",
        "network_called": False,
    }


__all__ = [
    "BINDINGS_FILENAME",
    "ExternalContextBindingError",
    "ExternalContextBindingResolver",
    "RESOLUTION_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "compile_external_context_bindings",
    "load_external_context_bindings",
]
