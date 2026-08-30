from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from gravity_insight.skill_hub_archive import (
    validate_skill_archive,
    validate_skill_directory,
    validate_trusted_wheel,
)
from gravity_insight.skill_hub_cas import SkillHubCAS
from gravity_insight.skill_hub_contract import SkillHubContractError, compile_hub_index
from gravity_insight.skill_hub_locks import build_skills_lock
from gravity_insight.skill_hub_source import HubSourceSession, _https_get, sync_hub_source
from gravity_insight.skill_hub_state import atomic_write_json, read_json
from gravity_insight.skill_render import render_package_files
from tests.test_skill_hub_contracts import (
    git_source,
    hub_index,
    skill_entry,
    team_manifest,
    trusted_entry,
)


def zip_bytes(files: dict[str, bytes], *, modes: dict[str, int] | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 22, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((modes or {}).get(name, stat.S_IFREG | 0o644)) << 16
            archive.writestr(info, content)
    return output.getvalue()


def skill_archive(entry: dict) -> bytes:
    artifact = {
        "contract": entry["manifest"],
        "digest": entry["package"]["manifest_digest"],
        "skill_uri": entry["skill_uri"],
    }
    return zip_bytes(render_package_files(artifact))


def trusted_wheel(*, groups=("gravity.models", "gravity.operators")) -> bytes:
    distribution = "gravity-team-forecast-methods"
    version = "1.2.3"
    dist_info = "gravity_team_forecast_methods-1.2.3.dist-info"
    sections = "\n".join(
        f"[{group}]\nexample = gravity_team_forecast_methods:factory\n"
        for group in groups
    )
    files = {
        "gravity_team_forecast_methods/__init__.py": b"def factory():\n    return None\n",
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.4\nName: {distribution}\nVersion: {version}\n"
            "Gravity-Trusted-Pack-ID: trusted-pack://team/forecast-methods@1\n\n"
        ).encode("utf-8"),
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{dist_info}/RECORD": b"",
        f"{dist_info}/entry_points.txt": sections.encode("utf-8"),
    }
    return zip_bytes(files)


def bound_entry(entry: dict, content: bytes) -> dict:
    selected = copy.deepcopy(entry)
    import hashlib

    selected["archive"]["sha256"] = hashlib.sha256(content).hexdigest()
    selected["archive"]["size_bytes"] = len(content)
    if "descriptor" in selected:
        selected["descriptor"]["wheel_sha256"] = selected["archive"]["sha256"]
        from gravity_insight.trusted_pack_contract import compile_trusted_pack_descriptor

        selected["descriptor_digest"] = compile_trusted_pack_descriptor(
            selected["descriptor"]
        )["digest"]
    return selected


class GitHubFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        self.git(self.root, "init", "-b", "main")
        self.git(self.root, "config", "user.name", "Hub Test")
        self.git(self.root, "config", "user.email", "hub@example.invalid")
        self.git(
            self.root,
            "remote",
            "add",
            "origin",
            "https://github.com/example/team-skills.git",
        )

    def publish(self, index: dict, artifacts: dict[str, bytes]) -> str:
        path = self.root / "hub" / "index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        for relative, content in artifacts.items():
            target = self.root.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.git(self.root, "add", "-A")
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_DATE": "2026-08-22T00:00:00+00:00",
                "GIT_COMMITTER_DATE": "2026-08-22T00:00:00+00:00",
            }
        )
        self.git(self.root, "commit", "-m", "publish", environment=environment)
        return self.git(self.root, "rev-parse", "HEAD")

    def clone(self, name: str) -> Path:
        target = Path(self.temporary.name) / name
        subprocess.run(
            ["git", "clone", "--quiet", str(self.root), str(target)],
            check=True,
        )
        self.git(
            target,
            "remote",
            "set-url",
            "origin",
            "https://github.com/example/team-skills.git",
        )
        return target

    def close(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def git(
        root: Path, *arguments: str, environment: dict[str, str] | None = None
    ) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        ).stdout.strip()


