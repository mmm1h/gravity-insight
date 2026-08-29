"""Run the frozen R10 MCP development questions against an offline surrogate."""

from __future__ import annotations

import argparse
import copy
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
from typing import Any

from gravity_sdk.mcp.server import MCPServer, PROTOCOL_VERSION


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = ROOT / "tests/fixtures/mcp_host_development_questions.json"
DEFAULT_OUTPUT = ROOT / "tests/fixtures/mcp_host_development_evidence.json"
EVIDENCE_SCHEMA_VERSION = "gravity.mcp-host-development-evidence.v1"
SELECTOR_ID = "gravity.schema-aware-lexical-selector.v1"
_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "before",
        "but",
        "can",
        "current",
        "for",
        "from",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "one",
        "or",
        "the",
        "this",
        "through",
        "to",
        "which",
        "with",
    }
)


class OfflineCounter:
    def __init__(self) -> None:
        self.internal_http_requests = 0


class OfflineTrust:
    def trust(self, identity_kind: str, selector: str) -> dict[str, Any]:
        return {
            "schema_version": "gravity.capability-trust-result.v1",
            "status": "success",
            "identity_kind": identity_kind,
            "selector": selector,
            "trust_status": "stable",
            "reason_codes": [],
            "network_called": False,
        }


class OfflineJourneys:
    _IDS = ("analysis.event-trend", "analysis.example")

    def list(self) -> dict[str, Any]:
        return {
            "schema_version": "gravity.journey-list.v1",
            "status": "success",
            "count": len(self._IDS),
            "journeys": [
                {"journey_id": value, "version": 1, "lifecycle": "active"}
                for value in self._IDS
            ],
            "network_called": False,
        }

    def describe(self, journey_id: str) -> dict[str, Any]:
        return {
            "schema_version": "gravity.journey-description.v1",
            "status": "success",
            "journey": {"journey_id": journey_id, "version": 1},
            "network_called": False,
        }

    def can_run(
        self, journey_id: str, inputs: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "schema_version": "gravity.journey-can-run.v1",
            "ok": True,
            "status": "success",
            "exit_code": 0,
            "journey": {"journey_id": journey_id, "version": 1},
            "inputs": dict(inputs or {}),
            "can_run_status": "verified",
            "reason_codes": [],
            "network_called": False,
        }

    def run(self, journey_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        result = _synthetic_analysis_result()
        result["journey"] = {"journey_id": journey_id, "version": 1}
        result["scope"] = dict(inputs)
        return result


class OfflineArtifacts:
    def compile(self, analysis_result: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "gravity.analysis-artifact.v1",
            "status": "success",
            "analysis_result": copy.deepcopy(dict(analysis_result)),
        }

    def write_artifact(
        self, artifact: Mapping[str, Any], destination: str
    ) -> dict[str, Any]:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, artifact)
        return {
            "schema_version": "gravity.analysis-artifact-write.v1",
            "status": "written",
            "path": str(path),
            "network_called": False,
        }

    def write_markdown(
        self,
        artifact: Mapping[str, Any],
        destination: str,
        *,
        max_bytes: int,
    ) -> dict[str, Any]:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "# Offline Analysis\n\nStatus: success\n"
        if len(text.encode("utf-8")) > max_bytes:
            raise ValueError("Markdown output exceeds the requested budget")
        path.write_text(text, encoding="utf-8", newline="\n")
        return {
            "schema_version": "gravity.analysis-artifact-write.v1",
            "status": "written",
            "path": str(path),
            "network_called": False,
        }


