"""Read-only Gravity workspace discovery and validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .workspace_recipe import Recipe, RecipeBindings, validate_recipes


WORKSPACE_FILENAME = "gravity.toml"
WORKSPACE_ENV = "GRAVITY_WORKSPACE"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_OUTPUT_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SENSITIVE_OUTPUT_FIELDS = frozenset(
    {"user_id", "device_id", "distinct_id", "account_id", "phone", "email"}
)
_PRODUCT_KINDS = frozenset({"custom-sql"})
_VERIFICATION_STATUSES = frozenset(
    {"pending_review", "verified", "verified_with_gaps", "blocked"}
)


class WorkspaceError(ValueError):
    """Raised when an explicitly selected workspace is invalid."""


class WorkspaceNotConfiguredError(WorkspaceError):
    """Raised when an operation requires workspace data that is absent."""


@dataclass(frozen=True)
class WorkspaceDefaults:
    app: str | None
    timezone: str
    time_window: str | None


@dataclass(frozen=True)
class Workspace:
    """Validated workspace data plus its separate mutable state location."""

    path: Path | None
    root: Path
    state_root: Path
    apps: Mapping[str, int]
    defaults: WorkspaceDefaults
    datasources: Mapping[str, Mapping[str, Any]]
    products: Mapping[str, Mapping[str, Any]]
    recipes: Mapping[str, Recipe]

    @property
    def configured(self) -> bool:
        return self.path is not None

    @property
    def product_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.products))

    @property
    def recipe_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.recipes))

    def resolve_app(self, value: str | int | None = None) -> int:
        selected: str | int | None = self.defaults.app if value is None else value
        if type(selected) is int and selected > 0:
            return selected
        if isinstance(selected, str):
            if selected in self.apps:
                return self.apps[selected]
            if selected.isascii() and selected.isdecimal() and int(selected) > 0:
                return int(selected)
        raise WorkspaceError(f"unknown Gravity app alias or id: {selected!r}")

    def product(self, name: str) -> Mapping[str, Any]:
        try:
            return self.products[name]
        except KeyError as exc:
            if not self.products:
                raise WorkspaceNotConfiguredError(
                    "no SQL products are configured; add [products.<name>] to gravity.toml"
                ) from exc
            raise WorkspaceError(f"unknown SQL product: {name}") from exc

    def datasource(self, name: str) -> Mapping[str, Any]:
        try:
            return self.datasources[name]
        except KeyError as exc:
            raise WorkspaceError(f"unknown datasource: {name}") from exc

    def recipe(self, name: str) -> Recipe:
        try:
            return self.recipes[name]
        except KeyError as exc:
            if not self.recipes:
                raise WorkspaceNotConfiguredError(
                    "no recipes are configured; add [recipes.<name>] to gravity.toml"
                ) from exc
            raise WorkspaceError(f"unknown recipe: {name}") from exc


def user_cache_root(environ: Mapping[str, str] | None = None) -> Path:
    """Return a platform-appropriate cache root without creating it."""

    env = os.environ if environ is None else environ
    configured = env.get("GRAVITY_CACHE_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        local = env.get("LOCALAPPDATA", "").strip()
        if local:
            return (Path(local).expanduser() / "gravity-sdk").resolve()
    xdg = env.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        return (Path(xdg).expanduser() / "gravity-sdk").resolve()
    return (Path.home() / ".cache" / "gravity-sdk").resolve()


def find_workspace(start: str | Path | None = None) -> Path | None:
    """Search from *start* through its parents for ``gravity.toml``."""

    current = Path.cwd() if start is None else Path(start).expanduser()
    current = current.resolve()
    if current.is_file():
        current = current.parent
    for candidate_root in (current, *current.parents):
        candidate = candidate_root / WORKSPACE_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_workspace(
    workspace: str | Path | None = None,
    *,
    start: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    cache_root: str | Path | None = None,
) -> Workspace:
    """Resolve and load a workspace without writing to it.

    Selection precedence is an explicit path, ``GRAVITY_WORKSPACE``, then an
    upward search from *start* (or the current working directory).
    """

    env = os.environ if environ is None else environ
    explicit = workspace
    if explicit is None:
        configured = env.get(WORKSPACE_ENV, "").strip()
        explicit = configured or None
    path = _explicit_workspace_path(explicit) if explicit is not None else find_workspace(start)
    selected_cache = (
        Path(cache_root).expanduser().resolve()
        if cache_root is not None
        else user_cache_root(env)
    )
    if path is None:
        state_root = selected_cache / "default"
        return Workspace(
            path=None,
            root=state_root,
            state_root=state_root,
            apps={},
            defaults=WorkspaceDefaults(app=None, timezone="UTC", time_window=None),
            datasources={},
            products={},
            recipes={},
        )

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise WorkspaceError(f"cannot read Gravity workspace {path}: {exc}") from exc
    apps, defaults, datasources, products, recipes = _validate_workspace(data, path)
    state_root = _workspace_state_root(selected_cache, path)
    return Workspace(
        path=path,
        root=path.parent,
        state_root=state_root,
        apps=apps,
        defaults=defaults,
        datasources=datasources,
        products=products,
        recipes=recipes,
    )


def require_products(workspace: Workspace | None = None) -> tuple[str, ...]:
    selected = load_workspace() if workspace is None else workspace
    if not selected.products:
        raise WorkspaceNotConfiguredError(
            "no SQL products are configured; add [products.<name>] to gravity.toml"
        )
    return selected.product_names


def _explicit_workspace_path(value: str | Path) -> Path:
    selected = Path(value).expanduser().resolve()
    if selected.is_dir():
        selected = selected / WORKSPACE_FILENAME
    if not selected.is_file():
        raise WorkspaceError(f"Gravity workspace does not exist: {selected}")
    return selected


def _workspace_state_root(cache_root: Path, path: Path) -> Path:
    digest = hashlib.sha256(str(path).casefold().encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.parent.name).strip("-.")
    return cache_root / "workspaces" / f"{slug or 'workspace'}-{digest}"


def _validate_workspace(
    value: Any, path: Path
) -> tuple[
    dict[str, int],
    WorkspaceDefaults,
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, Recipe],
]:
    if not isinstance(value, dict):
        raise WorkspaceError(f"{path}: workspace root must be a table")
    allowed = {
        "schema_version",
        "apps",
        "defaults",
        "datasources",
        "products",
        "recipes",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise WorkspaceError(f"{path}: unknown workspace fields: {', '.join(unknown)}")
    if value.get("schema_version") != 1 or type(value.get("schema_version")) is not int:
        raise WorkspaceError(f"{path}: schema_version must be integer 1")
    for section in ("apps", "defaults", "datasources", "products"):
        if not isinstance(value.get(section), dict):
            raise WorkspaceError(f"{path}: [{section}] must be present and must be a table")

    apps = _validate_apps(value["apps"], path)
    defaults = _validate_defaults(value["defaults"], apps, path)
    datasources = _validate_datasources(value["datasources"], path)
    products = _validate_products(value["products"], apps, datasources, path)
    recipes = validate_recipes(
        value.get("recipes", {}), apps, path, error=WorkspaceError
    )
    return apps, defaults, datasources, products, recipes


def _validate_apps(value: Mapping[str, Any], path: Path) -> dict[str, int]:
    apps: dict[str, int] = {}
    for alias, app_id in value.items():
        if not _NAME_RE.fullmatch(alias):
            raise WorkspaceError(f"{path}: invalid app alias: {alias!r}")
        if type(app_id) is not int or app_id <= 0:
            raise WorkspaceError(f"{path}: app {alias!r} must be a positive integer")
        apps[alias] = app_id
    return apps


def _validate_defaults(
    value: Mapping[str, Any], apps: Mapping[str, int], path: Path
) -> WorkspaceDefaults:
    required = {"app", "timezone", "time_window"}
    if set(value) != required:
        missing = sorted(required - set(value))
        unknown = sorted(set(value) - required)
        detail = [*(f"missing {item}" for item in missing), *(f"unknown {item}" for item in unknown)]
        raise WorkspaceError(f"{path}: invalid [defaults]: {', '.join(detail)}")
    app = value["app"]
    timezone_name = value["timezone"]
    time_window = value["time_window"]
    if not isinstance(app, str) or app not in apps:
        raise WorkspaceError(f"{path}: defaults.app must name an alias in [apps]")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise WorkspaceError(f"{path}: defaults.timezone must be a non-empty IANA name")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise WorkspaceError(f"{path}: unknown timezone: {timezone_name}") from exc
    if not isinstance(time_window, str) or not time_window.strip():
        raise WorkspaceError(f"{path}: defaults.time_window must be a non-empty string")
    return WorkspaceDefaults(app=app, timezone=timezone_name, time_window=time_window)


def _validate_datasources(
    value: Mapping[str, Any], path: Path
) -> dict[str, Mapping[str, Any]]:
    datasources: dict[str, Mapping[str, Any]] = {}
    ids: set[str] = set()
    for name, raw in value.items():
        if not _NAME_RE.fullmatch(name) or not isinstance(raw, dict):
            raise WorkspaceError(f"{path}: invalid datasource definition: {name!r}")
        datasource_id = raw.get("id")
        status = raw.get("verification_status")
        if not isinstance(datasource_id, str) or not datasource_id.strip():
            raise WorkspaceError(f"{path}: datasource {name!r} requires a non-empty id")
        if datasource_id in ids:
            raise WorkspaceError(f"{path}: duplicate datasource id: {datasource_id}")
        if status not in _VERIFICATION_STATUSES:
            raise WorkspaceError(f"{path}: datasource {name!r} has invalid verification_status")
        _ensure_json_value(raw, f"datasources.{name}", path)
        ids.add(datasource_id)
        datasources[name] = dict(raw)
    return datasources


def _validate_products(
    value: Mapping[str, Any],
    apps: Mapping[str, int],
    datasources: Mapping[str, Mapping[str, Any]],
    path: Path,
) -> dict[str, Mapping[str, Any]]:
    products: dict[str, Mapping[str, Any]] = {}
    for name, raw in value.items():
        if not _NAME_RE.fullmatch(name) or not isinstance(raw, dict):
            raise WorkspaceError(f"{path}: invalid product definition: {name!r}")
        kind = raw.get("kind")
        datasource = raw.get("datasource")
        selected_apps = raw.get("apps")
        claims = raw.get("forbidden_claims")
        if kind not in _PRODUCT_KINDS:
            raise WorkspaceError(f"{path}: product {name!r} has unsupported kind: {kind!r}")
        if datasource not in datasources:
            raise WorkspaceError(f"{path}: product {name!r} references unknown datasource")
        if not isinstance(selected_apps, list) or not selected_apps:
            raise WorkspaceError(f"{path}: product {name!r} requires a non-empty apps array")
        for app in selected_apps:
            if not (type(app) is int and app > 0) and not (
                isinstance(app, str) and app in apps
            ):
                raise WorkspaceError(f"{path}: product {name!r} has an unknown app: {app!r}")
        _string_list(claims, f"products.{name}.forbidden_claims", path, allow_empty=False)
        _validate_custom_sql_product(name, raw, path)
        _ensure_json_value(raw, f"products.{name}", path)
        products[name] = dict(raw)
    return products


def _validate_custom_sql_product(
    name: str, raw: Mapping[str, Any], path: Path
) -> None:
    sql = raw.get("sql")
    fields = _string_list(
        raw.get("output_fields"), f"products.{name}.output_fields", path, allow_empty=False
    )
    if not isinstance(sql, str) or not sql.strip():
        raise WorkspaceError(f"{path}: products.{name}.sql must be non-empty")
    placeholders: set[str] = set()
    try:
        for _literal, field, format_spec, conversion in Formatter().parse(sql):
            if field is not None:
                placeholders.add(field)
                if format_spec or conversion:
                    raise ValueError("format modifiers are not allowed")
    except ValueError as exc:
        raise WorkspaceError(f"{path}: products.{name}.sql has invalid placeholders") from exc
    required = {"app_ids", "start", "end", "limit"}
    if placeholders != required:
        raise WorkspaceError(
            f"{path}: products.{name}.sql placeholders must be exactly "
            "{app_ids}, {start}, {end}, and {limit}"
        )
    _validate_output_fields(name, fields, path)
    if raw.get("privacy") != "aggregate":
        raise WorkspaceError(f"{path}: products.{name}.privacy must be 'aggregate'")
    max_rows = raw.get("max_rows")
    if type(max_rows) is not int or not 1 <= max_rows <= 10000:
        raise WorkspaceError(f"{path}: products.{name}.max_rows must be between 1 and 10000")


def _validate_output_fields(name: str, fields: list[str], path: Path) -> None:
    if len(fields) != len(set(fields)):
        raise WorkspaceError(f"{path}: products.{name}.output_fields contains duplicates")
    if any(not _OUTPUT_FIELD_RE.fullmatch(field) for field in fields):
        raise WorkspaceError(
            f"{path}: products.{name}.output_fields contains an invalid field name"
        )
    if {field.casefold() for field in fields} & _SENSITIVE_OUTPUT_FIELDS:
        raise WorkspaceError(f"{path}: products.{name}.output_fields contains a user-level field")


def _string_list(value: Any, field: str, path: Path, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty) or not all(
        isinstance(item, str) and bool(item) for item in value
    ):
        raise WorkspaceError(f"{path}: {field} must be a {'non-empty ' if not allow_empty else ''}string array")
    return value


def _ensure_json_value(value: Any, field: str, path: Path) -> None:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise WorkspaceError(f"{path}: {field} contains a non-JSON value") from exc


__all__ = [
    "WORKSPACE_ENV",
    "WORKSPACE_FILENAME",
    "Workspace",
    "WorkspaceDefaults",
    "WorkspaceError",
    "WorkspaceNotConfiguredError",
    "Recipe",
    "RecipeBindings",
    "find_workspace",
    "load_workspace",
    "require_products",
    "user_cache_root",
]
