from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.build_offline_wheel import build_or_reuse_offline_wheel
except ModuleNotFoundError:
    from build_offline_wheel import build_or_reuse_offline_wheel


ROOT = Path(__file__).resolve().parents[1]
SURFACES = ("cli", "sdk", "plan", "agent", "mcp")

_PROBE = r'''
import copy
import json
import pathlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

site = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(site))

import gravity_insight
from gravity_insight import GravitySDK
from gravity_insight.agents.handoff import attach_plan_node
from gravity_insight.journey_cli import dispatch as journey_dispatch
from gravity_insight.journey_contract import journey_artifact
from gravity_insight.mcp.server import MCPServer, PROTOCOL_VERSION
from gravity_insight.plan import PlanAdapter, PlanAdapters, execute_plan

package_path = pathlib.Path(gravity_insight.__file__).resolve()
if not package_path.is_relative_to(site):
    raise AssertionError(f"gravity_insight escaped installed wheel: {package_path}")


class CommonJourneyService:
    def __init__(self):
        self.calls = []

    def run(self, journey_id, inputs):
        self.calls.append((journey_id, copy.deepcopy(inputs)))
        success = journey_id == "analysis.readable-app-catalog"
        return {
            "schema_version": "gravity.surface-matrix-result.v1",
            "ok": success,
            "status": "success" if success else "capability_gap",
            "exit_code": 0 if success else 4,
            "journey": {"journey_id": journey_id, "version": 1},
            "can_run_status": "verified" if success else "blocked",
            "reason_codes": [] if success else ["COMPLETENESS_INSUFFICIENT"],
            "completeness": "complete" if success else "unknown",
            "observation_count": 1 if success else 0,
            "network_called": False,
        }


workspace = SimpleNamespace(root=pathlib.Path.cwd(), state_root=pathlib.Path.cwd())
sdk = GravitySDK(workspace=workspace)
service = CommonJourneyService()
sdk._journey_service = service


class SDKFactory:
    def __new__(cls, **_options):
        return sdk

    @classmethod
    def from_env(cls, **_options):
        return sdk


def signature(value):
    return {
        "schema_version": value["schema_version"],
        "ok": value["ok"],
        "status": value["status"],
        "exit_code": value["exit_code"],
        "journey_id": value["journey"]["journey_id"],
        "can_run_status": value["can_run_status"],
        "reason_codes": value["reason_codes"],
        "completeness": value["completeness"],
        "observation_count": value["observation_count"],
        "network_called": value["network_called"],
    }


def cli_run(case):
    args = SimpleNamespace(
        journey_command="run",
        journey_id=case["journey_id"],
        input="case-input",
        workspace=None,
    )
    with (
        patch("gravity_insight.sdk.GravitySDK", SDKFactory),
        patch("gravity_insight.workspace.load_workspace", return_value=workspace),
    ):
        return journey_dispatch(args, lambda _value: copy.deepcopy(case["inputs"]))


def plan_adapter():
    def validate(request, _context):
        if set(request) != {"selector", "journey_id", "inputs"}:
            raise ValueError(
                "matrix plan request must contain selector, journey_id, and inputs"
            )

    def run(request, _context):
        return sdk.journeys.run(request["journey_id"], request["inputs"])

    return PlanAdapter(
        run,
        validate,
        preserve_partial=True,
        preserve_capability_gap=True,
    )


def execute_node(node):
    result = execute_plan(
        {"schema_version": "gravity.plan.v1", "nodes": [node]},
        adapters=PlanAdapters(run=plan_adapter()),
        workspace=workspace,
        max_workers=1,
    )
    inner = result["results"][0]["result"]
    if inner is None:
        raise AssertionError(f"matrix Plan discarded semantic failure: {result}")
    return inner


def plan_run(case):
    return execute_node({
        "id": "common-journey",
        "kind": "run",
        "request": {
            "selector": case["journey_id"],
            "journey_id": case["journey_id"],
            "inputs": copy.deepcopy(case["inputs"]),
        },
        "limits": {"max_pages": 1, "max_items": 1},
    })


def agent_run(case):
    card = attach_plan_node(
        {
            "kind": "operation",
            "selector": case["journey_id"],
            "operation_id": case["journey_id"],
            "plan_executable": True,
            "required_inputs": [],
            "input_schema": {},
            "input_template": {},
            "effect": "read",
        },
        "run the exact common Journey",
    )
    node = copy.deepcopy(card["plan_node"])
    node["request"] = {
        "selector": case["journey_id"],
        "journey_id": case["journey_id"],
        "inputs": copy.deepcopy(case["inputs"]),
    }
    node["limits"] = {"max_pages": 1, "max_items": 1}
    return execute_node(node)


def mcp_run(case):
    response = MCPServer(sdk).handle({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "gravity.execute",
            "arguments": {
                "journey_id": case["journey_id"],
                "inputs": copy.deepcopy(case["inputs"]),
            },
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "integrated-validation",
                    "version": "1",
                },
            },
        },
    })
    return response["result"]["structuredContent"]["result"]


cases = [
    {
        "case_id": "local-success",
        "journey_id": "analysis.readable-app-catalog",
        "inputs": {"scope": "local-fixture"},
        "expected_status": "success",
    },
    {
        "case_id": "fail-closed",
        "journey_id": "analysis.event-trend",
        "inputs": {},
        "expected_status": "capability_gap",
    },
]
results = []
for case in cases:
    contract = journey_artifact(case["journey_id"])["contract"]
    if set(contract["surfaces"]) != {"cli", "sdk", "plan", "agent"}:
        raise AssertionError(f"incomplete declared surfaces: {contract['surfaces']}")
    if any(value != "available" for value in contract["surfaces"].values()):
        raise AssertionError(f"unavailable declared surface: {contract['surfaces']}")
    values = {
        "cli": cli_run(case),
        "sdk": sdk.journeys.run(case["journey_id"], copy.deepcopy(case["inputs"])),
        "plan": plan_run(case),
        "agent": agent_run(case),
        "mcp": mcp_run(case),
    }
    signatures = {name: signature(value) for name, value in values.items()}
    baseline = signatures["sdk"]
    if any(value != baseline for value in signatures.values()):
        raise AssertionError(f"surface semantic drift: {signatures}")
    if baseline["status"] != case["expected_status"]:
        raise AssertionError(f"unexpected case status: {baseline}")
    results.append({
        "case_id": case["case_id"],
        "journey_id": case["journey_id"],
        "semantic_signature": baseline,
        "surfaces": {name: "passed" for name in signatures},
    })

print(json.dumps({
    "schema_version": "gravity.installed-wheel-surface-matrix.v1",
    "passed": True,
    "installed_package": str(package_path),
    "surface_count": 5,
    "case_count": len(results),
    "owner_call_count": len(service.calls),
    "network_calls": 0,
    "cases": results,
}, sort_keys=True))
'''