class OfflineSDK:
    def __init__(self, root: Path, counter: OfflineCounter) -> None:
        self.workspace = SimpleNamespace(
            root=root,
            state_root=root / "state",
            apps={"demo": 7},
        )
        self.counter = counter
        self.capability_trust = OfflineTrust()
        self.journeys = OfflineJourneys()
        self.analysis_artifacts = OfflineArtifacts()

    def capabilities(self, **_options: Any) -> dict[str, Any]:
        return {
            "schema_version": "gravity.agent-capabilities.v1",
            "status": "success",
            "candidates": [],
            "network_called": False,
        }

    def describe_sql_products(self) -> list[dict[str, Any]]:
        return [{"name": "offline-demo", "status": "registered"}]

    def list_http_receipts(self, **_options: Any) -> dict[str, Any]:
        return {
            "schema_version": "gravity.http-receipt-list.v1",
            "status": "success",
            "receipts": [],
            "network_called": False,
        }

    def saved_analyses(self, app: str, **_options: Any) -> dict[str, Any]:
        return {
            "schema_version": "gravity.saved-analysis-list.v1",
            "status": "success",
            "app": app,
            "items": [],
            "network_called": False,
        }

    def table_lineage(self, query: str, **_options: Any) -> dict[str, Any]:
        return {
            "schema_version": "gravity.table-lineage-result.v1",
            "status": "success",
            "query": query,
            "items": [],
            "network_called": False,
        }

    def analysis_vocabulary(self, query: str, **_options: Any) -> dict[str, Any]:
        return {
            "schema_version": "gravity.analysis-vocabulary-result.v1",
            "status": "success",
            "query": query,
            "items": [],
            "network_called": False,
        }


def _synthetic_analysis_result() -> dict[str, Any]:
    return {
        "schema_version": "gravity.analysis-result.v1",
        "ok": True,
        "status": "success",
        "exit_code": 0,
        "question": "Offline development fixture",
        "journey": {"journey_id": "analysis.example", "version": 1},
        "scope": {},
        "findings": [],
        "limitations": ["Synthetic offline development result."],
        "allowed_claims": [],
        "forbidden_claims": [],
        "network_called": False,
    }


def _metadata() -> dict[str, Any]:
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {
            "name": SELECTOR_ID,
            "version": "1",
        },
        "io.modelcontextprotocol/clientCapabilities": {},
    }


