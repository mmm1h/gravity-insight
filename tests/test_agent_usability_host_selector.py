from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "scripts" / "agent_usability_host_selector.py"
if str(PLUGIN.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN.parent))


def _request() -> dict:
    return {
        "schema_version": "gravity.agent-external-selector-request.v1",
        "catalog": {
            "capabilities": [{
                "selector": "composite:business_pulse",
                "source": "composite",
                "name": "business pulse",
            }],
            "categories": [],
        },
        "questions": [{"id": "q-0001", "query": "业务脉搏 — café"}],
    }


def _response() -> dict:
    return {
        "status": "completed",
        "error": None,
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "function_call",
                "call_id": "call-example",
                "name": "submit_catalog_selections",
                "status": "completed",
                "arguments": json.dumps({"results": [{
                    "id": "q-0001", "selectors": ["composite:business_pulse"],
                    "reason": "",
                }]}),
            },
        ],
    }


class HostSelectorPluginTests(unittest.TestCase):
    def test_recanonicalize_matches_parent_utf8_hash_and_covers_gbk_crash(self) -> None:
        from agent_usability_host_selector import _request_sha256

        request = _request()
        text = json.dumps(
            request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            _request_sha256(request),
        )
        garbled = text.encode("utf-8").decode("gbk", errors="surrogateescape")
        with self.assertRaises(UnicodeEncodeError):
            json.dumps(
                json.loads(garbled),
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")

    def test_missing_credentials_fail_after_canonicalize(self) -> None:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("OPENAI_API_KEY", None)
        payload = json.dumps(
            _request(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        completed = subprocess.run(
            [sys.executable, "--", str(PLUGIN)],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**env, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
        self.assertNotEqual(0, completed.returncode)
        self.assertEqual("", completed.stdout)
        self.assertIn("OPENAI_API_KEY", completed.stderr)

    def test_responses_wire_preserves_blinded_batch_and_external_envelope(self) -> None:
        import agent_usability_host_selector as selector

        request = _request()
        request["questions"].append({"id": "q-0002", "query": "业务脉搏"})
        response = _response()
        first = json.loads(response["output"][-1]["arguments"])["results"][0]
        second = dict(first, id="q-0002")
        response["output"][-1]["arguments"] = json.dumps({"results": [second, first]})
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "<test-only-key>"}, clear=True),
            patch.object(sys, "stdin", io.StringIO(json.dumps(request))),
            patch.object(sys, "stdout", output),
            patch.object(selector.urllib.request, "urlopen") as send,
        ):
            send.return_value.__enter__.return_value.read.return_value = json.dumps(
                response
            ).encode("utf-8")
            self.assertEqual(0, selector.main())
        send.assert_called_once()
        wire = send.call_args.args[0]
        self.assertEqual("https://api.openai.com/v1/responses", wire.full_url)
        self.assertEqual("POST", wire.method)
        self.assertEqual("Bearer <test-only-key>", wire.get_header("Authorization"))
        self.assertEqual(100, send.call_args.kwargs["timeout"])
        body = json.loads(wire.data)
        self.assertEqual("gpt-6-astra", body["model"])
        self.assertEqual({"effort": "low"}, body["reasoning"])
        self.assertEqual(24_000, body["max_output_tokens"])
        self.assertFalse(body["store"])
        self.assertFalse(body["parallel_tool_calls"])
        self.assertTrue(body["tools"][0]["strict"])
        self.assertEqual(
            {"type": "function", "name": "submit_catalog_selections"}, body["tool_choice"]
        )
        self.assertEqual(["results"], body["tools"][0]["parameters"]["required"])
        self.assertFalse({
            "temperature", "top_p", "top_logprobs", "logprobs", "messages",
            "max_tokens", "system", "prompt_cache_retention", "previous_response_id",
        } & body.keys())
        user_input = body["input"][0]["content"].split("Request JSON:\n", 1)[1]
        self.assertEqual(request, json.loads(user_input))
        result = json.loads(output.getvalue())
        self.assertEqual("gravity.agent-external-selector-response.v1", result["schema_version"])
        self.assertEqual([first, second], result["results"])
        self.assertEqual(
            "openai/gpt-6-astra/low/host-selector.v2", result["metadata"]["selector"]
        )
        self.assertEqual(selector._request_sha256(request), result["metadata"]["request_sha256"])

    def test_text_and_reasoning_do_not_hide_a_valid_function_call(self) -> None:
        from agent_usability_host_selector import _parse_tool_results

        response = _response()
        response["output"].insert(0, {
            "type": "message", "content": [{"type": "output_text", "text": "Done."}],
        })
        # The API's function-call status is optional; enclosing completion suffices.
        response["output"][-1].pop("status")
        self.assertEqual("q-0001", _parse_tool_results(response)[0]["id"])

    def test_incomplete_response_cannot_publish_apparently_complete_rows(self) -> None:
        from agent_usability_host_selector import _parse_tool_results

        response = _response()
        response.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        with self.assertRaisesRegex(SystemExit, "did not complete"):
            _parse_tool_results(response)

    def test_refusal_cannot_be_accepted_alongside_a_function_call(self) -> None:
        from agent_usability_host_selector import _parse_tool_results

        response = _response()
        response["output"].append({
            "type": "message", "content": [{"type": "refusal", "refusal": "Cannot comply."}],
        })
        with self.assertRaisesRegex(SystemExit, "refusal"):
            _parse_tool_results(response)

    def test_multiple_submissions_are_rejected_instead_of_taking_first(self) -> None:
        from agent_usability_host_selector import _parse_tool_results

        response = _response()
        response["output"].append(dict(response["output"][-1], call_id="call-second"))
        with self.assertRaisesRegex(SystemExit, "exactly once"):
            _parse_tool_results(response)

    def test_truncated_function_arguments_fail_without_retry(self) -> None:
        import agent_usability_host_selector as selector

        response = _response()
        response["output"][-1]["arguments"] = '{"results": ['
        with patch.object(selector, "_post", return_value=response) as send:
            with self.assertRaisesRegex(SystemExit, "not valid JSON"):
                selector._complete(_request())
        send.assert_called_once()

    def test_authentication_error_is_not_retried_or_echoed(self) -> None:
        import agent_usability_host_selector as selector

        error = urllib.error.HTTPError(
            selector.API_URL, 401, "Unauthorized", {}, io.BytesIO(b"private-provider-detail"),
        )
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "<test-only-key>"}, clear=True),
            patch.object(selector.urllib.request, "urlopen", side_effect=error) as send,
        ):
            with self.assertRaises(SystemExit) as caught:
                selector._complete(_request())
        send.assert_called_once()
        self.assertEqual("host selector HTTP 401", str(caught.exception))

    def test_rate_limits_exhaust_only_the_bounded_retry_budget(self) -> None:
        import agent_usability_host_selector as selector

        errors = [urllib.error.HTTPError(
            selector.API_URL, 429, "Too Many Requests", {}, io.BytesIO(),
        ) for _ in range(3)]
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "<test-only-key>"}, clear=True),
            patch.object(selector.urllib.request, "urlopen", side_effect=errors) as send,
            patch.object(selector.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(SystemExit, "failed after 3 attempts: HTTP 429"):
                selector._complete(_request())
        self.assertEqual(3, send.call_count)
        self.assertEqual([2.0, 5.0], [call.args[0] for call in sleep.call_args_list])
        self.assertEqual(1, len({call.args[0].data for call in send.call_args_list}))

    def test_live_path_rejects_unknown_selector_instead_of_abstaining(self) -> None:
        from agent_usability_host_selector import _normalize_results

        with self.assertRaisesRegex(SystemExit, "unknown selectors"):
            _normalize_results(
                [{"id": "q-0001", "selectors": ["not-in-catalog"], "reason": ""}],
                ["q-0001"],
                frozenset({"composite:business_pulse"}),
            )
