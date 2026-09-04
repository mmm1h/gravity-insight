"""Deterministic Repository Map generation and task-context projection API."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "src/gravity_insight/contracts/generated/repository-map.v2.json"
MAP_SCHEMA = "repository-map-v2.schema.json"
MAP_FACT_SCHEMA = "repository-map-v1.schema.json"
PACK_SCHEMA = "task-context-pack-v1.schema.json"
MAP_ENCODINGS = {
    "entries": "columnar-string-table-negative-index.v1",
    "issue_index": "path-table-location-tuples.v1",
    "module_graph": "node-table-adjacency-index.v1",
}
COMPONENT_INDEX = ROOT / "specs/agent-runtime/index.json"
DEBT_PATH = ROOT / "docs/maintainers/technical-debt.md"
ARCHITECTURE_PATH = ROOT / "docs/architecture.md"
HISTORY_PREFIXES = ("docs/archive/", "archive/", "history/")
RISK_LEVELS = {"low": 0, "medium": 1, "high": 2}
RISK_REVIEW_MODES = {
    "low": "self_review",
    "medium": "independent_review",
    "high": "adversarial_review",
}
_HIGH_RISK_PREFIXES = (
    ".github/workflows/",
    "specs/agent-runtime/",
    "src/gravity_insight/agents/",
    "src/gravity_insight/contracts/",
)
_HIGH_RISK_EXACT_PATHS = {
    "AGENTS.md",
    "docs/architecture.md",
    "pyproject.toml",
    "scripts/run_integrated_validation.py",
    "src/gravity_insight/plan_adapters.py",
}
_HIGH_RISK_PATH_TERMS = (
    "auth",
    "concurr",
    "control_plane",
    "credential",
    "degrad",
    "error",
    "failure",
    "fallback",
    "http_",
    "mutation",
    "pagination",
    "permission",
    "privacy",
    "provenance",
    "retry",
    "route",
    "security",
    "transport",
)
_LOW_RISK_PREFIXES = (
    "content/",
    "docs/",
    "skills/",
    "tests/",
)
_LOW_RISK_EXACT_PATHS = {"README.md", "SECURITY.md"}
REQUIRED_MAP_FIELDS = (
    "domain",
    "capability",
    "skill",
    "journey",
    "owner",
    "public_surfaces",
    "dependencies",
    "schema",
    "tests",
    "current_docs",
    "issue",
    "debt",
    "maturity",
    "token_estimate",
    "byte_estimate",
)
_ISSUE_PATTERN = re.compile(r"(?<![\w/])(?:#\s*|Issue\s+)(\d{1,6})\b", re.I)
_DEBT_HEADING = re.compile(r"^###\s+(\d+)\.\s+(.+?)\s*$", re.M)
_CJK_PATTERN = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]"
)


class RepositoryMapError(ValueError):
    """Raised when a map cannot be derived or queried safely."""


def _posix(path: Path, root: Path = ROOT) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _is_history(relative: str) -> bool:
    normalized = PurePosixPath(relative.replace("\\", "/")).as_posix()
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in HISTORY_PREFIXES)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RepositoryMapError(f"expected JSON object: {_posix(path)}")
    return value


def canonical_json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    if pretty:
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _string_values(item)


def _encode_entry_value(value: Any, indexes: Mapping[str, int]) -> Any:
    if isinstance(value, str):
        return -(indexes[value] + 1)
    if isinstance(value, list):
        return [_encode_entry_value(item, indexes) for item in value]
    if isinstance(value, Mapping):
        return {
            key: _encode_entry_value(item, indexes)
            for key, item in value.items()
        }
    return value


def _decode_entry_value(value: Any, strings: Sequence[str]) -> Any:
    if isinstance(value, int) and not isinstance(value, bool) and value < 0:
        index = -value - 1
        if index >= len(strings):
            raise RepositoryMapError(f"entry string index is out of range: {index}")
        return strings[index]
    if isinstance(value, list):
        return [_decode_entry_value(item, strings) for item in value]
    if isinstance(value, Mapping):
        return {
            key: _decode_entry_value(item, strings)
            for key, item in value.items()
        }
    return value


def encode_repository_map(document: Mapping[str, Any]) -> dict[str, Any]:
    """Encode the v1 fact model as the compact v2 whole-file transport."""

    if document.get("schema_version") != "gravity.repository-map.v1":
        raise RepositoryMapError("repository map facts must use gravity.repository-map.v1")
    entries = list(document["entries"])
    fields = sorted(entries[0]) if entries else []
    if any(sorted(entry) != fields for entry in entries):
        raise RepositoryMapError("repository map entries do not share one field set")
    strings = sorted(set(_string_values(entries)))
    string_indexes = {value: index for index, value in enumerate(strings)}

    issue_index = document["issue_index"]
    paths = sorted(
        {
            location["path"]
            for locations in issue_index.values()
            for location in locations
        }
    )
    path_indexes = {value: index for index, value in enumerate(paths)}

    graph = document["module_graph"]
    adjacency = graph["edges"]
    nodes = sorted(adjacency)
    node_indexes = {value: index for index, value in enumerate(nodes)}
    missing_targets = sorted(
        {
            target
            for targets in adjacency.values()
            for target in targets
            if target not in node_indexes
        }
    )
    if missing_targets:
        raise RepositoryMapError(
            "module graph targets are absent from the node table: "
            + ", ".join(missing_targets)
        )

    return {
        **{
            key: value
            for key, value in document.items()
            if key not in {"entries", "issue_index", "module_graph", "schema_version"}
        },
        "schema_version": "gravity.repository-map.v2",
        "encoding": dict(MAP_ENCODINGS),
        "entries": {
            "fields": fields,
            "strings": strings,
            "rows": [
                [_encode_entry_value(entry[field], string_indexes) for field in fields]
                for entry in entries
            ],
        },
        "issue_index": {
            "paths": paths,
            "issues": {
                issue: [
                    [path_indexes[location["path"]], location["line"]]
                    for location in locations
                ]
                for issue, locations in issue_index.items()
            },
        },
        "module_graph": {
            **{key: value for key, value in graph.items() if key != "edges"},
            "nodes": nodes,
            "edges": [
                [node_indexes[target] for target in adjacency[node]]
                for node in nodes
            ],
        },
    }


def decode_repository_map(document: Mapping[str, Any]) -> dict[str, Any]:
    """Restore every v1 fact from a compact v2 Repository Map transport."""

    if document.get("schema_version") != "gravity.repository-map.v2":
        raise RepositoryMapError("repository map transport must use gravity.repository-map.v2")
    if document.get("encoding") != MAP_ENCODINGS:
        raise RepositoryMapError("repository map transport encoding is unsupported")

    encoded_entries = document["entries"]
    fields = encoded_entries["fields"]
    strings = encoded_entries["strings"]
    if fields != sorted(set(fields)):
        raise RepositoryMapError("entry fields must be sorted and unique")
    if strings != sorted(set(strings)):
        raise RepositoryMapError("entry strings must be sorted and unique")
    entries: list[dict[str, Any]] = []
    for row in encoded_entries["rows"]:
        if len(row) != len(fields):
            raise RepositoryMapError("entry row length differs from the field table")
        entries.append(
            {
                field: _decode_entry_value(value, strings)
                for field, value in zip(fields, row, strict=True)
            }
        )

    encoded_issues = document["issue_index"]
    paths = encoded_issues["paths"]
    if paths != sorted(set(paths)):
        raise RepositoryMapError("issue paths must be sorted and unique")
    issue_index: dict[str, list[dict[str, Any]]] = {}
    for issue, locations in encoded_issues["issues"].items():
        decoded_locations: list[dict[str, Any]] = []
        for path_index, line in locations:
            if path_index < 0 or path_index >= len(paths):
                raise RepositoryMapError(
                    f"issue path index is out of range: {path_index}"
                )
            decoded_locations.append({"path": paths[path_index], "line": line})
        issue_index[issue] = decoded_locations

    encoded_graph = document["module_graph"]
    nodes = encoded_graph["nodes"]
    rows = encoded_graph["edges"]
    if nodes != sorted(set(nodes)):
        raise RepositoryMapError("module graph nodes must be sorted and unique")
    if len(rows) != len(nodes):
        raise RepositoryMapError("module graph row count differs from the node table")
    adjacency: dict[str, list[str]] = {}
    for node, targets in zip(nodes, rows, strict=True):
        decoded_targets: list[str] = []
        for target_index in targets:
            if target_index < 0 or target_index >= len(nodes):
                raise RepositoryMapError(
                    f"module graph target index is out of range: {target_index}"
                )
            decoded_targets.append(nodes[target_index])
        adjacency[node] = decoded_targets
    if encoded_graph["node_count"] != len(adjacency):
        raise RepositoryMapError("module graph node count differs from decoded nodes")
    if encoded_graph["edge_count"] != sum(len(values) for values in adjacency.values()):
        raise RepositoryMapError("module graph edge count differs from decoded edges")

    return {
        **{
            key: value
            for key, value in document.items()
            if key
            not in {
                "encoding",
                "entries",
                "issue_index",
                "module_graph",
                "schema_version",
            }
        },
        "schema_version": "gravity.repository-map.v1",
        "entries": entries,
        "issue_index": issue_index,
        "module_graph": {
            **{
                key: value
                for key, value in encoded_graph.items()
                if key not in {"nodes", "edges"}
            },
            "edges": adjacency,
        },
    }


def estimate_tokens(data: bytes | str) -> int:
    """Approximate mixed code/CJK BPE tokens without a tokenizer dependency."""

    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    cjk = len(_CJK_PATTERN.findall(text))
    non_cjk = _CJK_PATTERN.sub("", text).encode("utf-8")
    return cjk + math.ceil(len(non_cjk) / 4)


def _tracked_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    excluded = {
        _posix(MAP_PATH, root),
        "tmp/repository-map-proposal.md",
    }
    result: list[Path] = []
    for raw in completed.stdout.decode("utf-8").split("\0"):
        if not raw:
            continue
        relative = PurePosixPath(raw.replace("\\", "/")).as_posix()
        path = root / relative
        if relative in excluded or _is_history(relative) or not path.is_file():
            continue
        result.append(path)
    return sorted(result, key=lambda path: _posix(path, root))


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _load_graph_owner(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the existing test-side #14 graph owner without copying its rules."""

    owner_path = root / "tests/agent_migration_characterization.py"
    spec = importlib.util.spec_from_file_location("_repository_map_graph_owner", owner_path)
    if spec is None or spec.loader is None:
        raise RepositoryMapError(f"cannot load module graph owner: {_posix(owner_path, root)}")
    module = importlib.util.module_from_spec(spec)
    root_text = str(root)
    added_root = root_text not in sys.path
    if added_root:
        sys.path.insert(0, root_text)
    try:
        spec.loader.exec_module(module)
    finally:
        if added_root:
            sys.path.remove(root_text)
    definition = module.module_graph_current_definition(root / "docs/maintainers/technical-debt.md")
    measurement = module.module_graph_measurement(
        root / "src/gravity_insight", definition
    )
    adjacency = module.module_graph_adjacency(
        root / "src/gravity_insight", definition, "canonical"
    )
    summary = measurement["profiles"]["canonical"]
    graph = {
        "definition_id": measurement["definition_id"],
        "definition_sha256": measurement["definition_sha256"],
        "profile": "canonical",
        "node_count": measurement["node_count"],
        "edge_count": summary["edge_count"],
        "graph_sha256": summary["graph_sha256"],
        "edges": adjacency["edges"],
    }
    return definition, graph


