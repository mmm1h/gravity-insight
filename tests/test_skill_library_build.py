from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import scripts.generate_skill_library as builder
from gravity_insight.agent_runtime_contracts import (
    AgentRuntimeContractError,
    validate_schema,
)
from gravity_insight.skill_package import SkillPackageError


ROOT = Path(__file__).resolve().parents[1]


def _entry_for_archive(entry: dict, archive: bytes) -> dict:
    selected = copy.deepcopy(entry)
    selected["archive"]["size_bytes"] = len(archive)
    selected["archive"]["sha256"] = hashlib.sha256(archive).hexdigest()
    return selected


class SkillLibraryBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.outputs = builder.render_outputs()
        cls.index = json.loads(cls.outputs["index.json"])
        cls.agent_index = json.loads(cls.outputs["agent-index.json"])
        cls.source = json.loads(cls.outputs["source.json"])
        cls.build_manifest = json.loads(cls.outputs["build-manifest.json"])

    def test_two_builds_are_byte_identical(self) -> None:
        self.assertEqual(self.outputs, builder.render_outputs())

    def test_build_contains_docs_packages_archives_and_indexes(self) -> None:
        self.assertEqual(607, len(self.outputs))
        self.assertEqual(43, sum(path.startswith("docs/") for path in self.outputs))
        self.assertEqual(258, sum(path.startswith("packages/") for path in self.outputs))
        self.assertEqual(
            215,
            sum(path.startswith("agent-skills/") for path in self.outputs),
        )
        self.assertEqual(
            43,
            sum(path.startswith("runtime-skill-") for path in self.outputs),
        )
        self.assertEqual(
            43,
            sum(
                path.startswith("agent-skill-") and path.endswith(".zip")
                for path in self.outputs
            ),
        )

    def test_hub_index_contains_every_canonical_skill_once(self) -> None:
        identities = [item["skill_uri"] for item in self.index["skills"]]
        self.assertEqual(43, len(identities))
        self.assertEqual(sorted(identities), identities)
        self.assertEqual(len(identities), len(set(identities)))

    def test_agent_index_contains_every_canonical_skill_once(self) -> None:
        identities = [item["skill_uri"] for item in self.agent_index["skills"]]
        names = [item["name"] for item in self.agent_index["skills"]]
        self.assertEqual(43, len(identities))
        self.assertEqual(sorted(identities), identities)
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(
            builder._source_digest(),
            self.agent_index["canonical_source_sha256"],
        )

    def test_agent_index_schema_rejects_readiness_drift(self) -> None:
        self.assertEqual(
            builder.AGENT_INDEX_SCHEMA_PATH.read_bytes(),
            self.outputs["agent-skill-index-v1.schema.json"],
        )
        changed = copy.deepcopy(self.agent_index)
        changed["skills"][0]["readiness"] = "available"
        with self.assertRaisesRegex(AgentRuntimeContractError, "does not match"):
            validate_schema(
                changed,
                "agent-skill-index-v1.schema.json",
                "Agent Skill index",
            )

    def test_archive_metadata_is_reproducible(self) -> None:
        archive = next(
            content
            for path, content in self.outputs.items()
            if path.startswith("runtime-skill-")
        )
        with zipfile.ZipFile(io.BytesIO(archive)) as selected:
            self.assertEqual(6, len(selected.infolist()))
            for item in selected.infolist():
                self.assertEqual((1980, 1, 1, 0, 0, 0), item.date_time)
                self.assertEqual(zipfile.ZIP_STORED, item.compress_type)
                self.assertEqual(0o100644, item.external_attr >> 16)

    def test_archive_manifest_is_the_canonical_manifest(self) -> None:
        entry = self.index["skills"][0]
        archive = self.outputs[entry["archive"]["path"]]
        with zipfile.ZipFile(io.BytesIO(archive)) as selected:
            manifest = json.loads(selected.read("manifest.json"))
        self.assertEqual(entry["manifest"], manifest)

    def test_unpacked_package_is_the_same_archive_content(self) -> None:
        entry = self.index["skills"][0]
        manifest = entry["manifest"]
        prefix = f"packages/{manifest['namespace']}.{manifest['skill_id']}/"
        with zipfile.ZipFile(io.BytesIO(self.outputs[entry["archive"]["path"]])) as selected:
            for name in selected.namelist():
                self.assertEqual(selected.read(name), self.outputs[prefix + name])

    def test_docs_are_rendered_from_the_same_manifest(self) -> None:
        entry = self.index["skills"][0]
        manifest = entry["manifest"]
        path = f"docs/{manifest['namespace']}/{manifest['skill_id']}.md"
        self.assertIn(manifest["guide"]["title"], self.outputs[path].decode("utf-8"))

    def test_agent_exports_are_bounded_progressive_disclosure_packages(self) -> None:
        expected = {
            "SKILL.md",
            "references/GUIDE.md",
            "references/SCHEMA.json",
            "references/CLAIMS.md",
            "references/EXAMPLES.md",
        }
        for entry in self.agent_index["skills"]:
            with self.subTest(skill=entry["skill_uri"]):
                self.assertEqual(entry["name"], entry["directory"])
                self.assertEqual(expected, {item["path"] for item in entry["files"]})
                prefix = f"agent-skills/{entry['directory']}/"
                skill = self.outputs[prefix + "SKILL.md"].decode("utf-8")
                self.assertTrue(skill.startswith("---\nname: "))
                self.assertIn("Read `references/GUIDE.md`", skill)
                combined = b"\n".join(
                    self.outputs[prefix + item["path"]] for item in entry["files"]
                )
                self.assertNotIn(b"https://", combined)

    def test_agent_archive_matches_index_and_unpacked_projection(self) -> None:
        for entry in self.agent_index["skills"]:
            archive = self.outputs[entry["archive"]["path"]]
            builder.validate_agent_archive(archive, entry)
            prefix = f"agent-skills/{entry['directory']}/"
            with zipfile.ZipFile(io.BytesIO(archive)) as selected:
                self.assertEqual(
                    [f"{entry['directory']}/{item['path']}" for item in entry["files"]],
                    selected.namelist(),
                )
                for item in entry["files"]:
                    archived = selected.read(f"{entry['directory']}/{item['path']}")
                    self.assertEqual(self.outputs[prefix + item["path"]], archived)

    def test_agent_archive_rejects_path_escape_and_content_tampering(self) -> None:
        entry = self.agent_index["skills"][0]
        archive = self.outputs[entry["archive"]["path"]]
        changed = copy.deepcopy(entry)
        changed["archive"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(SkillPackageError, "metadata drifted"):
            builder.validate_agent_archive(archive, changed)

        escaped = builder._zip({"../SKILL.md": b"unsafe"})
        with self.assertRaisesRegex(SkillPackageError, "entries"):
            builder.validate_agent_archive(
                escaped,
                _entry_for_archive(entry, escaped),
            )

        files = {
            f"{entry['directory']}/{item['path']}": (
                b"tampered"
                if item["path"] == "SKILL.md"
                else self.outputs[f"agent-skills/{entry['directory']}/{item['path']}"]
            )
            for item in entry["files"]
        }
        tampered = builder._zip(files)
        with self.assertRaisesRegex(SkillPackageError, "content drifted"):
            builder.validate_agent_archive(
                tampered,
                _entry_for_archive(entry, tampered),
            )

    def test_exportability_does_not_promote_declared_readiness(self) -> None:
        runtime = {item["skill_uri"]: item for item in self.index["skills"]}
        blocked = next(
            item for item in self.agent_index["skills"] if item["readiness"] == "blocked"
        )
        executable = next(
            item for item in self.agent_index["skills"] if item["readiness"] == "executable"
        )
        for entry in (blocked, executable):
            manifest = runtime[entry["skill_uri"]]["manifest"]
            self.assertEqual(manifest["readiness"], entry["readiness"])
            self.assertEqual(manifest["validation"], entry["validation"])
            self.assertEqual(
                runtime[entry["skill_uri"]]["package"]["package_digest"],
                entry["package_digest"],
            )
        self.assertEqual("unvalidated", blocked["validation"])
        self.assertEqual("validated", executable["validation"])

    def test_static_hub_source_points_to_release_payload(self) -> None:
        self.assertEqual("static_https", self.source["transport"])
        self.assertIsNone(self.source["git"])
        self.assertTrue(self.source["https"]["index_url"].endswith("/index.json"))
        self.assertEqual(builder._source_digest(), self.source["https"]["source_revision"])
        remote_archives = [
            item["archive"]["path"] for item in self.index["skills"]
        ] + [
            item["archive"]["path"] for item in self.agent_index["skills"]
        ]
        self.assertTrue(all("/" not in path for path in remote_archives))
        self.assertTrue(all(path in self.outputs for path in remote_archives))

    def test_build_manifest_hashes_every_prior_output(self) -> None:
        rows = {row["path"]: row for row in self.build_manifest["files"]}
        self.assertEqual(set(self.outputs) - {"build-manifest.json"}, set(rows))
        for path, row in rows.items():
            content = self.outputs[path]
            self.assertEqual(len(content), row["size_bytes"])
            self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])

    def test_build_manifest_names_exact_flat_release_assets(self) -> None:
        rows = {row["path"]: row for row in self.build_manifest["release_assets"]}
        expected = {
            path
            for path in self.outputs
            if builder._is_release_asset(path)
        }
        self.assertEqual(expected, set(rows))
        self.assertEqual(90, len(rows))
        self.assertTrue(all("/" not in path for path in rows))
        for path, row in rows.items():
            content = self.outputs[path]
            self.assertEqual(len(content), row["size_bytes"])
            self.assertEqual(
                hashlib.sha256(content).hexdigest(),
                row["sha256"],
            )

    def test_every_package_file_matches_its_index_hash(self) -> None:
        for entry in self.index["skills"]:
            manifest = entry["manifest"]
            prefix = f"packages/{manifest['namespace']}.{manifest['skill_id']}/"
            for row in entry["package"]["files"]:
                content = self.outputs[prefix + row["path"]]
                with self.subTest(skill=entry["skill_uri"], path=row["path"]):
                    self.assertEqual(row["size_bytes"], len(content))
                    self.assertEqual(row["sha256"], hashlib.sha256(content).hexdigest())

    def test_write_outputs_recreates_the_rendered_tree(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            target = Path(temporary)
            builder._write_outputs(target, self.outputs)
            for path, content in self.outputs.items():
                self.assertEqual(content, target.joinpath(*path.split("/")).read_bytes())

    def test_gitignore_blocks_generated_zip_outputs(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("build/", ignore.splitlines())
        self.assertIn("*.zip", ignore.splitlines())

    def test_build_check_accepts_the_current_source(self) -> None:
        self.assertEqual(0, builder.main(["--check"]))


if __name__ == "__main__":
    unittest.main()