class EvaluationSession:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.counter = OfflineCounter()
        self.server = MCPServer(OfflineSDK(root, self.counter))
        self.rpc_count = 0
        self._request_id = 0
        self.context_root = root / "context-repo"
        self._prepare_context_repo()

    def rpc(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.rpc_count += 1
        self._request_id += 1
        selected = dict(params or {})
        selected["_meta"] = _metadata()
        response = self.server.process_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": selected,
                }
            )
        )
        if response is None:
            raise AssertionError("Evaluation RPC unexpectedly returned no response")
        return response

    def candidates(self) -> list[dict[str, Any]]:
        self.rpc("server/discover")
        tools = self.rpc("tools/list")["result"]["tools"]
        resources: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = self.rpc(
                "resources/list", {"cursor": cursor} if cursor is not None else {}
            )["result"]
            resources.extend(page["resources"])
            cursor = page.get("nextCursor")
            if cursor is None:
                break
        templates = self.rpc("resources/templates/list")["result"][
            "resourceTemplates"
        ]
        return [
            *_tool_candidates(tools),
            *(_resource_candidate(item["uri"], item) for item in resources),
            *(
                _resource_candidate(item["uriTemplate"], item)
                for item in templates
            ),
        ]

    def materialize_request(self, case: Mapping[str, Any]) -> dict[str, Any]:
        request = copy.deepcopy(dict(case["request"]))
        if "arguments" in request:
            request["arguments"] = self._materialize(
                request["arguments"], str(case["case_id"])
            )
        return request

    def output_path(self, case_id: str, format_name: str) -> Path:
        suffix = ".json" if format_name == "json" else ".md"
        return self.root / "outputs" / f"{case_id}{suffix}"

    def _materialize(self, value: Any, case_id: str) -> Any:
        if isinstance(value, Mapping) and set(value) == {"$fixture"}:
            fixture = value["$fixture"]
            if fixture == "synthetic_success":
                return _synthetic_analysis_result()
            if fixture == "temporary_output":
                format_name = "markdown" if "markdown" in case_id else "json"
                return str(self.output_path(case_id, format_name))
            if fixture == "repo_context_pack":
                return self._context_pack_arguments()
            raise AssertionError(f"Unknown evaluation fixture: {fixture}")
        if isinstance(value, Mapping):
            return {key: self._materialize(item, case_id) for key, item in value.items()}
        if isinstance(value, list):
            return [self._materialize(item, case_id) for item in value]
        return value

    def _prepare_context_repo(self) -> None:
        self.context_root.mkdir(parents=True)
        docs = self.context_root / "docs"
        docs.mkdir()
        (docs / "context.md").write_text(
            "# Current context\n", encoding="utf-8", newline="\n"
        )
        commands = (
            ("git", "init", "-q"),
            ("git", "config", "core.autocrlf", "false"),
            ("git", "config", "user.email", "offline@example.invalid"),
            ("git", "config", "user.name", "Offline Evaluation"),
            ("git", "add", "docs/context.md"),
            ("git", "commit", "-q", "-m", "offline context"),
        )
        for command in commands:
            subprocess.run(command, cwd=self.context_root, check=True)

    def _context_pack_arguments(self) -> dict[str, Any]:
        return {
            "root": str(self.context_root),
            "project_id": "demo",
            "requirement": {
                "artifact_kind": "context_requirement",
                "schema_version": "gravity.context-requirement.v1",
                "requirement_id": "context://demo/runtime-boundaries@1",
                "provider_uri": "context-provider://gravity/project-repo@1",
                "skill_uri": "gravity.game/demo@1.0.0",
                "journey_id": "analysis.example",
                "subject_entities": ["app://project/demo"],
                "required_windows": ["current"],
                "authority_policy": {
                    "required": ["canonical"],
                    "allow_supporting": True,
                    "allow_unverified": False,
                },
                "allowed_sensitivity": ["internal"],
                "freshness_policy": {"as_of": None, "max_age_days": None},
                "budget": {
                    "max_files": 8,
                    "max_file_bytes": 262144,
                    "max_total_bytes": 524288,
                    "max_total_lines": 1000,
                },
                "items": [
                    {
                        "item_id": "current",
                        "fact_id": "fact.demo",
                        "required": True,
                        "path": "docs/context.md",
                        "title": "current",
                        "resource_type": "document",
                        "entity_refs": ["app://project/demo"],
                        "valid_time": {
                            "start": None,
                            "end": None,
                            "timezone": "Asia/Shanghai",
                        },
                        "effective_range": {"start": None, "end": None},
                        "authority": "canonical",
                        "sensitivity": "internal",
                        "supersedes": [],
                        "max_age_days": None,
                    }
                ],
            },
            "requested_time": {
                "current": {
                    "start": "2026-08-18",
                    "end": "2026-08-20",
                    "timezone": "Asia/Shanghai",
                }
            },
            "entity_aliases": {
                "app://project/demo": "entity://gravity/app@1"
            },
        }