def _relative_index_path(raw: str, root: Path) -> str | None:
    path = (COMPONENT_INDEX.parent / raw).resolve()
    try:
        relative = path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    return relative if path.exists() else None


def _module_from_path(relative: str) -> str | None:
    prefix = "src/gravity_insight/"
    if not relative.startswith(prefix) or not relative.endswith(".py"):
        return None
    tail = relative.removeprefix("src/").removesuffix(".py")
    if tail.endswith("/__init__"):
        tail = tail.removesuffix("/__init__")
    return tail.replace("/", ".")


def _path_from_module(module: str, root: Path) -> str | None:
    if module == "gravity_insight":
        candidates = [root / "src/gravity_insight/__init__.py"]
    elif module.startswith("gravity_insight."):
        relative = module.replace(".", "/")
        candidates = [root / f"src/{relative}.py", root / f"src/{relative}/__init__.py"]
    else:
        return None
    for candidate in candidates:
        if candidate.is_file():
            return _posix(candidate, root)
    return None


def _schema_index(root: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for path in sorted((root / "src/gravity_insight/contracts/schema").glob("*.json")):
        document = _json(path)
        schema_version = document.get("properties", {}).get("schema_version", {})
        value = schema_version.get("const") if isinstance(schema_version, dict) else None
        if isinstance(value, str):
            result[value].append(_posix(path, root))
    return {key: sorted(value) for key, value in sorted(result.items())}


def _schema_paths(document: Mapping[str, Any], schemas: Mapping[str, list[str]]) -> list[str]:
    version = document.get("schema_version")
    return list(schemas.get(version, ())) if isinstance(version, str) else []


def _manifest_dependencies(document: Mapping[str, Any]) -> list[str]:
    values: set[str] = set()
    for field in ("dependencies", "required_capabilities", "capability_dependencies"):
        rows = document.get(field, [])
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("selector"), str):
                    values.add(row["selector"])
    for field in (
        "required_semantics",
        "required_operators",
        "required_models",
        "semantic_dependencies",
        "operator_dependencies",
        "model_dependencies",
    ):
        rows = document.get(field, [])
        if isinstance(rows, list):
            values.update(value for value in rows if isinstance(value, str))
    context = document.get("context_dependencies")
    if isinstance(context, dict):
        for rows in context.values():
            if isinstance(rows, list):
                values.update(value for value in rows if isinstance(value, str))
    rows = document.get("required_context", [])
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, str):
                values.add(row)
            elif isinstance(row, dict):
                values.update(value for value in row.values() if isinstance(value, str))
    required_skill = document.get("required_skill")
    if isinstance(required_skill, str):
        values.add(required_skill)
    return sorted(values)


