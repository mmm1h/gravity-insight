from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import scripts.generate_skill_library as builder


ROOT = Path(__file__).resolve().parents[1]


class SkillLibraryBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.outputs = builder.render_outputs()
        cls.index = json.loads(cls.outputs["index.json"])
        cls.source = json.loads(cls.outputs["source.json"])
        cls.build_manifest = json.loads(cls.outputs["build-manifest.json"])

    def test_two_builds_are_byte_identical(self) -> None:
        self.assertEqual(self.outputs, builder.render_outputs())

    def test_build_contains_docs_packages_archives_and_indexes(self) -> None:
        self.assertEqual(283, len(self.outputs))
        self.assertEqual(40, sum(path.startswith("docs/") for path in self.outputs))
        self.assertEqual(200, sum(path.startswith("packages/") for path in self.outputs))
        self.assertEqual(40, sum(path.endswith(".zip") for path in self.outputs))

    def test_hub_index_contains_every_canonical_skill_once(self) -> None:
        identities = [item["skill_uri"] for item in self.index["skills"]]
        self.assertEqual(40, len(identities))
        self.assertEqual(sorted(identities), identities)
        self.assertEqual(len(identities), len(set(identities)))

    def test_archive_metadata_is_reproducible(self) -> None:
        archive = next(content for path, content in self.outputs.items() if path.endswith(".zip"))
        with zipfile.ZipFile(io.BytesIO(archive)) as selected:
            self.assertEqual(5, len(selected.infolist()))
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

    def test_static_hub_source_points_to_release_payload(self) -> None:
        self.assertEqual("static_https", self.source["transport"])
        self.assertIsNone(self.source["git"])
        self.assertTrue(self.source["https"]["index_url"].endswith("/index.json"))
        self.assertEqual(builder._source_digest(), self.source["https"]["source_revision"])

    def test_build_manifest_hashes_every_prior_output(self) -> None:
        rows = {row["path"]: row for row in self.build_manifest["files"]}
        self.assertEqual(set(self.outputs) - {"build-manifest.json"}, set(rows))
        for path, row in rows.items():
            content = self.outputs[path]
            self.assertEqual(len(content), row["size_bytes"])
            self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])

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