class SurfaceMatrixError(RuntimeError):
    pass


def semantic_signature(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": value["schema_version"],
        "ok": value["ok"],
        "status": value["status"],
        "exit_code": value["exit_code"],
        "journey_id": value["journey"]["journey_id"],
        "can_run_status": value["can_run_status"],
        "reason_codes": value["reason_codes"],
        "completeness": value["completeness"],
        "observation_count": value["observation_count"],
        "network_called": value["network_called"],
    }


def _run(command: list[str], *, cwd: Path, timeout: int = 300) -> str:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(
        command,
        cwd=cwd,
        env={**environment, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise SurfaceMatrixError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout


def _selected_wheel(wheel: Path | None, wheelhouse: Path) -> Path:
    if wheel is None:
        return build_or_reuse_offline_wheel(ROOT, wheelhouse)
    resolved = wheel.resolve()
    if not resolved.is_file() or resolved.suffix != ".whl":
        raise SurfaceMatrixError(f"installed-wheel input is not a wheel file: {resolved}")
    return resolved


def run_surface_matrix(wheel: Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gravity-surface-matrix-") as raw:
        temporary = Path(raw).resolve()
        wheelhouse = temporary / "wheelhouse"
        site = temporary / "site"
        wheelhouse.mkdir()
        site.mkdir()
        selected_wheel = _selected_wheel(wheel, wheelhouse)
        install_command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--no-deps",
        ]
        # Maintainer gates may run above the public <3.13 compatibility range.
        if sys.version_info >= (3, 13):
            install_command.append("--ignore-requires-python")
        install_command.extend(["--target", str(site), str(selected_wheel)])
        _run(install_command, cwd=temporary)
        output = _run(
            [sys.executable, "-I", "-X", "utf8", "-c", _PROBE, str(site)],
            cwd=temporary,
        )
        try:
            result = json.loads(output)
        except json.JSONDecodeError as exc:
            raise SurfaceMatrixError("surface matrix probe returned invalid JSON") from exc
        result["wheel"] = selected_wheel.name
        result["wheel_sha256"] = hashlib.sha256(selected_wheel.read_bytes()).hexdigest()
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run five-surface Journey parity against one installed wheel."
    )
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_surface_matrix(args.wheel)
        if args.receipt is not None:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    except (OSError, SurfaceMatrixError, subprocess.SubprocessError) as exc:
        print(f"installed wheel surface matrix failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