def _capability_selectors(document: Mapping[str, Any]) -> list[str]:
    result: set[str] = set()
    if document.get("artifact_kind") == "capability" and isinstance(document.get("selector"), str):
        result.add(document["selector"])
    for field in ("dependencies", "required_capabilities", "capability_dependencies"):
        rows = document.get(field, [])
        if isinstance(rows, list):
            result.update(
                row["selector"]
                for row in rows
                if isinstance(row, dict) and isinstance(row.get("selector"), str)
            )
    return sorted(result)


def _debt_sections(text: str) -> list[dict[str, Any]]:
    current = text.split("## 已关闭", 1)[0]
    matches = list(_DEBT_HEADING.finditer(current))
    result: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(current)
        body = current[match.start():end]
        line_start = current.count("\n", 0, match.start()) + 1
        line_end = line_start + body.count("\n")
        result.append(
            {
                "number": match.group(1),
                "title": match.group(2),
                "body": body,
                "line_start": line_start,
                "line_end": line_end,
            }
        )
    return result


def _path_references(text: str, root: Path) -> list[str]:
    candidates = re.findall(r"(?:\[[^\]]+\]\(([^)#]+)|`([^`]+)`)", text)
    result: set[str] = set()
    for pair in candidates:
        raw = next((item for item in pair if item), "").replace("\\", "/")
        if not raw or " " in raw or raw.startswith(("http://", "https://")):
            continue
        for base in (DEBT_PATH.parent, root):
            path = (base / raw).resolve()
            try:
                relative = path.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if path.is_file() and not _is_history(relative):
                result.add(relative)
                break
    return sorted(result)