class SkillHubIoTests(unittest.TestCase):
    def setUp(self) -> None:
        raw_entry = skill_entry()
        self.skill_zip = skill_archive(raw_entry)
        self.skill = bound_entry(raw_entry, self.skill_zip)
        self.wheel = trusted_wheel()
        self.trusted = trusted_entry(self.wheel)
        self.index_value = hub_index(skills=[self.skill], packs=[self.trusted])

    def test_two_clean_git_checkouts_resolve_byte_identical_locks(self) -> None:
        fixture = GitHubFixture()
        try:
            fixture.publish(
                self.index_value,
                {
                    self.skill["archive"]["path"]: self.skill_zip,
                    self.trusted["archive"]["path"]: self.wheel,
                },
            )
            left = sync_hub_source(
                git_source(), repository=fixture.clone("left"), runtime_version="0.3.0"
            )
            right = sync_hub_source(
                git_source(), repository=fixture.clone("right"), runtime_version="0.3.0"
            )
            identity = self.skill["skill_uri"]
            left_lock = build_skills_lock(
                left.index, left.reference(), [identity], runtime_version="0.3.0"
            )
            right_lock = build_skills_lock(
                right.index, right.reference(), [identity], runtime_version="0.3.0"
            )
        finally:
            fixture.close()

        self.assertEqual(left.reference(), right.reference())
        self.assertEqual(left_lock, right_lock)
        self.assertFalse(left.network_called)

    def test_git_session_remains_pinned_after_branch_moves(self) -> None:
        fixture = GitHubFixture()
        try:
            first = fixture.publish(
                self.index_value,
                {self.skill["archive"]["path"]: self.skill_zip},
            )
            session = sync_hub_source(git_source(), repository=fixture.root)
            changed = copy.deepcopy(self.index_value)
            changed["index_version"] = 1
            fixture.publish(changed, {"new.txt": b"new"})

            self.assertEqual(first, session.source_revision)
            self.assertEqual(self.skill_zip, session.read_artifact(self.skill["archive"]["path"]))
        finally:
            fixture.close()

    def test_git_blob_size_is_rejected_before_reading_oversized_output(self) -> None:
        manifest = team_manifest()
        manifest["description"] = "x" * 1024
        oversized_index = hub_index(skills=[skill_entry(manifest)], packs=[])
        fixture = GitHubFixture()
        try:
            fixture.publish(oversized_index, {})
            source = git_source()
            source["limits"]["max_index_bytes"] = 1024
            with self.assertRaisesRegex(
                SkillHubContractError, "HUB_SOURCE_OUTPUT_LIMIT"
            ):
                sync_hub_source(source, repository=fixture.root)
        finally:
            fixture.close()

    def test_git_mirror_rejects_a_linked_parent_before_resolution(self) -> None:
        fixture = GitHubFixture()
        try:
            fixture.publish(self.index_value, {})
            parent = Path(fixture.temporary.name) / "linked-parent"
            try:
                parent.symlink_to(fixture.root.parent, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaisesRegex(
                SkillHubContractError, "HUB_SOURCE_UNAVAILABLE"
            ):
                sync_hub_source(
                    git_source(), repository=parent / fixture.root.name
                )
        finally:
            fixture.close()

    def test_static_https_uses_only_exact_fake_urls_and_reports_network(self) -> None:
        source = git_source()
        source.update(
            {
                "transport": "static_https",
                "git": None,
                "https": {
                    "index_url": "https://skills.example.invalid/v1/index.json",
                    "artifact_base_url": "https://skills.example.invalid/v1/artifacts/",
                    "source_revision": "review-1",
                },
            }
        )
        index_bytes = json.dumps(self.index_value).encode("utf-8")
        expected_artifact_url = (
            "https://skills.example.invalid/v1/artifacts/"
            + self.skill["archive"]["path"]
        )
        responses = {
            source["https"]["index_url"]: index_bytes,
            expected_artifact_url: self.skill_zip,
        }
        calls: list[str] = []

        def get(url: str, maximum: int, timeout: int) -> bytes:
            calls.append(url)
            self.assertLessEqual(len(responses[url]), maximum)
            self.assertEqual(10, timeout)
            return responses[url]

        session = sync_hub_source(source, http_get=get, runtime_version="0.3.0")
        self.assertEqual(self.skill_zip, session.read_artifact(self.skill["archive"]["path"]))
        self.assertEqual([source["https"]["index_url"], expected_artifact_url], calls)
        self.assertTrue(session.network_called)

    def test_injected_https_transport_cannot_bypass_byte_limits(self) -> None:
        source = git_source()
        source.update(
            {
                "transport": "static_https",
                "git": None,
                "https": {
                    "index_url": "https://skills.example.invalid/v1/index.json",
                    "artifact_base_url": "https://skills.example.invalid/v1/artifacts/",
                    "source_revision": "review-1",
                },
            }
        )
        source["limits"]["max_index_bytes"] = 1024
        with self.assertRaisesRegex(SkillHubContractError, "HUB_SOURCE_OUTPUT_LIMIT"):
            sync_hub_source(
                source,
                http_get=lambda _url, maximum, _timeout: b"x" * (maximum + 1),
            )

        source["limits"]["max_index_bytes"] = 1048576
        source["limits"]["max_artifact_bytes"] = 1024
        index_bytes = json.dumps(self.index_value).encode("utf-8")

        def get(url: str, maximum: int, _timeout: int) -> bytes:
            if url == source["https"]["index_url"]:
                return index_bytes
            return b"x" * (maximum + 1)

        session = sync_hub_source(source, http_get=get, runtime_version="0.3.0")
        with self.assertRaisesRegex(SkillHubContractError, "HUB_SOURCE_OUTPUT_LIMIT"):
            session.read_artifact(self.skill["archive"]["path"])

    def test_default_https_transport_disables_environment_and_redirects(self) -> None:
        response = Mock(
            status_code=200,
            is_redirect=False,
            headers={"Content-Length": "3"},
        )
        response.iter_content.return_value = [b"abc"]
        session = Mock(trust_env=True)
        session.get.return_value = response
        with patch("requests.Session", return_value=session):
            content = _https_get("https://skills.example.invalid/index.json", 16, 7)

        self.assertEqual(b"abc", content)
        self.assertFalse(session.trust_env)
        options = session.get.call_args.kwargs
        self.assertFalse(options["allow_redirects"])
        self.assertTrue(options["stream"])
        self.assertEqual(7, options["timeout"])
        self.assertNotIn("Authorization", options["headers"])
        response.close.assert_called_once_with()
        session.close.assert_called_once_with()

        redirect = Mock(status_code=302, is_redirect=True, headers={})
        redirected_session = Mock(trust_env=True)
        redirected_session.get.return_value = redirect
        with (
            patch("requests.Session", return_value=redirected_session),
            self.assertRaisesRegex(SkillHubContractError, "HUB_SOURCE_UNAVAILABLE"),
        ):
            _https_get("https://skills.example.invalid/index.json", 16, 7)
        self.assertFalse(redirected_session.trust_env)
        redirect.close.assert_called_once_with()
        redirected_session.close.assert_called_once_with()

    def test_skill_archive_and_trusted_wheel_validate_without_loading_code(self) -> None:
        skill = validate_skill_archive(self.skill_zip, self.skill)
        wheel = validate_trusted_wheel(self.wheel, self.trusted)

        self.assertEqual(self.skill["skill_uri"], skill["skill_uri"])
        self.assertEqual(self.trusted["descriptor"]["distribution"], wheel["distribution"])
        self.assertEqual(
            {"gravity.models", "gravity.operators"}, set(wheel["allowed_groups"])
        )

        bad_wheel = trusted_wheel(groups=("console_scripts",))
        bad_entry = bound_entry(trusted_entry(bad_wheel), bad_wheel)
        with self.assertRaisesRegex(SkillHubContractError, "TRUSTED_PACK_GROUP_INVALID"):
            validate_trusted_wheel(bad_wheel, bad_entry)

    def test_archive_attack_corpus_fails_closed(self) -> None:
        manifest = self.skill["manifest"]
        artifact = {
            "contract": manifest,
            "digest": self.skill["package"]["manifest_digest"],
            "skill_uri": self.skill["skill_uri"],
        }
        base = render_package_files(artifact)
        attacks = []
        traversal = {**base, "../escape.md": b"escape"}
        attacks.append(zip_bytes(traversal))
        collision = {**base, "guide.md": b"collision"}
        attacks.append(zip_bytes(collision))
        executable_modes = {"GUIDE.md": stat.S_IFREG | 0o755}
        attacks.append(zip_bytes(base, modes=executable_modes))
        link_modes = {"GUIDE.md": stat.S_IFLNK | 0o777}
        attacks.append(zip_bytes(base, modes=link_modes))
        special_modes = {"GUIDE.md": stat.S_IFIFO | 0o644}
        attacks.append(zip_bytes(base, modes=special_modes))
        bomb = {**base, "references/BOMB.md": b"0" * 262144}
        attacks.append(zip_bytes(bomb))
        tampered = dict(base)
        tampered["GUIDE.md"] += b"tampered"
        attacks.append(zip_bytes(tampered))

        for content in attacks:
            entry = bound_entry(self.skill, content)
            with self.subTest(size=len(content)), self.assertRaises(SkillHubContractError):
                validate_skill_archive(content, entry)

    def test_concurrent_fetch_is_single_flight_and_materializes_offline(self) -> None:
        compiled = compile_hub_index(self.index_value, runtime_version="0.3.0")
        entry = compiled["skills"][self.skill["skill_uri"]]
        calls = 0
        guard = threading.Lock()
        callers_ready = threading.Barrier(6, timeout=20)
        source_entered = threading.Event()
        release_source = threading.Event()

        def read(relative: str, maximum: int) -> bytes:
            nonlocal calls
            self.assertEqual(entry["archive"]["path"], relative)
            self.assertGreaterEqual(maximum, len(self.skill_zip))
            with guard:
                calls += 1
            source_entered.set()
            self.assertTrue(
                release_source.wait(20),
                "single-flight source release timed out after 20s",
            )
            return self.skill_zip

        def fetch(cas: SkillHubCAS, session: HubSourceSession) -> dict[str, Any]:
            try:
                callers_ready.wait()
            except threading.BrokenBarrierError as exc:
                raise AssertionError(
                    "single-flight caller rendezvous timed out or broke after 20s"
                ) from exc
            return cas.fetch_skill(session, entry)

        session = HubSourceSession(
            git_source(),
            "3" * 40,
            compiled,
            False,
            read,
        )
        with tempfile.TemporaryDirectory() as directory:
            cas = SkillHubCAS(Path(directory) / "cas")
            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = [pool.submit(fetch, cas, session) for _index in range(6)]
                try:
                    self.assertTrue(
                        source_entered.wait(20),
                        "single-flight source was not entered within 20s",
                    )
                finally:
                    release_source.set()
                results = [future.result(timeout=20) for future in futures]
            destination = Path(directory) / "installed" / "team-analysis"
            installed = cas.materialize_skill(
                entry["package"]["package_digest"], destination
            )
            verified = validate_skill_directory(
                destination,
                expected_digest=entry["package"]["package_digest"],
            )

        self.assertEqual(1, calls)
        self.assertEqual(1, sum(not item["cached"] for item in results))
        self.assertEqual("installed", installed["status"])
        self.assertEqual(entry["skill_uri"], verified["artifact"]["skill_uri"])

    def test_cas_tampering_is_detected_and_never_overwritten(self) -> None:
        compiled = compile_hub_index(self.index_value)
        entry = compiled["skills"][self.skill["skill_uri"]]
        session = HubSourceSession(
            git_source(),
            "3" * 40,
            compiled,
            False,
            lambda _path, _maximum: self.skill_zip,
        )
        with tempfile.TemporaryDirectory() as directory:
            cas = SkillHubCAS(Path(directory) / "cas")
            first = cas.fetch_skill(session, entry)
            guide = Path(first["cas_path"]) / "GUIDE.md"
            guide.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(SkillHubContractError, "HUB_CAS_TAMPERED"):
                cas.fetch_skill(session, entry)
            self.assertEqual("tampered", guide.read_text(encoding="utf-8"))

    def test_fetch_rejects_a_linked_cas_channel(self) -> None:
        compiled = compile_hub_index(self.index_value)
        entry = compiled["skills"][self.skill["skill_uri"]]
        session = HubSourceSession(
            git_source(),
            "3" * 40,
            compiled,
            False,
            lambda _path, _maximum: self.skill_zip,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cas = SkillHubCAS(root / "cas")
            outside = root / "outside"
            outside.mkdir()
            channel = cas.root / "skills"
            try:
                channel.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaisesRegex(SkillHubContractError, "HUB_CAS_INVALID"):
                cas.fetch_skill(session, entry)
            self.assertEqual([], list(outside.iterdir()))

    def test_materialization_rejects_a_linked_parent(self) -> None:
        compiled = compile_hub_index(self.index_value)
        entry = compiled["skills"][self.skill["skill_uri"]]
        session = HubSourceSession(
            git_source(),
            "3" * 40,
            compiled,
            False,
            lambda _path, _maximum: self.skill_zip,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cas = SkillHubCAS(root / "cas")
            cas.fetch_skill(session, entry)
            outside = root / "outside"
            outside.mkdir()
            linked = root / "linked"
            try:
                linked.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaisesRegex(
                SkillHubContractError, "HUB_INSTALL_PATH_INVALID"
            ):
                cas.materialize_skill(
                    entry["package"]["package_digest"], linked / "skill"
                )
            self.assertFalse((outside / "skill").exists())

    def test_state_reads_and_writes_reject_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "state.json"
            source.write_text('{"value":1}\n', encoding="utf-8")
            linked = root / "state-hardlink.json"
            os.link(source, linked)
            for path in (source, linked):
                with self.subTest(path=path), self.assertRaisesRegex(
                    SkillHubContractError, "HUB_STATE_INVALID"
                ):
                    read_json(path)
            with self.assertRaisesRegex(
                SkillHubContractError, "HUB_STATE_PATH_INVALID"
            ):
                atomic_write_json(source, {"value": 2})

    def test_state_reads_and_writes_reject_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "state.json"
            source.write_text('{"value":1}\n', encoding="utf-8")
            linked = root / "state-link.json"
            parent = root / "state-parent-link"
            real_parent = root / "real-parent"
            real_parent.mkdir()
            try:
                linked.symlink_to(source)
                parent.symlink_to(real_parent, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            with self.assertRaisesRegex(SkillHubContractError, "HUB_STATE_INVALID"):
                read_json(linked)
            with self.assertRaisesRegex(
                SkillHubContractError, "HUB_STATE_PATH_INVALID"
            ):
                atomic_write_json(linked, {"value": 2})
            with self.assertRaisesRegex(
                SkillHubContractError, "HUB_STATE_PATH_INVALID"
            ):
                atomic_write_json(parent / "state.json", {"value": 2})
            self.assertFalse((real_parent / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
