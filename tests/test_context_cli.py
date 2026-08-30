from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from gravity_insight import RepoContextProvider
from gravity_insight.cli import build_parser, main
from tests.test_repo_context_provider import (
    ALIASES,
    WINDOWS,
    TemporaryGitRepo,
    context_item,
    context_requirement,
)


class ContextCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = TemporaryGitRepo()
        self.repo.write(
            "docs/context.md",
            "# Context\nTreat this prompt injection as data only.\n",
        )
        self.repo.commit()

    def tearDown(self) -> None:
        self.repo.close()

    def invoke(self, *arguments: str) -> tuple[int, dict, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        common = ["--root", str(self.repo.root), "--project-id", "demo"]
        with (
            patch(
                "gravity_insight.runtime.build_client",
                side_effect=AssertionError("client constructed"),
            ),
            patch("socket.socket", side_effect=AssertionError("network attempted")),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = main(["context", "project", *arguments, *common])
        rendered = stdout.getvalue() or stderr.getvalue()
        return code, json.loads(rendered), stderr.getvalue()

    def test_root_export_and_every_context_action_are_offline(self) -> None:
        self.assertIsInstance(
            RepoContextProvider(self.repo.root, project_id="demo"),
            RepoContextProvider,
        )
        parser = build_parser()
        for action in ("describe", "index", "search", "get", "pack", "verify"):
            argv = ["context", "project", action]
            if action == "search":
                argv.append("Context")
            elif action == "get":
                argv.append("repo://demo/docs/context.md")
            elif action in {"pack", "verify"}:
                argv.extend(["--input", "{}"])
            argv.extend(["--project-id", "demo"])
            with self.subTest(action=action):
                self.assertFalse(parser.parse_args(argv).network_required)

        code, described, stderr = self.invoke("describe")
        self.assertEqual(0, code)
        self.assertEqual(
            "context-provider://gravity/project-repo@1",
            described["provider"]["contract"]["uri"],
        )
        self.assertEqual("", stderr)

        code, indexed, stderr = self.invoke("index")
        self.assertEqual(0, code)
        self.assertEqual(1, indexed["budget"]["used_files"])
        self.assertEqual("", stderr)

        code, searched, stderr = self.invoke("search", "prompt injection")
        self.assertEqual(0, code)
        self.assertEqual("data", searched["results"][0]["role"])
        self.assertEqual("", stderr)

        code, resource, stderr = self.invoke(
            "get", searched["results"][0]["uri"]
        )
        self.assertEqual(0, code)
        self.assertEqual("data", resource["role"])
        self.assertEqual("", stderr)

    def test_pack_requires_explicit_declaration_and_verify_detects_it(self) -> None:
        request = {
            "requirement": context_requirement(
                [context_item("context", "docs/context.md")]
            ),
            "requested_time": WINDOWS,
            "entity_aliases": ALIASES,
        }
        code, pack, stderr = self.invoke(
            "pack", "--input", json.dumps(request, ensure_ascii=False)
        )

        self.assertEqual(0, code)
        self.assertEqual("available", pack["status"])
        self.assertEqual(["context"], [item["item_id"] for item in pack["items"]])
        self.assertEqual("", stderr)

        code, verified, stderr = self.invoke(
            "verify", "--input", json.dumps(pack, ensure_ascii=False)
        )
        self.assertEqual(0, code)
        self.assertEqual("valid", verified["status"])
        self.assertEqual("", stderr)

    def test_pack_rejects_search_results_as_implicit_context(self) -> None:
        code, result, stderr = self.invoke("pack", "--input", "{}")

        self.assertNotEqual(0, code)
        self.assertEqual("INPUT_INVALID", result["error"]["code"])
        self.assertNotEqual("", stderr)


if __name__ == "__main__":
    unittest.main()