def _base_entities(root: Path, graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    schemas = _schema_index(root)
    components = _json(COMPONENT_INDEX)["components"]
    entities: list[dict[str, Any]] = []
    for component in components:
        machine_sources = [
            value
            for raw in component.get("machine_sources", [])
            if (value := _relative_index_path(raw, root)) is not None
        ]
        exact_sources = [value for value in machine_sources if (root / value).is_file()]
        modules = [value for value in map(_module_from_path, exact_sources) if value]
        dependencies = sorted(
            {
                target
                for module in modules
                for target in graph["edges"].get(module, [])
            }
        )
        schema_paths = sorted(value for value in machine_sources if "/schema/" in value)
        reference = _relative_index_path(component.get("reference", ""), root)
        entities.append(
            {
                "id": f"component:{component['id']}",
                "entity_kind": "component",
                "source_files": sorted(set(["specs/agent-runtime/index.json", *exact_sources])),
                "source_spans": [],
                "domain": component["id"].split("-", 1)[0],
                "capability": None,
                "skill": None,
                "journey": None,
                "owner": component.get("owner"),
                "public_surfaces": None,
                "dependencies": dependencies or None,
                "schema": schema_paths or None,
                "tests": [],
                "current_docs": [reference] if reference else [],
                "issue": [],
                "debt": [],
                "maturity": component.get("maturity"),
                "terms": [component["id"], *exact_sources, *modules],
            }
        )

    capability_documents: list[tuple[str, dict[str, Any]]] = []
    for path in sorted((root / "src/gravity_insight/contracts/capabilities").glob("*.json")):
        capability_documents.append((_posix(path, root), _json(path)))
    journey_documents: list[tuple[str, dict[str, Any]]] = []
    for path in sorted((root / "src/gravity_insight/contracts/journeys").glob("*.json")):
        document = _json(path)
        if document.get("artifact_kind") == "journey":
            journey_documents.append((_posix(path, root), document))
    skill_documents = [
        (_posix(path, root), _json(path))
        for path in sorted((root / "skills/library").glob("*.json"))
    ]
    skills_by_journey: dict[str, set[str]] = defaultdict(set)
    skills_by_capability: dict[str, set[str]] = defaultdict(set)
    journeys_by_capability: dict[str, set[str]] = defaultdict(set)
    for _path, document in skill_documents:
        skill_id = document["skill_id"]
        for journey in document.get("covers_journeys", []):
            if isinstance(journey, str):
                skills_by_journey[journey].add(skill_id)
        for selector in _capability_selectors(document):
            skills_by_capability[selector].add(skill_id)
    for _path, document in journey_documents:
        journey_id = document["journey_id"]
        for selector in _capability_selectors(document):
            journeys_by_capability[selector].add(journey_id)

    for relative, document in capability_documents:
        selector = document["selector"]
        entities.append(
            {
                "id": f"capability:{selector}",
                "entity_kind": "capability",
                "source_files": [relative],
                "source_spans": [],
                "domain": str(document.get("owner", "")).partition("/")[2] or None,
                "capability": [selector],
                "skill": sorted(skills_by_capability.get(selector, set())),
                "journey": sorted(journeys_by_capability.get(selector, set())),
                "owner": document.get("owner"),
                "public_surfaces": None,
                "dependencies": _manifest_dependencies(document),
                "schema": _schema_paths(document, schemas) or None,
                "tests": [],
                "current_docs": [],
                "issue": [],
                "debt": [],
                "maturity": document.get("lifecycle"),
                "terms": [selector, relative],
            }
        )
    for relative, document in journey_documents:
        journey_id = document["journey_id"]
        linked_skills = set(skills_by_journey.get(journey_id, set()))
        if isinstance(document.get("required_skill"), str):
            linked_skills.add(document["required_skill"])
        surfaces = document.get("surfaces")
        entities.append(
            {
                "id": f"journey:{journey_id}",
                "entity_kind": "journey",
                "source_files": [relative],
                "source_spans": [],
                "domain": journey_id.split(".", 1)[0],
                "capability": _capability_selectors(document),
                "skill": sorted(linked_skills),
                "journey": [journey_id],
                "owner": document.get("owner"),
                "public_surfaces": dict(sorted(surfaces.items())) if isinstance(surfaces, dict) else None,
                "dependencies": _manifest_dependencies(document),
                "schema": _schema_paths(document, schemas) or None,
                "tests": [],
                "current_docs": [],
                "issue": [],
                "debt": [],
                "maturity": document.get("lifecycle"),
                "terms": [journey_id, relative, *_capability_selectors(document)],
            }
        )
    for relative, document in skill_documents:
        skill_id = document["skill_id"]
        namespace = document.get("namespace")
        journeys = sorted(value for value in document.get("covers_journeys", []) if isinstance(value, str))
        entities.append(
            {
                "id": f"skill:{skill_id}",
                "entity_kind": "skill",
                "source_files": [relative],
                "source_spans": [],
                "domain": namespace if isinstance(namespace, str) else None,
                "capability": _capability_selectors(document),
                "skill": [skill_id],
                "journey": journeys,
                "owner": None,
                "public_surfaces": None,
                "dependencies": _manifest_dependencies(document),
                "schema": _schema_paths(document, schemas) or None,
                "tests": [],
                "current_docs": [],
                "issue": [],
                "debt": [],
                "maturity": document.get("lifecycle"),
                "terms": [skill_id, relative, *journeys, *_capability_selectors(document)],
            }
        )

    debt_text = DEBT_PATH.read_text(encoding="utf-8")
    for section in _debt_sections(debt_text):
        number = section["number"]
        entities.append(
            {
                "id": f"debt:{number}",
                "entity_kind": "debt",
                "source_files": [_posix(DEBT_PATH, root)],
                "source_spans": [
                    {
                        "path": _posix(DEBT_PATH, root),
                        "line_start": section["line_start"],
                        "line_end": section["line_end"],
                    }
                ],
                "domain": None,
                "capability": None,
                "skill": None,
                "journey": None,
                "owner": None,
                "public_surfaces": None,
                "dependencies": _path_references(section["body"], root) or None,
                "schema": None,
                "tests": [],
                "current_docs": [_posix(DEBT_PATH, root)],
                "issue": sorted(set(_ISSUE_PATTERN.findall(section["body"]))),
                "debt": [number],
                "maturity": None,
                "terms": [
                    f"technical debt #{number}",
                    f"debt #{number}",
                    section["title"],
                    f"debt:{number}",
                ],
            }
        )
    return entities


def _term_hits(text: str, terms: Iterable[str]) -> list[tuple[str, int]]:
    selected = sorted({term for term in terms if isinstance(term, str) and len(term) >= 4})
    result: list[tuple[str, int]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for term in selected:
            if term in line:
                result.append((term, line_number))
    return result


def _reference_enrichment(
    root: Path,
    entities: list[dict[str, Any]],
    tracked: Sequence[Path],
) -> dict[str, list[dict[str, Any]]]:
    tests: dict[str, str] = {}
    docs: dict[str, str] = {}
    issue_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in tracked:
        relative = _posix(path, root)
        text = _read_text(path)
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for issue in _ISSUE_PATTERN.findall(line):
                issue_index[issue].append({"path": relative, "line": line_number})
        if relative.startswith("tests/") and path.suffix in {".py", ".json"}:
            tests[relative] = text
        if path.suffix == ".md" and not _is_history(relative):
            docs[relative] = text

    debt_sections = _debt_sections(DEBT_PATH.read_text(encoding="utf-8"))
    for entity in entities:
        terms = entity.pop("terms")
        direct_tests = {
            relative for relative, text in tests.items() if _term_hits(text, terms)
        }
        helper_names = {
            Path(relative).stem
            for relative in direct_tests
            if not Path(relative).name.startswith("test_")
        }
        transitive_tests = {
            relative
            for relative, text in tests.items()
            if Path(relative).name.startswith("test_")
            and any(
                f"tests.{helper}" in text or f"from {helper}" in text
                for helper in helper_names
            )
        }
        entity["tests"] = sorted(direct_tests | transitive_tests)
        existing_docs = set(entity["current_docs"])
        existing_docs.update(
            relative for relative, text in docs.items() if _term_hits(text, terms)
        )
        entity["current_docs"] = sorted(existing_docs)
        issue_values = set(entity["issue"])
        source_paths = set(entity["source_files"])
        for collection in (tests, docs):
            for relative, text in collection.items():
                if relative not in entity["tests"] and relative not in entity["current_docs"]:
                    continue
                for _term, line_number in _term_hits(text, terms):
                    line = text.splitlines()[line_number - 1]
                    issue_values.update(_ISSUE_PATTERN.findall(line))
        source_spans = entity["source_spans"] or [
            {"path": relative, "line_start": None, "line_end": None}
            for relative in source_paths
        ]
        for span in source_spans:
            text = _span_bytes(root, span).decode("utf-8", errors="replace")
            issue_values.update(_ISSUE_PATTERN.findall(text))
        entity["issue"] = sorted(issue_values, key=int)
        debt_values = set(entity["debt"])
        for section in debt_sections:
            if _term_hits(section["body"], terms):
                debt_values.add(section["number"])
        entity["debt"] = sorted(debt_values, key=int)
    return {
        key: sorted(
            {json.dumps(item, sort_keys=True): item for item in values}.values(),
            key=lambda item: (item["path"], item["line"]),
        )
        for key, values in sorted(issue_index.items(), key=lambda item: int(item[0]))
    }


def _span_bytes(root: Path, span: Mapping[str, Any]) -> bytes:
    data = (root / span["path"]).read_text(encoding="utf-8").splitlines(keepends=True)
    start = span.get("line_start")
    end = span.get("line_end")
    selected = data if start is None or end is None else data[start - 1:end]
    return "".join(selected).encode("utf-8")


def _entry_estimates(root: Path, entity: dict[str, Any]) -> tuple[int, int]:
    spans = entity["source_spans"] or [
        {"path": path, "line_start": None, "line_end": None}
        for path in entity["source_files"]
        if (root / path).is_file()
    ]
    schema_paths = set(entity["schema"] or [])
    seen = {(span["path"], span.get("line_start"), span.get("line_end")) for span in spans}
    spans.extend(
        {"path": path, "line_start": None, "line_end": None}
        for path in sorted(schema_paths)
        if (path, None, None) not in seen
    )
    payload = b"".join(_span_bytes(root, span) for span in spans)
    return len(payload), estimate_tokens(payload)


def _unavailable(entity: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in REQUIRED_MAP_FIELDS:
        if entity.get(field) is not None:
            continue
        if field in {"capability", "skill", "journey", "public_surfaces"}:
            result[field] = "not_applicable_to_entity_kind"
        elif field in {"domain", "owner", "schema", "maturity", "dependencies"}:
            result[field] = "no_machine_binding"
        else:
            result[field] = "no_exact_repository_reference"
    return result


def _field_derivation() -> dict[str, dict[str, Any]]:
    return {
        "domain": {
            "sources": ["contract namespace/identity", "specs/agent-runtime/index.json"],
            "method": "Use an explicit Skill namespace; otherwise use the first identity component. Debt has no domain binding.",
            "null_reason": "The source entity has no machine-owned namespace or domain identity.",
        },
        "capability": {
            "sources": ["Capability/Journey/Skill contract selector fields"],
            "method": "Collect exact selector values from the entity and its declared capability dependencies.",
            "null_reason": "Capability is not applicable to this entity kind.",
        },
        "skill": {
            "sources": ["skills/library/*.json", "Journey required_skill"],
            "method": "Join exact skill_id, covers_journeys, required_skill, and capability selector values.",
            "null_reason": "Skill is not applicable to this entity kind.",
        },
        "journey": {
            "sources": ["contracts/journeys/*.json", "Skill covers_journeys"],
            "method": "Join exact journey_id and covers_journeys values.",
            "null_reason": "Journey is not applicable to this entity kind.",
        },
        "owner": {
            "sources": ["component index owner", "Capability/Journey owner"],
            "method": "Copy only an explicit owner field from the machine source.",
            "null_reason": "No machine owner field exists; authorship and Git author are not treated as ownership.",
        },
        "public_surfaces": {
            "sources": ["Journey surfaces"],
            "method": "Copy the explicit surface/status object; documentation filenames are not promoted to availability claims.",
            "null_reason": "No explicit public-surface declaration exists for the entity.",
        },
        "dependencies": {
            "sources": ["contract dependency fields", "canonical module graph v1"],
            "method": "Collect declared manifest dependencies or canonical outgoing module edges for exact Python machine sources.",
            "null_reason": "No governed dependency declaration or graph-bound Python source exists.",
        },
        "schema": {
            "sources": ["contracts/schema/*.json", "component machine_sources"],
            "method": "Join contract schema_version to a schema const, or retain exact component schema source paths.",
            "null_reason": "No exact schema_version const or component schema source is bound.",
        },
        "tests": {
            "sources": ["tracked tests/**/*.py", "tracked tests/**/*.json"],
            "method": "Exact-match entity identities, selectors, source paths, and module names in current tracked tests.",
            "null_reason": "The test field is scan-derived; an empty array proves no exact reference in the scanned universe.",
        },
        "current_docs": {
            "sources": ["tracked non-Archive Markdown"],
            "method": "Exact-match entity identities, selectors, source paths, and module names; exclude History/Archive prefixes.",
            "null_reason": "The docs field is scan-derived; an empty array proves no exact current reference.",
        },
        "issue": {
            "sources": ["current tracked text"],
            "method": "Extract #N or Issue N only from entity sources and exact-match reference lines; this is textual evidence, not GitHub state.",
            "null_reason": "The issue field is scan-derived; an empty array proves no exact textual reference, not that no external Issue exists.",
        },
        "debt": {
            "sources": ["docs/maintainers/technical-debt.md current entries"],
            "method": "Parse current debt sections and exact-match entity identities or source paths.",
            "null_reason": "The debt field is scan-derived; an empty array proves no exact current debt reference.",
        },
        "maturity": {
            "sources": ["component maturity", "Capability/Journey/Skill lifecycle"],
            "method": "Copy the source-owned maturity or lifecycle value without translating vocabularies.",
            "null_reason": "The entity source has no maturity/lifecycle field.",
        },
        "token_estimate": {
            "sources": ["entity source spans", "bound schema files"],
            "method": "Count each CJK code point as one token plus ceil(non-CJK UTF-8 bytes / 4).",
            "null_reason": "Never null; unreadable source generation fails instead.",
        },
        "byte_estimate": {
            "sources": ["entity source spans", "bound schema files"],
            "method": "Sum exact current UTF-8 byte lengths for unique selected source spans and bound schemas.",
            "null_reason": "Never null; unreadable source generation fails instead.",
        },
    }


def build_repository_map(root: Path = ROOT) -> dict[str, Any]:
    _definition, graph = _load_graph_owner(root)
    entities = _base_entities(root, graph)
    issue_index = _reference_enrichment(root, entities, _tracked_files(root))
    for entity in entities:
        byte_estimate, token_estimate = _entry_estimates(root, entity)
        entity["byte_estimate"] = byte_estimate
        entity["token_estimate"] = token_estimate
        entity["unavailable"] = _unavailable(entity)
    entities.sort(key=lambda item: item["id"])
    counts = Counter(entity["entity_kind"] for entity in entities)
    return {
        "schema_version": "gravity.repository-map.v1",
        "generation_metadata": {
            "deterministic": True,
            "generated_at": None,
            "generated_at_reason": "volatile timestamps are excluded from the reproducible projection",
        },
        "field_derivation": _field_derivation(),
        "estimate_method": {
            "bytes": "Exact UTF-8 bytes of the selected source spans and bound schemas; field name retains the requirement vocabulary.",
            "tokens": "Tokenizer-free approximation: CJK code points + ceil(other UTF-8 bytes / 4).",
            "expected_error": "Usually about +/-20-40% for mixed Python/JSON/Chinese; minified text, long identifiers, or unusual Unicode can exceed 2x. It is not a tokenizer count.",
        },
        "counts": {
            **dict(sorted(counts.items())),
            "entries": len(entities),
            "issues_with_current_references": len(issue_index),
            "module_graph_edges": graph["edge_count"],
            "module_graph_nodes": graph["node_count"],
        },
        "entries": entities,
        "issue_index": issue_index,
        "module_graph": graph,
    }


def validate_contract(value: Mapping[str, Any], schema_name: str) -> None:
    from gravity_insight.agent_runtime_contracts import validate_schema

    validate_schema(dict(value), schema_name, schema_name)


def write_repository_map(
    root: Path = ROOT,
    output: Path | None = None,
) -> tuple[dict[str, Any], bytes]:
    facts = build_repository_map(root)
    validate_contract(facts, MAP_FACT_SCHEMA)
    document = encode_repository_map(facts)
    validate_contract(document, MAP_SCHEMA)
    payload = canonical_json_bytes(document) + b"\n"
    selected = output or (root / MAP_PATH.relative_to(ROOT))
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_bytes(payload)
    return facts, payload


def load_repository_map(
    path: Path = MAP_PATH,
    *,
    validate: bool = True,
) -> dict[str, Any]:
    document = _json(path)
    if validate:
        validate_contract(document, MAP_SCHEMA)
    facts = decode_repository_map(document)
    if validate:
        validate_contract(facts, MAP_FACT_SCHEMA)
    return facts


def _normalize_input_path(value: str, root: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise RepositoryMapError(f"changed file is outside repository: {value}") from exc
    return PurePosixPath(value.replace("\\", "/")).as_posix().lstrip("./")


def _matching_entries(
    document: Mapping[str, Any], kind: str, values: Sequence[str], root: Path
) -> list[dict[str, Any]]:
    entries = list(document["entries"])
    selected: list[dict[str, Any]] = []
    normalized = set(values)
    if kind == "issue":
        normalized = {str(int(value.removeprefix("#"))) for value in values}
        selected = [
            entry
            for entry in entries
            if normalized.intersection(entry["issue"] or [])
        ]
    elif kind == "journey":
        selected = [entry for entry in entries if normalized.intersection(entry["journey"] or [])]
    elif kind == "skill":
        selected = [entry for entry in entries if normalized.intersection(entry["skill"] or [])]
    elif kind == "selector":
        selected = [
            entry
            for entry in entries
            if normalized.intersection(entry["capability"] or [])
            or normalized.intersection(entry["dependencies"] or [])
        ]
    elif kind == "changed_files":
        normalized = {_normalize_input_path(value, root) for value in values}
        selected = [
            entry
            for entry in entries
            if normalized.intersection(
                set(entry["source_files"])
                | set(entry["dependencies"] or [])
                | set(entry["schema"] or [])
                | set(entry["tests"] or [])
                | set(entry["current_docs"] or [])
            )
        ]
    else:
        raise RepositoryMapError(f"unknown context selector kind: {kind}")
    return sorted(selected, key=lambda item: item["id"])


def _line_span(path: Path, terms: Iterable[str], radius: int = 2) -> tuple[int | None, int | None]:
    text = _read_text(path)
    if text is None:
        return None, None
    hits = _term_hits(text, terms)
    if not hits:
        return None, None
    lines = text.splitlines()
    line = hits[0][1]
    return max(1, line - radius), min(len(lines), line + radius)


def _add_reference(
    references: dict[tuple[str, int | None, int | None], dict[str, Any]],
    root: Path,
    path: str,
    *,
    layer: str,
    reason: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> None:
    if _is_history(path) or not (root / path).is_file():
        return
    key = (path, line_start, line_end)
    if key in references:
        references[key]["reasons"] = sorted(set([*references[key]["reasons"], reason]))
        return
    span = {"path": path, "line_start": line_start, "line_end": line_end}
    payload = _span_bytes(root, span)
    references[key] = {
        **span,
        "layer": layer,
        "reasons": [reason],
        "bytes": len(payload),
        "estimated_tokens": estimate_tokens(payload),
    }


def _merge_references(
    root: Path, references: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_path: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for reference in references:
        by_path[reference["path"]].append(reference)
    layer_order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    result: list[dict[str, Any]] = []
    for path, rows in sorted(by_path.items()):
        if any(row["line_start"] is None for row in rows):
            payload = (root / path).read_bytes()
            result.append(
                {
                    "path": path,
                    "line_start": None,
                    "line_end": None,
                    "layer": min(
                        (row["layer"] for row in rows), key=layer_order.get
                    ),
                    "reasons": sorted(
                        {reason for row in rows for reason in row["reasons"]}
                    ),
                    "bytes": len(payload),
                    "estimated_tokens": estimate_tokens(payload),
                }
            )
            continue
        intervals = sorted(rows, key=lambda row: (row["line_start"], row["line_end"]))
        merged: list[dict[str, Any]] = []
        for row in intervals:
            if merged and row["line_start"] <= merged[-1]["line_end"] + 1:
                merged[-1]["line_end"] = max(merged[-1]["line_end"], row["line_end"])
                merged[-1]["reasons"].update(row["reasons"])
                if layer_order[row["layer"]] < layer_order[merged[-1]["layer"]]:
                    merged[-1]["layer"] = row["layer"]
            else:
                merged.append(
                    {
                        "line_start": row["line_start"],
                        "line_end": row["line_end"],
                        "layer": row["layer"],
                        "reasons": set(row["reasons"]),
                    }
                )
        for row in merged:
            span = {
                "path": path,
                "line_start": row["line_start"],
                "line_end": row["line_end"],
            }
            payload = _span_bytes(root, span)
            result.append(
                {
                    **span,
                    "layer": row["layer"],
                    "reasons": sorted(row["reasons"]),
                    "bytes": len(payload),
                    "estimated_tokens": estimate_tokens(payload),
                }
            )
    return result


def _selector_source_references(root: Path, values: Sequence[str]) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    for path in sorted((root / "src/gravity_insight").rglob("*.py")):
        start, end = _line_span(path, values, radius=3)
        if start is not None and end is not None:
            result.append((_posix(path, root), start, end))
    return result


def _full_gate(root: Path) -> list[str]:
    source = (root / "AGENTS.md").read_text(encoding="utf-8")
    try:
        validation = source.split("## Validation", 1)[1]
        block = validation.split("```powershell", 1)[1].split("```", 1)[0]
    except IndexError as exc:
        raise RepositoryMapError("AGENTS.md has no Validation PowerShell block") from exc
    commands: list[str] = []
    python = sys.executable.replace("\\", "/")
    for raw in block.splitlines():
        command = raw.strip()
        if not command or "agent_usability_eval.py" in command:
            continue
        if command.startswith("python "):
            commands.append(f'& "{python}" {command.removeprefix("python ")}')
        elif command.startswith('& ".venv/Scripts/python.exe" '):
            commands.append(
                f'& "{python}" '
                + command.removeprefix('& ".venv/Scripts/python.exe" ')
            )
        elif command == "git diff --check":
            commands.append(command)
    return commands


def _surface_consumer_gate(python: str) -> list[str]:
    """Return the existing installed-artifact surface and consumer checks."""

    return [
        f'& "{python}" -m pytest -q tests/test_public_api_snapshot.py '
        "tests/test_installed_wheel_surface_matrix.py "
        "tests/test_installed_wheel_consumer_check.py",
        f'& "{python}" scripts/check_installed_wheel_surface_matrix.py',
        f'& "{python}" scripts/check_installed_wheel_consumer.py',
    ]


def _integrated_canary_gate(python: str) -> list[str]:
    """Return clean-commit integrated validation and the offline canary contract."""

    return [
        f'& "{python}" scripts/run_integrated_validation.py --trial',
        f'& "{python}" -m pytest -q tests/test_control_plane_lifecycle.py',
    ]


def _risk_rule_for_path(path: str) -> tuple[str, str]:
    normalized = PurePosixPath(path.replace("\\", "/")).as_posix()
    lowered = normalized.casefold()
    if normalized in _HIGH_RISK_EXACT_PATHS:
        return "high", "high:governance-or-shared-spine"
    if any(normalized.startswith(prefix) for prefix in _HIGH_RISK_PREFIXES):
        return "high", "high:contract-agent-route-or-release-control"
    if any(term in lowered for term in _HIGH_RISK_PATH_TERMS):
        return "high", "high:safety-concurrency-degradation-or-provenance"
    if normalized in _LOW_RISK_EXACT_PATHS or any(
        normalized.startswith(prefix) for prefix in _LOW_RISK_PREFIXES
    ):
        return "low", "low:content-doc-or-test-only"
    if normalized.startswith("src/gravity_insight/") or normalized.startswith("scripts/"):
        return "medium", "medium:runtime-surface-or-maintainer-tool"
    return "high", "high:unclassified-path-fails-closed"


def classify_change_risk(
    paths: Sequence[str],
    *,
    entity_ids: Sequence[str] = (),
    focused_gate: Sequence[str] = (),
    full_gate: Sequence[str] = (),
    python: str | None = None,
) -> dict[str, Any]:
    """Classify a change once, taking the highest matching risk conservatively."""

    if not paths and not entity_ids:
        raise RepositoryMapError("risk classification requires changed paths or entities")
    executable = python or sys.executable.replace("\\", "/")
    matches: list[dict[str, str]] = []
    for path in sorted(set(paths)):
        level, rule = _risk_rule_for_path(path)
        matches.append({"subject": path, "level": level, "rule": rule})
    for entity_id in sorted(set(entity_ids)):
        if entity_id.startswith("component:"):
            level, rule = "high", "high:runtime-component-entity"
        elif entity_id.startswith(("capability:", "journey:")):
            level, rule = "medium", "medium:consumer-visible-entity"
        elif entity_id.startswith(("skill:", "debt:")):
            level, rule = "low", "low:content-entity"
        else:
            level, rule = "high", "high:unresolved-entity-fails-closed"
        matches.append({"subject": entity_id, "level": level, "rule": rule})
    level = max((item["level"] for item in matches), key=RISK_LEVELS.__getitem__)
    commands = list(focused_gate)
    if level == "medium":
        commands.extend(_surface_consumer_gate(executable))
    elif level == "high":
        commands = [*full_gate, *_integrated_canary_gate(executable)]
    commands = list(dict.fromkeys(commands))
    return {
        "level": level,
        "review_mode": RISK_REVIEW_MODES[level],
        "validation_profile": {
            "low": "focused",
            "medium": "surface_consumer",
            "high": "integrated_canary",
        }[level],
        "matched_rules": matches,
        "selected_commands": commands,
        "selection_policy": "highest_match_wins; unclassified paths fail closed to high",
    }


def _reverse_graph(edges: Mapping[str, Sequence[str]]) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = {node: set() for node in edges}
    for source, targets in edges.items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)
    return reverse


def _closure(reverse: Mapping[str, set[str]], seeds: Iterable[str]) -> list[str]:
    seed_set = set(seeds)
    seen = set(seed_set)
    queue = deque(sorted(seed_set))
    while queue:
        node = queue.popleft()
        for dependent in sorted(reverse.get(node, set())):
            if dependent not in seen:
                seen.add(dependent)
                queue.append(dependent)
    return sorted(seen - seed_set)


def _bounded_set(values: Sequence[str], limit: int = 40) -> dict[str, Any]:
    selected = sorted(set(values))
    return {
        "count": len(selected),
        "sha256": canonical_sha256(selected),
        "preview": selected[:limit],
        "truncated": len(selected) > limit,
    }


def _test_references_for_modules(root: Path, modules: Sequence[str]) -> list[str]:
    result: list[str] = []
    for path in sorted((root / "tests").rglob("*.py")):
        text = _read_text(path)
        if text is not None and any(module in text for module in modules):
            result.append(_posix(path, root))
    return result


def build_task_context(
    kind: str,
    values: str | Sequence[str],
    *,
    root: Path = ROOT,
    map_document: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected_values = [values] if isinstance(values, str) else list(values)
    if not selected_values:
        raise RepositoryMapError("at least one selector value is required")
    normalized_values = [str(value) for value in selected_values]
    document = dict(map_document or load_repository_map(root / MAP_PATH.relative_to(ROOT)))
    entries = _matching_entries(document, kind, normalized_values, root)
    all_entries = list(document["entries"])
    exact_values = set(normalized_values)
    if kind == "issue":
        primary_entries = entries
    elif kind == "journey":
        primary_entries = [
            entry
            for entry in entries
            if entry["entity_kind"] == "journey"
            and exact_values.intersection(entry["journey"] or [])
        ]
    elif kind == "skill":
        primary_entries = [
            entry
            for entry in entries
            if entry["entity_kind"] == "skill"
            and exact_values.intersection(entry["skill"] or [])
        ]
    elif kind == "selector":
        primary_entries = [
            entry
            for entry in entries
            if entry["entity_kind"] == "capability"
            and exact_values.intersection(entry["capability"] or [])
        ]
    else:
        changed_values = {
            _normalize_input_path(value, root) for value in normalized_values
        }
        direct_entries = [
            entry
            for entry in entries
            if changed_values.intersection(
                set(entry["source_files"])
                | set(entry["dependencies"] or [])
                | set(entry["schema"] or [])
            )
        ]
        primary_entries = direct_entries or [
            entry
            for entry in entries
            if entry["entity_kind"] == "debt"
            and changed_values.intersection(entry["tests"] or [])
        ]
    dependency_values = {
        value
        for entry in primary_entries
        for value in (entry["dependencies"] or [])
    }
    dependency_entries = [
        entry
        for entry in all_entries
        if (
            entry["entity_kind"] == "capability"
            and dependency_values.intersection(entry["capability"] or [])
        )
        or (
            entry["entity_kind"] == "skill"
            and dependency_values.intersection(entry["skill"] or [])
        )
    ]
    context_entries = sorted(
        {entry["id"]: entry for entry in [*primary_entries, *dependency_entries]}.values(),
        key=lambda item: item["id"],
    )
    references: dict[tuple[str, int | None, int | None], dict[str, Any]] = {}
    unresolved: list[str] = []
    terms = set(normalized_values)
    if kind == "issue":
        terms.update(
            f"technical debt #{int(value.removeprefix('#'))}"
            for value in normalized_values
        )

    if kind == "changed_files":
        changed = [_normalize_input_path(value, root) for value in normalized_values]
        for path in changed:
            if _is_history(path):
                unresolved.append(f"history/archive excluded by default: {path}")
                continue
            _add_reference(references, root, path, layer="L2", reason="changed file")
    if kind == "issue":
        entry_reference_paths = {
            path
            for entry in context_entries
            for path in [
                *entry["source_files"],
                *(entry["tests"] or []),
                *(entry["current_docs"] or []),
            ]
        }
        for value in normalized_values:
            issue = str(int(value.removeprefix("#")))
            locations = document["issue_index"].get(issue, [])
            if not locations:
                unresolved.append(f"no current repository reference for issue {issue}")
            elif not entries:
                unresolved.append(
                    f"issue {issue} has textual references but no machine entity binding"
                )
            preferred_locations = [
                location
                for location in locations
                if location["path"] in entry_reference_paths
                and Path(location["path"]).suffix in {".md", ".py"}
            ]
            fallback_locations = [
                location
                for location in locations
                if Path(location["path"]).suffix in {".md", ".py"}
            ]
            for location in (preferred_locations or fallback_locations or locations)[:3]:
                _add_reference(
                    references,
                    root,
                    location["path"],
                    layer="L2",
                    reason=f"exact issue {issue} reference",
                    line_start=max(1, location["line"] - 2),
                    line_end=location["line"] + 4,
                )

    for entry in context_entries:
        terms.add(entry["id"].partition(":")[2])
        spans = entry["source_spans"]
        if spans:
            for span in spans:
                _add_reference(
                    references,
                    root,
                    span["path"],
                    layer="L2",
                    reason=f"{entry['entity_kind']} machine owner",
                    line_start=span["line_start"],
                    line_end=span["line_end"],
                )
        else:
            for path in entry["source_files"]:
                layer = "L1" if entry["entity_kind"] == "component" else "L2"
                _add_reference(
                    references,
                    root,
                    path,
                    layer=layer,
                    reason=f"{entry['entity_kind']} machine owner",
                )
        for path in entry["schema"] or []:
            _add_reference(references, root, path, layer="L3", reason="exact bound schema")

    implementation_selectors = sorted(
        set(normalized_values if kind == "selector" else [])
        | {
            selector
            for entry in context_entries
            for selector in (entry["capability"] or [])
        }
    )
    if implementation_selectors:
        for path, start, end in _selector_source_references(root, implementation_selectors)[:3]:
            _add_reference(
                references,
                root,
                path,
                layer="L3",
                reason="implementation contains exact selector",
                line_start=start,
                line_end=end,
            )

    candidate_tests = sorted(
        {
            path
            for entry in context_entries
            for path in (entry["tests"] or [])
            if Path(path).suffix == ".py"
        }
    )
    candidate_docs = sorted(
        {path for entry in context_entries for path in (entry["current_docs"] or [])}
    )
    graph_definition_id = document["module_graph"]["definition_id"]
    if any(
        not Path(path).name.startswith("test_")
        and graph_definition_id in (root / path).read_text(encoding="utf-8")
        for path in candidate_tests
    ):
        terms.add(graph_definition_id)
    for path in candidate_tests[:3]:
        start, end = _line_span(root / path, terms, radius=3)
        if start is None:
            continue
        _add_reference(
            references,
            root,
            path,
            layer="L3",
            reason="exact-reference focused test",
            line_start=start,
            line_end=end,
        )
    for path in candidate_docs[:1]:
        if path in {"docs/architecture.md", "AGENTS.md", "README.md"}:
            continue
        start, end = _line_span(root / path, terms, radius=2)
        if start is None:
            continue
        _add_reference(
            references,
            root,
            path,
            layer="L1",
            reason="current exact-reference documentation",
            line_start=start,
            line_end=end,
        )

    graph = document["module_graph"]
    edges: dict[str, list[str]] = graph["edges"]
    seed_modules = sorted(
        {
            module
            for reference in references.values()
            if (module := _module_from_path(reference["path"])) in edges
        }
    )
    reverse = _reverse_graph(edges)
    direct_dependencies = sorted({target for seed in seed_modules for target in edges.get(seed, [])})
    direct_dependents = sorted({source for seed in seed_modules for source in reverse.get(seed, set())})
    transitive = _closure(reverse, seed_modules)
    impacted_tests = sorted(
        set(candidate_tests) | set(_test_references_for_modules(root, [*seed_modules, *direct_dependents]))
    )
    directly_runnable = [
        path
        for path in candidate_tests
        if Path(path).suffix == ".py" and Path(path).name.startswith("test_")
    ]
    candidate_helpers = {
        Path(path).stem
        for path in candidate_tests
        if not Path(path).name.startswith("test_")
    }
    directly_runnable.sort(
        key=lambda path: (
            not any(
                f"tests.{helper}" in (text := (root / path).read_text(encoding="utf-8"))
                or f"from {helper}" in text
                for helper in candidate_helpers
            ),
            not bool(_term_hits((root / path).read_text(encoding="utf-8"), terms)),
            path,
        )
    )
    runnable_tests = list(dict.fromkeys([*directly_runnable, *[
        path
        for path in impacted_tests
        if Path(path).suffix == ".py" and Path(path).name.startswith("test_")
    ]]))
    for path in runnable_tests[:2]:
        start, end = _line_span(root / path, [*seed_modules, *implementation_selectors], radius=3)
        if start is None:
            continue
        _add_reference(
            references,
            root,
            path,
            layer="L3",
            reason="canonical-impact focused test",
            line_start=start,
            line_end=end,
        )
    for module in direct_dependencies[:2]:
        path = _path_from_module(module, root)
        if path:
            _add_reference(references, root, path, layer="L3", reason="direct canonical dependency")

    python = sys.executable.replace("\\", "/")
    focused_gate = [f'& "{python}" scripts/generate_repository_map.py --check']
    if runnable_tests:
        focused_gate.append(
            f'& "{python}" -m pytest -q ' + runnable_tests[0]
        )
    else:
        focused_gate.append(f'& "{python}" -m pytest -q tests/test_repository_map.py')

    order = {"L1": 0, "L2": 1, "L3": 2, "L0": 3}
    minimal = sorted(
        _merge_references(root, references.values()),
        key=lambda item: (order[item["layer"]], item["path"], item["line_start"] or 0),
    )
    pack_bytes = sum(item["bytes"] for item in minimal)
    pack_tokens = sum(item["estimated_tokens"] for item in minimal)
    architecture = ARCHITECTURE_PATH.read_bytes()
    risk_paths = (
        [_normalize_input_path(value, root) for value in normalized_values]
        if kind == "changed_files"
        else sorted(
            {
                path
                for entry in primary_entries
                for path in [*entry["source_files"], *(entry["schema"] or [])]
            }
        )
    )
    risk = classify_change_risk(
        risk_paths,
        entity_ids=(
            []
            if kind == "changed_files"
            else [entry["id"] for entry in primary_entries]
            or [f"unresolved:{kind}:{','.join(normalized_values)}"]
        ),
        focused_gate=focused_gate,
        full_gate=_full_gate(root),
        python=python,
    )
    result = {
        "schema_version": "gravity.task-context-pack.v1",
        "input": {"kind": kind, "values": normalized_values},
        "history_policy": {
            "default_excluded": True,
            "excluded_prefixes": list(HISTORY_PREFIXES),
        },
        "matched_entries": [entry["id"] for entry in context_entries],
        "minimal_references": minimal,
        "reading_order": [
            f"{item['path']}"
            + (
                f":{item['line_start']}-{item['line_end']}"
                if item["line_start"] is not None
                else ""
            )
            for item in minimal
        ],
        "impact_scope": {
            "graph_definition_id": graph["definition_id"],
            "profile": "canonical",
            "seed_modules": seed_modules,
            "direct_dependencies": direct_dependencies,
            "direct_dependents": direct_dependents,
            "transitive_dependents": _bounded_set(transitive),
            "impacted_test_files": impacted_tests,
        },
        "risk_assessment": risk,
        "focused_gate": focused_gate,
        "full_gate": _full_gate(root),
        "size_comparison": {
            "pack_bytes": pack_bytes,
            "pack_estimated_tokens": pack_tokens,
            "canonical_architecture_bytes": len(architecture),
            "canonical_architecture_estimated_tokens": estimate_tokens(architecture),
            "ratio_to_canonical_architecture": round(pack_bytes / len(architecture), 4),
        },
        "unresolved": unresolved,
    }
    validate_contract(result, PACK_SCHEMA)
    return result


__all__ = [
    "MAP_PATH",
    "RepositoryMapError",
    "build_repository_map",
    "build_task_context",
    "canonical_json_bytes",
    "canonical_sha256",
    "classify_change_risk",
    "decode_repository_map",
    "encode_repository_map",
    "estimate_tokens",
    "load_repository_map",
    "validate_contract",
    "write_repository_map",
]
