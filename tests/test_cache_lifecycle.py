"""Offline cache lifecycle, privacy, old-location hits and destructive boundaries."""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_insight import __main__ as entry
from gravity_insight import cache_cli, cache_disk, cache_lifecycle as lifecycle
from gravity_insight import runtime_scope
from gravity_insight.support import cache_files, cache_paths
from gravity_insight.workspace import user_cache_root


SCOPE = "a" * 32
DIGEST = "b" * 64
NOW = 2_000_000_000


class CacheFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "canonical"
        self.legacy = self.base / "local" / "GravityInsight"
        self.root.mkdir()
        self.environment = patch.dict(os.environ, {
            "GRAVITY_CACHE_HOME": str(self.root), "LOCALAPPDATA": str(self.base / "local"),
            "XDG_CACHE_HOME": str(self.base / "xdg"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.home = patch.object(Path, "home", return_value=self.base / "home")
        self.home.start()
        self.addCleanup(self.home.stop)

    def put(self, relative: str, *, root: Path | None = None, age: int = 30,
            content: bytes = b"offline fixture") -> Path:
        path = (root or self.root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        modified = NOW - age * 86400
        os.utime(path, (modified, modified))
        return path

    def scan(self, **options):
        return lifecycle.inventory(roots=[self.root, self.legacy], now=NOW, **options)

    def prune(self, **options):
        return lifecycle.prune(roots=[self.root, self.legacy], now=NOW, **options)


class CacheRootTests(CacheFixture):
    def test_one_normalized_root_honors_override_and_tilde(self):
        with patch.dict(os.environ, {"GRAVITY_CACHE_HOME": "~/cache/../chosen"}):
            self.assertEqual(runtime_scope.gravity_insight_cache_root(), user_cache_root())
            self.assertEqual(user_cache_root(), Path("~/chosen").expanduser().resolve())

    def test_platform_defaults_share_one_root(self):
        for environment in ({"LOCALAPPDATA": str(self.base / "local")},
                            {"XDG_CACHE_HOME": str(self.base / "xdg")}, {}):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                self.assertEqual(runtime_scope.gravity_insight_cache_root(), user_cache_root())
                self.assertEqual(user_cache_root().name, "gravity-insight")

    def test_existing_legacy_account_artifacts_remain_reachable(self):
        catalog = self.put(f"{SCOPE}/metadata/catalog.sqlite3", root=self.legacy)
        operation = self.put(f"{SCOPE}/operation-catalog.json", root=self.legacy)
        field = self.put(f"{SCOPE}/field-policy/{DIGEST}.json", root=self.legacy)
        with patch.object(runtime_scope, "runtime_scope_key", side_effect=AssertionError("credentials")):
            self.assertEqual(runtime_scope.metadata_catalog_path(SCOPE), catalog)
            self.assertEqual(runtime_scope.operation_catalog_state_path(SCOPE), operation)
            self.assertEqual(runtime_scope.field_policy_cache_dir(SCOPE), field.parent)
        report, _ = self.scan()
        self.assertEqual(report["roots"][1]["location"], "legacy_residue")
        self.assertEqual(report["roots"][1]["files"], 3)

    def test_per_key_fallback_survives_partially_populated_new_directory(self):
        directory = self.legacy / SCOPE / "field-policy"
        key = ("operation", "input")
        cache_disk.write_snapshot(True, directory, key, {"offline": True}, 600, NOW)
        primary = self.root / SCOPE / "field-policy"
        primary.mkdir(parents=True)
        self.assertEqual(cache_disk.read_snapshot(True, primary, key, 600, NOW + 1),
                         (599, {"offline": True}))
        cache_disk.write_snapshot(True, primary, key, {"new": True}, 600, NOW)
        self.assertEqual(cache_disk.read_snapshot(True, primary, key, 600, NOW + 1)[1], {"new": True})
        cache_disk.clear_snapshots(True, primary)
        self.assertIsNone(cache_disk.read_snapshot(True, primary, key, 600, NOW + 1))

    def test_new_scopes_use_canonical_and_keep_principal_semantics(self):
        scope = runtime_scope.RuntimeScopeKey("path", "account", "principal", "generation", "workspace")
        self.assertEqual(runtime_scope.metadata_catalog_path(SCOPE), self.root / SCOPE / "metadata/catalog.sqlite3")
        self.assertEqual(runtime_scope.principal_state_root(self.root / "default", scope),
                         self.root / "default/principals" / scope.fingerprint)
        self.assertNotEqual(scope.storage_fingerprint, scope.fingerprint)

    def test_redaction_covers_old_location(self):
        selected = self.legacy / SCOPE / "metadata/catalog.sqlite3"
        self.assertNotIn(SCOPE, runtime_scope.redact_scoped_path(selected))

    def test_all_standard_roots_are_discoverable_and_deduplicated(self):
        roots = cache_paths.cache_roots()
        self.assertEqual(roots[0], self.root)
        self.assertIn(self.legacy, roots)
        self.assertIn(self.base / "xdg/GravityInsight", roots)
        self.assertEqual(len(roots), len(set(roots)))


class CacheInventoryTests(CacheFixture):
    def test_four_unbounded_categories_and_metadata_residues_are_separate(self):
        for relative in (f"default/principals/{SCOPE}/state.json", "default/receipts/run.json",
                         f"workspaces/private-project/skill-hub-cas/skills/sha256/{DIGEST}/skill.json",
                         f"default/skill-maintenance/generations/{DIGEST}.json",
                         f"{SCOPE}/field-policy/{DIGEST}.pkl", f"{SCOPE}/metadata/catalog.sqlite3",
                         f"{'c' * 32}/metadata/catalog.sqlite3"):
            self.put(relative)
        with patch.object(lifecycle, "allocated_bytes", return_value=4096), patch.object(Path, "read_text", side_effect=AssertionError("payload read")), patch.object(Path, "read_bytes", side_effect=AssertionError("payload read")):
            report, _ = self.scan()
        self.assertEqual(report["summary"]["files"], 7)
        self.assertEqual(report["summary"]["disk_bytes"], 7 * 4096)
        self.assertEqual(report["summary"]["reclaimable"]["files"], 1)
        rows = {row["category"]: row for row in report["categories"]}
        for category in ("principals", "receipts", "skill-hub-cas", "skill-maintenance/generations"):
            self.assertEqual(rows[category]["retained"]["files"], 1)
        self.assertFalse(report["metadata_size_peers"][0]["verified_duplicate"])
        rendered = json.dumps(report)
        for secret in (SCOPE, DIGEST, "private-project", str(self.root)):
            self.assertNotIn(secret, rendered)

    def test_unknown_allocation_is_not_fabricated_as_zero(self):
        self.put("default/receipts/one.json")
        with patch.object(lifecycle, "allocated_bytes", return_value=None):
            report, _ = self.scan(max_disk_bytes=0)
        self.assertIsNone(report["summary"]["disk_bytes"])
        self.assertFalse(report["budget"]["assessment_complete"])

    def test_native_allocation_is_available_without_content_read(self):
        path = self.put("default/receipts/one.json", content=b"x" * 8192)
        measured = cache_files.allocated_bytes(path, path.stat())
        if os.name == "nt" or hasattr(path.stat(), "st_blocks"):
            self.assertIsNotNone(measured)
            self.assertGreaterEqual(measured, 0)

    def test_http_retention_is_reported_as_best_effort_not_hard_limit(self):
        self.put(f"default/principals/{SCOPE}/receipts/http/{os.getpid()}-{'d' * 32}-one.json")
        with patch.dict(os.environ, {"GRAVITY_HTTP_RECEIPT_MAX_FILES": "1", "GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS": "7"}):
            report, rows = self.scan(max_files=0)
        self.assertEqual(rows[0].reason, "LIVE_PROCESS")
        self.assertFalse(report["http_receipts"]["hard_limit"])
        self.assertEqual(report["http_receipts"]["retained_over_budget_directories"], 1)
        self.assertTrue(report["budget"]["retained_over_budget"])
        self.assertIn("FILE_BUDGET_EXCEEDED", report["budget"]["reason_codes"])

    def test_credentials_get_stat_only_never_allocation_handle(self):
        self.put("default/.env.gravity.local", content=b"synthetic-only")
        with patch.object(lifecycle, "allocated_bytes", side_effect=AssertionError("credential opened")):
            report, _ = self.scan()
        self.assertEqual(report["summary"]["allocation_unknown_files"], 1)
        self.assertNotIn(".env.gravity.local", json.dumps(report))

    def test_nested_roots_are_counted_once(self):
        nested = self.root / "old"
        self.put("default/receipts/one.json", root=nested)
        report, _ = lifecycle.inventory(roots=[self.root, nested], now=NOW)
        self.assertEqual(report["summary"]["files"], 1)


class CachePruneTests(CacheFixture):
    def test_dry_run_and_execute_remove_only_proven_dead_files(self):
        dead = self.put(f"{SCOPE}/field-policy/{DIGEST}.pkl", root=self.legacy)
        staging = self.put(f"{SCOPE}/.operation-catalog.json.987654321.123.tmp", root=self.legacy)
        keep = self.put(f"{SCOPE}/field-policy/{DIGEST}.json", root=self.legacy)
        with patch.object(lifecycle, "_process_is_alive", return_value=False):
            preview = self.prune()
            self.assertEqual(preview["mode"], "dry-run")
            self.assertEqual(preview["summary"]["reclaimable"]["files"], 2)
            self.assertTrue(dead.exists() and staging.exists())
            actual = self.prune(execute=True)
        self.assertEqual(actual["deleted"]["files"], 2)
        self.assertEqual(actual["after"]["files"], 1)
        self.assertTrue(keep.exists())
        self.assertFalse(dead.exists() or staging.exists())
        self.assertEqual(actual["obligations"]["mutation_certainty"]["state"], "confirmed")
        self.assertEqual(preview["obligations"]["mutation_certainty"]["state"], "not_attempted")

    def test_uncertain_references_never_delete_even_over_budget(self):
        paths = [self.put(relative) for relative in (
            f"default/principals/{SCOPE}/active.json", "default/receipts/audit.json",
            f"default/receipts/http/987654321-{'d' * 32}-ref.json",
            f"default/skill-hub-cas/skills/sha256/{DIGEST}/locked.json",
            f"default/skill-maintenance/generations/{DIGEST}.json")]
        with patch.object(lifecycle, "_process_is_alive", return_value=False):
            report = self.prune(execute=True, max_files=0, max_disk_bytes=0)
        self.assertEqual(report["deleted"]["files"], 0)
        self.assertTrue(all(path.exists() for path in paths))
        self.assertTrue(report["budget"]["retained_over_budget"])
        self.assertTrue(all("UNCERTAIN" in row["reason_code"] for row in report["decisions"]))

    def test_live_staging_owner_is_retained(self):
        path = self.put(f"{SCOPE}/.operation-catalog.json.{os.getpid()}.123.tmp")
        report = self.prune(execute=True)
        self.assertTrue(path.exists())
        self.assertEqual(report["decisions"][0]["reason_code"], "LIVE_PROCESS")

    def test_holds_and_leases_fail_closed_without_reading_markers(self):
        dead = self.put(f"{SCOPE}/field-policy/{DIGEST}.pkl")
        marker = self.put("audit-holds/malformed.json", content=b"not json")
        report = self.prune(execute=True)
        self.assertTrue(dead.exists() and marker.exists())
        self.assertIn("PROTECTION_STATE_PRESENT", {row["reason_code"] for row in report["decisions"]})

    def test_recent_and_unrecognized_pickle_names_are_not_deleted(self):
        recent = self.put(f"{SCOPE}/field-policy/{DIGEST}.pkl", age=1)
        unknown = self.put(f"{SCOPE}/field-policy/unknown.pkl")
        report = self.prune(execute=True)
        self.assertTrue(recent.exists() and unknown.exists())
        self.assertEqual({row["reason_code"] for row in report["decisions"]}, {"RECENT_FILE", "UNKNOWN_ARTIFACT"})

    def test_changed_identity_aborts_delete(self):
        path = self.put(f"{SCOPE}/field-policy/{DIGEST}.pkl")
        before = path.stat()
        path.write_bytes(b"changed since preview")
        with self.assertRaises(OSError):
            cache_files.unlink_unchanged(self.root, path, before)
        self.assertTrue(path.exists())

    def test_busy_delete_is_reported_and_budget_remains_exceeded(self):
        path = self.put(f"{SCOPE}/field-policy/{DIGEST}.pkl")
        with patch.object(lifecycle, "unlink_unchanged", side_effect=OSError("private-path")):
            report = self.prune(execute=True, max_files=0)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["deleted"]["files"], 0)
        self.assertTrue(path.exists())
        self.assertEqual(report["obligations"]["mutation_certainty"]["state"], "uncertain")
        self.assertTrue(report["budget"]["retained_over_budget"])
        self.assertNotIn("private-path", json.dumps(report))

    def test_hardlinked_file_is_retained(self):
        path = self.put(f"{SCOPE}/field-policy/{DIGEST}.pkl")
        os.link(path, self.base / "outside-copy")
        report = self.prune(execute=True)
        self.assertEqual(report["decisions"][0]["reason_code"], "MULTIPLE_LINKS")
        self.assertTrue(path.exists())

    def test_linked_subtree_is_not_followed_or_deleted(self):
        target = self.base / "outside"
        target.mkdir()
        secret = self.put(f"{SCOPE}/field-policy/{DIGEST}.pkl", root=target)
        link = self.root / "linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            # Reparse detection still has deterministic coverage without OS privilege.
            with patch.object(lifecycle, "assert_unlinked", side_effect=OSError("link")):
                report = self.prune(execute=True)
        else:
            self.addCleanup(link.unlink)
            report = self.prune(execute=True)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["deleted"]["files"], 0)
        self.assertTrue(secret.exists())

    def test_current_field_policy_reader_has_no_pickle_import_or_decode(self):
        tree = ast.parse(Path(cache_disk.__file__).read_text(encoding="utf-8"))
        imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        self.assertNotIn("pickle", imports)
        self.assertEqual(cache_disk._path(self.root, ("op", "input")).suffix, ".json")
        self.assertEqual(len(cache_disk._path(self.root, ("op", "input")).stem), 64)


class CacheCliTests(CacheFixture):
    def test_all_help_paths_and_mutually_exclusive_modes(self):
        for args in (["--help"], ["status", "--help"], ["prune", "--help"]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
                cache_cli.main(args)
            self.assertEqual(result.exception.code, 0)
            self.assertIn("gravity cache", output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            cache_cli.main(["prune", "--dry-run", "--execute"])
        self.assertEqual(result.exception.code, 2)

    def test_json_dispatch_bypasses_all_startup_and_credentials(self):
        self.put(f"{SCOPE}/field-policy/{DIGEST}.pkl")
        for command in ("status", "prune"):
            output = io.StringIO()
            with patch.object(entry, "_startup_upgrade_exit", side_effect=AssertionError("network")), patch.object(entry, "_startup_skill_maintenance", side_effect=AssertionError("mutation")), patch.object(entry, "ensure_first_run_credentials", side_effect=AssertionError("credentials")), contextlib.redirect_stdout(output):
                code = entry.main(["cache", command, "--json"])
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["schema_version"], "gravity.cache-inventory.v1")
            self.assertFalse(report["network_called"])
            self.assertNotIn(SCOPE, output.getvalue())

    def test_text_output_contains_files_allocation_and_retention_reasons(self):
        self.put("default/receipts/run.json")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cache_cli.main(["status"]), 0)
        for text in ("files", "logical", "disk", "AUDIT_REFERENCES_UNCERTAIN", "not a hard limit"):
            self.assertIn(text, output.getvalue())

    def test_json_errors_do_not_disclose_paths(self):
        output = io.StringIO()
        with patch.object(cache_cli, "inventory", side_effect=OSError(str(self.root / SCOPE))), contextlib.redirect_stdout(output):
            self.assertNotEqual(cache_cli.main(["status", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["reason_code"], "CACHE_INVENTORY_FAILED")
        self.assertNotIn(SCOPE, output.getvalue())
