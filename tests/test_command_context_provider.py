from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from gravity_insight.external_context_provider import (
    CommandProviderTransport,
    subprocess_context_provider,
)
from gravity_insight.external_context_contract import compile_rpc_result
from tests.test_external_context_contracts import provider_descriptor


COMMAND_SCRIPT = r'''
import json
import os
import sys
import time

mode = sys.argv[1]
if mode == "success":
    print(json.dumps({
        "data": {
            "argv": sys.argv[2:],
            "value": "fixture",
            "config_home_present": any(
                key in os.environ
                for key in ("HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME")
            ),
            "gravity_present": any(key.startswith("GRAVITY_") for key in os.environ),
        },
        "ok": True,
    }, sort_keys=True))
elif mode == "resource-missing":
    print(json.dumps({"error": {"code": 404, "message": "private-resource-name"}}), file=sys.stderr)
    raise SystemExit(4)
elif mode == "unavailable":
    print("private-provider-secret", file=sys.stderr)
    raise SystemExit(7)
elif mode == "retry-malformed":
    marker = os.path.join(os.getcwd(), "retry-marker")
    if not os.path.exists(marker):
        open(marker, "w", encoding="utf-8").close()
        raise SystemExit(7)
    print("not-json")
elif mode == "stale":
    print(json.dumps({"data": {"value": "old"}, "updated_at": "2000-01-01T00:00:00Z"}))
elif mode == "malformed":
    print("not-json")
elif mode == "wait":
    time.sleep(2)
else:
    raise SystemExit(9)
'''


class CommandContextProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.script = self.root / "command_fixture.py"
        self.script.write_text(COMMAND_SCRIPT, encoding="utf-8", newline="\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def descriptor(
        self,
        mode: str,
        *,
        executable: str | None = None,
        freshness_model: str = "content_hash",
    ) -> dict:
        binding = {
            "executable": executable or str(Path(sys.executable).resolve()),
            "arguments": [str(self.script), mode],
            "working_directory": str(self.root),
            "protocol": "command",
            "command": {
                "routes": [
                    {
                        "route_id": "command-fixture",
                        "resource_prefix": "provider://team/command/",
                        "path_segment_count": 2,
                        "arguments": [
                            {"literal": "--resource"},
                            {"uri_path_segment": 1},
                            {"literal": "--scope"},
                            {"uri_path_segments": [0, 1], "separator": "/"},
                        ],
                        "resource": {
                            "item_id": "command-fixture",
                            "fact_id": "fact.command-fixture",
                            "title": "Command fixture",
                            "resource_type": "document",
                            "entity_refs": ["entity://gravity/app@1"],
                            "valid_time": {
                                "start": None,
                                "end": None,
                                "timezone": "Asia/Shanghai",
                            },
                            "effective_range": {"start": None, "end": None},
                            "sensitivity": "internal",
                            "citation_path": "command/fixture",
                            "content_pointer": "/data",
                        },
                        "failure_rules": [
                            {
                                "kind": "resource_unavailable",
                                "exit_codes": [4],
                                "json_pointer": "/error/code",
                                "equals": [404],
                            }
                        ],
                        "freshness": (
                            {
                                "timestamp_pointer": "/updated_at",
                                "max_age_seconds": 60,
                            }
                            if freshness_model == "ttl"
                            else None
                        ),
                    }
                ],
                "guidance": {
                    "source_unavailable": {
                        "missing": "fixture command or its login/network",
                        "message": "The fixture command source is unavailable.",
                        "user_actions": ["Install or repair the fixture command."],
                    },
                    "resource_unavailable": {
                        "missing": "fixture resource",
                        "message": "The requested fixture resource cannot be read.",
                        "user_actions": ["Check the resource identifier and access."],
                    },
                    "content_stale": {
                        "missing": "current fixture content",
                        "message": "The fixture content is not current enough.",
                        "user_actions": ["Refresh the source and retry."],
                    },
                },
            },
        }
        descriptor = provider_descriptor(
            transport="subprocess",
            source_trust="observed",
            alignment="partial",
            authority_ceiling="declared_intent",
            operations=("read",),
            subprocess_binding=binding,
        )
        descriptor["resource_types"] = ["document"]
        descriptor["allowed_resource_prefixes"] = ["provider://team/command/"]
        descriptor["capabilities"]["freshness_model"] = freshness_model
        descriptor["rpc"]["max_attempts"] = 1
        return descriptor

    def test_command_wraps_json_argv_without_gravity_credentials(self) -> None:
        names = ("GRAVITY_AUTH_TOKEN", "GRAVITY_PASSWORD")
        previous = {name: os.environ.get(name) for name in names}
        os.environ.update({name: "must-not-cross" for name in names})
        try:
            provider = subprocess_context_provider(
                self.descriptor("success"), work_root=self.root
            )
            result = provider.read("provider://team/command/group/entry")
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        item = result["context_items"][0]
        content = json.loads(item["content"])
        self.assertEqual(
            ["--resource", "entry", "--scope", "group/entry"], content["argv"]
        )
        self.assertTrue(content["config_home_present"])
        self.assertFalse(content["gravity_present"])
        self.assertEqual("declared_intent", item["authority"])
        self.assertNotIn("must-not-cross", json.dumps(result))

    def test_missing_command_degrades_with_agent_guidance(self) -> None:
        descriptor = self.descriptor(
            "success", executable=str(self.root / "not-installed.exe")
        )
        result = subprocess_context_provider(
            descriptor, work_root=self.root
        ).read("provider://team/command/group/entry")

        self.assertEqual(result, compile_rpc_result(result))
        self.assertEqual("context_gap", result["status"])
        self.assertEqual("source_unavailable", result["degradation"]["kind"])
        self.assertEqual("command_not_found", result["degradation"]["cause"])
        self.assertEqual(
            "supplemental_context_only", result["degradation"]["continuation"]
        )
        self.assertEqual([], result["context_items"])

    def test_resource_and_source_failures_degrade_without_stderr(self) -> None:
        cases = (
            ("resource-missing", "resource_unavailable", "resource_unavailable"),
            ("unavailable", "source_unavailable", "command_failed"),
        )
        for mode, kind, cause in cases:
            with self.subTest(mode=mode):
                result = subprocess_context_provider(
                    self.descriptor(mode), work_root=self.root
                ).read("provider://team/command/group/entry")
                self.assertEqual(kind, result["degradation"]["kind"])
                self.assertEqual(cause, result["degradation"]["cause"])
                self.assertNotIn("private-resource-name", json.dumps(result))
                self.assertNotIn("private-provider-secret", json.dumps(result))

    def test_stale_degrades_but_malformed_and_timeout_fail_closed(self) -> None:
        stale = subprocess_context_provider(
            self.descriptor("stale", freshness_model="ttl"), work_root=self.root
        ).read("provider://team/command/group/entry")
        malformed = subprocess_context_provider(
            self.descriptor("malformed"), work_root=self.root
        ).read("provider://team/command/group/entry")
        timeout_descriptor = self.descriptor("wait")
        timeout_descriptor["rpc"]["timeout_ms"] = 50
        timeout = subprocess_context_provider(
            timeout_descriptor, work_root=self.root
        ).read("provider://team/command/group/entry")

        self.assertEqual("freshness_expired", stale["degradation"]["cause"])
        self.assertEqual(["PROVIDER_RPC_MALFORMED"], malformed["reason_codes"])
        self.assertNotIn("degradation", malformed)
        self.assertEqual(["PROVIDER_RPC_TIMEOUT"], timeout["reason_codes"])
        self.assertNotIn("degradation", timeout)

    def test_retry_cannot_attach_old_degradation_to_malformed_result(self) -> None:
        descriptor = self.descriptor("retry-malformed")
        descriptor["rpc"]["max_attempts"] = 2
        result = subprocess_context_provider(
            descriptor, work_root=self.root
        ).read("provider://team/command/group/entry")

        self.assertEqual(["PROVIDER_RPC_MALFORMED"], result["reason_codes"])
        self.assertNotIn("degradation", result)

    def test_command_governance_violations_fail_closed(self) -> None:
        provider = subprocess_context_provider(
            self.descriptor("success"), work_root=self.root
        )
        denied = provider.read("provider://team/docs/outside")
        malformed_route = provider.read("provider://team/command/group/entry/extra")

        self.assertEqual(["PROVIDER_RESOURCE_DENIED"], denied["reason_codes"])
        self.assertFalse(denied["provider_rpc_called"])
        self.assertNotIn("degradation", denied)
        self.assertEqual(
            ["PROVIDER_RPC_RESPONSE_INVALID"], malformed_route["reason_codes"]
        )
        self.assertNotIn("degradation", malformed_route)

        elevated = self.descriptor("success")
        elevated["source_trust"] = "reviewed"
        elevated["capabilities"]["entity_time_alignment"] = "full"
        elevated["authority_ceiling"] = "canonical"
        with self.assertRaisesRegex(ValueError, "exceeds declared intent"):
            CommandProviderTransport(elevated, work_root=self.root)


if __name__ == "__main__":
    unittest.main()