def _tool_candidates(tools: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for tool in tools:
        name = str(tool["name"])
        schema = tool["inputSchema"]
        variants = _schema_variants(schema)
        for variant, selected_schema in variants:
            visible = " ".join(
                (
                    name,
                    str(tool.get("title", "")),
                    str(tool.get("description", "")),
                    json.dumps(selected_schema, sort_keys=True),
                    f"variant {variant} {variant}",
                )
            )
            candidates.append(
                {
                    "identity": f"tool:{name}:{variant}",
                    "method": "tools/call",
                    "name": name,
                    "variant": variant,
                    "visible_text": visible,
                }
            )
    return candidates


def _schema_variants(schema: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    branches = schema.get("oneOf")
    if isinstance(branches, list):
        selected = []
        for branch in branches:
            constants = [
                str(value["const"])
                for value in branch.get("properties", {}).values()
                if isinstance(value, Mapping) and "const" in value
            ]
            selected.append(("-".join(constants) or "default", branch))
        return selected
    for value in schema.get("properties", {}).values():
        if isinstance(value, Mapping) and isinstance(value.get("enum"), list):
            return [
                (str(option), {**schema, "selected_variant": str(option)})
                for option in value["enum"]
            ]
    return [("default", schema)]


def _resource_candidate(uri: str, descriptor: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "identity": f"resource:{uri}",
        "method": "resources/read",
        "uri": uri,
        "visible_text": " ".join(
            (
                uri,
                str(descriptor.get("name", "")),
                str(descriptor.get("description", "")),
                "resource read",
            )
        ),
    }


def _tokens(value: str) -> Counter[str]:
    words = (
        word
        for word in _WORD.findall(str(value).casefold().replace("_", " "))
        if len(word) >= 2 and word not in _STOP_WORDS
    )
    return Counter(words)


def select_first_choice(
    question: str, candidates: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    query = _tokens(question)
    documents = [_tokens(str(item["visible_text"])) for item in candidates]
    frequencies = Counter(term for document in documents for term in document)
    idf = {
        term: math.log((len(documents) + 1) / (count + 1)) + 1.0
        for term, count in frequencies.items()
    }
    unseen = math.log(len(documents) + 1) + 1.0
    denominator = sum(idf.get(term, unseen) * count for term, count in query.items())
    scored = []
    for candidate, document in zip(candidates, documents, strict=True):
        matched = tuple(sorted(set(query) & set(document)))
        numerator = sum(
            idf[term] * min(query[term], document[term]) for term in matched
        )
        score = numerator / denominator if denominator else 0.0
        scored.append((score, str(candidate["identity"]), matched, candidate))
    score, _identity, matched, selected = min(
        scored, key=lambda item: (-item[0], item[1])
    )
    return {
        **dict(selected),
        "score": round(score, 6),
        "matched_terms": list(matched),
    }


def _execute_choice(
    session: EvaluationSession,
    selected: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    if selected["method"] == "tools/call":
        return session.rpc(
            "tools/call",
            {
                "name": selected["name"],
                "arguments": request.get("arguments", {}),
            },
        )
    uri = str(selected["uri"])
    if "{" not in uri and request.get("method") == "resources/read":
        requested_uri = str(request["uri"])
        if selected["identity"] == f"resource:{requested_uri}":
            uri = requested_uri
    elif selected["identity"].startswith("resource:"):
        expected_identity = _template_identity(str(request.get("uri", "")))
        if selected["identity"] == expected_identity:
            uri = str(request["uri"])
    return session.rpc("resources/read", {"uri": uri})


def _template_identity(uri: str) -> str:
    if uri.startswith("gravity://metadata/table-lineage/"):
        return "resource:gravity://metadata/table-lineage/{query}"
    if uri.startswith("gravity://workspace/analysis-vocabulary/"):
        return "resource:gravity://workspace/analysis-vocabulary/{query}"
    return f"resource:{uri}"


def _legal_answer(
    rule: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    first_choice_correct: bool,
    output_path: Path | None,
) -> tuple[bool, str]:
    if not first_choice_correct:
        return False, "first_choice_incorrect"
    if "error" in response:
        return False, "json_rpc_error"
    kind = rule["kind"]
    result = response.get("result", {})
    if kind == "resource_content":
        contents = result.get("contents", [])
        if not contents:
            return False, "resource_content_missing"
        try:
            decoded = json.loads(contents[0]["text"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return False, "resource_content_invalid"
        return (
            isinstance(decoded, Mapping) and "schema_version" in decoded,
            "resource_content" if "schema_version" in decoded else "resource_schema_missing",
        )
    structured = result.get("structuredContent", {})
    domain = structured.get("result", {})
    if kind == "tool_error":
        error = domain.get("error", {})
        local_write_ok = output_path is None or not output_path.exists()
        passed = (
            bool(result.get("isError"))
            and error.get("code") == rule["code"]
            and local_write_ok
        )
        return passed, str(error.get("code") or "tool_error_missing")
    passed = (
        bool(result.get("isError")) is bool(rule["is_error"])
        and domain.get("status") == rule["status"]
    )
    return passed, str(domain.get("status") or "tool_status_missing")


def evaluate(questions_path: Path = DEFAULT_QUESTIONS) -> dict[str, Any]:
    questions_bytes = questions_path.read_bytes()
    suite = json.loads(questions_bytes.decode("utf-8"))
    if suite.get("schema_version") != "gravity.mcp-host-development-questions.v1":
        raise ValueError("Unsupported MCP development question schema")
    cases = suite.get("cases")
    if not isinstance(cases, list) or len(cases) != 20:
        raise ValueError("The frozen MCP development suite must contain exactly 20 cases")

    records = []
    first_choice_count = 0
    legal_answer_count = 0
    total_rpcs = 0
    total_http = 0
    with tempfile.TemporaryDirectory(prefix="gravity-mcp-development-") as directory:
        base = Path(directory)
        for index, case in enumerate(cases, start=1):
            session = EvaluationSession(base / f"case-{index:02d}")
            initial_rpcs = session.rpc_count
            initial_http = session.counter.internal_http_requests
            candidates = session.candidates()
            selected = select_first_choice(str(case["question"]), candidates)
            first_correct = selected["identity"] == case["expected_first_choice"]
            request = session.materialize_request(case)
            output_path = None
            if request.get("method") == "tools/call" and request.get("name") == "gravity.export":
                arguments = request.get("arguments", {})
                destination = arguments.get("destination")
                if isinstance(destination, str):
                    output_path = Path(destination)
            response = _execute_choice(session, selected, request)
            legal, terminal = _legal_answer(
                case["legal_answer"],
                response,
                first_choice_correct=first_correct,
                output_path=output_path,
            )
            rpc_count = session.rpc_count - initial_rpcs
            http_count = session.counter.internal_http_requests - initial_http
            first_choice_count += int(first_correct)
            legal_answer_count += int(legal)
            total_rpcs += rpc_count
            total_http += http_count
            records.append(
                {
                    "case_id": case["case_id"],
                    "question": case["question"],
                    "expected_first_choice": case["expected_first_choice"],
                    "observed_first_choice": selected["identity"],
                    "first_choice_correct": first_correct,
                    "selection_score": selected["score"],
                    "matched_terms": selected["matched_terms"],
                    "legal_answer": legal,
                    "terminal": terminal,
                    "mcp_rpcs": rpc_count,
                    "internal_http_requests": http_count,
                }
            )

    thresholds = suite["thresholds"]
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "suite_id": suite["suite_id"],
        "suite_sha256": hashlib.sha256(questions_bytes).hexdigest(),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluator": {
            "selector_id": SELECTOR_ID,
            "kind": "offline_schema_aware_lexical_surrogate",
            "real_host": False,
            "host_specific_prompt": False,
            "declared_real_host_versions": suite["host_matrix"][
                "declared_real_host_versions"
            ],
            "limitation": suite["host_matrix"]["limitation"],
        },
        "summary": {
            "case_count": len(cases),
            "first_choice_correct": first_choice_count,
            "first_choice_minimum": thresholds["first_choice_minimum"],
            "first_choice_pass": first_choice_count
            >= thresholds["first_choice_minimum"],
            "legal_answers": legal_answer_count,
            "legal_answer_minimum": thresholds["legal_answer_minimum"],
            "legal_answer_pass": legal_answer_count
            >= thresholds["legal_answer_minimum"],
            "mcp_rpcs": total_rpcs,
            "internal_http_requests": total_http,
            "production_http_requests": 0,
        },
        "cases": records,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=False)
        stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    options = parser.parse_args(argv)
    evidence = evaluate(options.questions)
    _write_json(options.output, evidence)
    print(json.dumps(evidence["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
