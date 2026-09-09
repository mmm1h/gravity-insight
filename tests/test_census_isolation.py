"""Offline regressions for the entry-change/ReadTimeout incident and retry owner."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
import yaml

from gravity_insight.census.cli import main
from gravity_insight.census.diffing import diff_routes, diff_snapshots, exception_failure
from gravity_insight.census.fetcher import StaticFetcher, _FetchError, check_upstream
from gravity_insight.contracts.envelope_obligations import EnvelopeObligations


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/upstream-census.yml'


class CensusIncidentTests(unittest.TestCase):
    def test_entry_changed_then_read_timeout_keeps_final_failure_evidence(self):
        response = SimpleNamespace(content=b'<script type="module" src="/new.js"></script>',
            encoding='utf-8', url='https://example.test/', headers={})
        with patch.object(StaticFetcher, '_get', return_value=response):
            entry = check_upstream('https://example.test/', {'entry_urls': [], 'html': {}})
        self.assertEqual('entry_change_observed', entry['observation_state'])
        self.assertFalse(entry['api_breaking_confirmed'])
        self.assertEqual('unknown', EnvelopeObligations.from_dict(entry['obligations']).data_completeness.state.value)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch('gravity_insight.census.fetcher.perform_http_request', side_effect=requests.ReadTimeout('private URL')) as request,
                patch('gravity_insight.cli_stdio.configure_utf8_stdio'),
                patch('gravity_insight.census.cli.sys.stderr', SimpleNamespace(buffer=io.BytesIO())),
            ):
                code = main(['fetch', '--raw-dir', str(root / 'raw'), '--output', str(root / 'snapshot.json'),
                    '--max-attempts', '1', '--require-complete', '--failure-output', str(root / 'failure.json'),
                    '--step-output', str(root / 'step.json')])
            failure = json.loads((root / 'failure.json').read_text())
            step = json.loads((root / 'step.json').read_text())
            snapshot = json.loads((root / 'snapshot.json').read_text())
        self.assertNotEqual(0, code)
        self.assertEqual(1, request.call_count)
        self.assertEqual('transport_failure', step['observation_state'])
        self.assertEqual({'used': 1, 'limit': 800, 'remaining': 799}, failure['request_budget'])
        self.assertEqual('ReadTimeout', failure['failures'][0]['exception_type'])
        self.assertIn('single crawl owner', failure['next_action'])
        self.assertFalse(step['drift_conclusion_available'])
        self.assertEqual(1, snapshot['summary']['request_attempts'])
        self.assertFalse(snapshot['summary']['complete'])
        self.assertNotIn('private URL', json.dumps(failure))
        self.assertEqual('failed', EnvelopeObligations.from_dict(failure['obligations']).execution_status.state.value)

    def test_capacity_is_distinct_from_transport_and_incomplete(self):
        capacity = exception_failure(_FetchError('rate limited', url='https://example.test/', status_class='rate_limited', status_code=429))
        self.assertEqual('capacity_limited', capacity['observation_state'])
        self.assertIn('cooldown', capacity['next_action'])
        self.assertFalse(capacity['api_breaking_confirmed'])

    def test_request_and_time_exhaustion_prevent_network_attempts(self):
        fetcher = StaticFetcher(max_requests=1)
        fetcher.attempts = 1
        expired = StaticFetcher()
        expired._deadline = 0
        for instance, expected in ((fetcher, 'request_budget_exhausted'), (expired, 'time_budget_exhausted')):
            with self.subTest(expected=expected), patch('gravity_insight.census.fetcher.perform_http_request') as request:
                with self.assertRaises(_FetchError) as error:
                    instance._get('https://example.test/')
                payload = exception_failure(error.exception)
                self.assertEqual(expected, payload['failure_class'])
                self.assertFalse(payload['retryable'])
                request.assert_not_called()

    def test_redirect_cannot_generate_an_unaccounted_request(self):
        fetcher = StaticFetcher(max_requests=1)
        with patch('gravity_insight.census.fetcher.perform_http_request', return_value=SimpleNamespace(status_code=302)) as request:
            with self.assertRaises(_FetchError) as error:
                fetcher._get('https://example.test/')
        self.assertFalse(request.call_args.kwargs['allow_redirects'])
        self.assertEqual('content_incomplete', error.exception.status_class)

    def test_failed_worker_counters_are_finalized_before_retry_accounting(self):
        def concurrent_failure(fetcher, **kwargs):
            error = _FetchError('fixture', url='https://example.test/', status_class='transport_error', request_attempts=1, request_limit=800)
            fetcher.attempts = 4
            raise error
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'step.json'
            with (
                patch.object(StaticFetcher, 'fetch', concurrent_failure),
                patch('gravity_insight.cli_stdio.configure_utf8_stdio'),
                patch('gravity_insight.census.cli.sys.stderr', SimpleNamespace(buffer=io.BytesIO())),
            ):
                self.assertNotEqual(0, main(['fetch', '--step-output', str(target)]))
            step = json.loads(target.read_text())
        self.assertEqual(4, step['request_budget']['used'])

    def test_incomplete_graph_and_asset_diff_never_prove_api_breaking(self):
        old = {'bundle_id': 'old', 'summary': {'complete': True}, 'files': []}
        incomplete = {**old, 'summary': {'complete': False}}
        withheld = diff_snapshots(old, incomplete)
        self.assertEqual('crawl_incomplete', withheld['observation_state'])
        self.assertIsNone(withheld['summary']['added_files'])
        changed = diff_snapshots(old, {**old, 'files': [{'url': '/new.js', 'sha256': 'new'}]})
        self.assertEqual('drift_confirmed', changed['observation_state'])
        self.assertFalse(changed['api_breaking_confirmed'])
        self.assertIn('parsed routes', changed['next_action'])
        routes = {'source': {'bundle_complete': True}, 'routes': []}
        self.assertEqual('unchanged', diff_routes(routes, routes)['observation_state'])
        self.assertFalse(diff_routes(routes, {**routes, 'source': {}})['drift_conclusion_available'])


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required to execute the workflow owner')
class CensusWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
        cls.steps = cls.workflow['jobs']['inspect-public-static-graph']['steps']
        cls.script = next(step['run'] for step in cls.steps if step.get('id') == 'fetch')

    def _execute(self, scenario):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = ROOT / 'tests/fixtures/census_workflow_stub.ps1'
            script = root / 'run.ps1'
            script.write_text(source.read_text() + '\n' + self.script, encoding='utf-8')
            scenario_path = root / 'scenario.json'
            scenario_path.write_text(json.dumps(scenario), encoding='utf-8')
            process = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(script)],
                env={**os.environ, 'RUNNER_TEMP': str(root), 'CENSUS_SCENARIO': str(scenario_path),
                    'GITHUB_OUTPUT': str(root / 'output')}, capture_output=True, text=True, timeout=30, encoding="utf-8")
            calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text(encoding='utf-8-sig').splitlines()]
            evidence = root / 'gravity-drift'
            step = json.loads((evidence / 'census-step-output.json').read_text(encoding='utf-8-sig'))
            artifacts = [path.name for path in evidence.iterdir()]
        return process, calls, step, artifacts

    def test_transport_retry_has_one_owner_and_shared_budget(self):
        process, calls, step, artifacts = self._execute([
            {'failure_class': 'transport_failure', 'used': 1}, {'complete': True, 'used': 3}])
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual([800, 799], [call['limit'] for call in calls])
        self.assertEqual(4, step['crawl_budget']['used'])
        self.assertEqual('workflow', step['crawl_budget']['retry_owner'])
        self.assertIn('attempt-1-fetch-failure.json', artifacts)
        self.assertIn('attempt-2-current-snapshot.json', artifacts)

    def test_retry_exhaustion_and_terminal_causes_fail_closed(self):
        cases = [
            ([{'failure_class': 'transport_failure', 'used': 1}] * 3, 3),
            ([{'failure_class': 'upstream_capacity', 'used': 1}] * 3, 3),
            ([{'failure_class': 'transport_failure', 'used': 800}], 1),
            ([{'failure_class': 'transport_failure', 'used': 1, 'elapsed_seconds': 1201}], 1),
            ([{'failure_class': 'content_incomplete', 'used': 1}], 1),
            ([{'crash': True}], 1),
        ]
        for scenario, expected_calls in cases:
            with self.subTest(scenario=scenario):
                process, calls, step, artifacts = self._execute(scenario)
                self.assertNotEqual(0, process.returncode)
                self.assertEqual(expected_calls, len(calls))
                self.assertFalse(step['complete'])
                self.assertIn('attempt-1-census-step-output.json', artifacts)

    def test_absolute_deadline_kills_child_and_retains_finally_evidence(self):
        process, calls, step, artifacts = self._execute([
            {'failure_class': 'transport_failure', 'used': 1, 'timeout': True}])
        self.assertNotEqual(0, process.returncode)
        self.assertEqual(1, len(calls))
        self.assertEqual('time_budget_exhausted', step['failure_class'])
        self.assertEqual('unverified_upper_bound_after_forced_stop', step['request_accounting'])
        self.assertIn('child-killed.txt', artifacts)
        self.assertIn('attempt-1-census-step-output.json', artifacts)

    def test_yaml_and_all_powershell_steps_parse_and_monitoring_failure_is_fatal(self):
        self.assertEqual(25, self.workflow['jobs']['inspect-public-static-graph']['timeout-minutes'])
        terminal = next(step for step in self.steps if step['name'] == 'Reject unavailable monitoring after bounded attempts')
        self.assertNotIn('upstream_capacity', terminal['if'])
        for step in self.steps:
            if step.get('shell') != 'pwsh':
                continue
            source = re.sub(r'\$\{\{.*?\}\}', 'fixture', step['run'])
            encoded = source.replace("'", "''")
            process = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command',
                f"[void][scriptblock]::Create('{encoded}')"], capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(0, process.returncode, step['name'] + process.stderr)
