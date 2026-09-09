"""Synthetic acceptance for metadata-bound user-detail exports; no live rows."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET
import zipfile

from gravity_insight.client import GravityInsightClient
from gravity_insight.export_completion import result_completion_status, export_result_obligations
from gravity_insight.export_contracts import ExportContractRegistry
from gravity_insight.export_file import export_file_policies
from gravity_insight.export_models import ExportRuntimeError
from gravity_insight.export_models import ExportCreationRequest, ExportJobSnapshot, ExportState
from gravity_insight.export_state import ExportOrchestrator
from gravity_insight.export_privacy import ExportPrivacyFinalizer
from gravity_insight.export_results import _failure_diagnostics, _file_receipt
from gravity_insight.export_scope_total import classify_export_rows
from gravity_insight.field_metadata_override import selected_metadata_loader
from gravity_insight.paths import CONTRACT_ROOT
from gravity_insight.registry import PolicyEngine
from tests.test_gravity_insight_export_integration import FakeRuntime, _xlsx_metadata, read_registry
from tests.test_user_detail_export_characterization import EVIDENCE, OPERATION, _payload


CONTRACTS = ExportContractRegistry.from_file(CONTRACT_ROOT / 'exports/routes-v1.json')
CONTRACT = CONTRACTS.get(OPERATION)
CODES = tuple(sorted(CONTRACT.privacy['request_columns']))
LABELS = dict(zip(CONTRACT.privacy['request_columns'], CONTRACT.privacy['allowed_columns']))
VALUES = {
    'ClientID': '9007199254740993', 'CreateTime': '2026-01-01 00:00:00',
    'Version': 12, 'useraccount_id': '000000000000000002',
    'userdevice_id': 'synthetic-device', 'userfirst_login_time': '2026-01-01 00:00:01',
    'useruser_ab': 'synthetic-ab',
}


def _workbook(path, *, codes=CODES, records=None, overrides=None, styles=None, labels=LABELS, header_overrides=None):
    records = records if records is not None else [VALUES, {**VALUES, **{code: None for code in CODES if code.startswith('user')}}]
    worksheet = ET.Element('worksheet')
    data = ET.SubElement(worksheet, 'sheetData')
    strings = ET.Element('sst')
    count = 0
    for row_number, values in enumerate([{code: labels[code] for code in codes}, *records], 1):
        row = ET.SubElement(data, 'row', r=str(row_number))
        for index, code in enumerate(codes):
            value = values.get(code)
            if value is None:
                continue
            cell = ET.SubElement(row, 'c', r=f'{chr(65 + index)}{row_number}', t='s' if isinstance(value, str) else 'n')
            if isinstance(value, str):
                ET.SubElement(ET.SubElement(strings, 'si'), 't').text = value
                ET.SubElement(cell, 'v').text = str(count)
                count += 1
            else:
                ET.SubElement(cell, 'v').text = str(value)
            if row_number == 2 and overrides and code in overrides:
                overrides[code](cell)
            if row_number == 1 and header_overrides and code in header_overrides:
                header_overrides[code](cell)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('xl/sharedStrings.xml', ET.tostring(strings))
        archive.writestr('xl/worksheets/sheet1.xml', ET.tostring(worksheet))
        if styles is not None:
            archive.writestr('xl/styles.xml', styles)


def _metadata():
    return [dict(name=binding['name'], cname=LABELS[code], data_type=binding['data_type'], app_id=101, visible=True)
            for code, binding in CONTRACT.privacy['metadata_fields'].items()]


def _metadata_result(rows, *, has_more=False):
    return SimpleNamespace(to_dict=lambda: {
        'ok': True, 'status': 'success', 'data': {'list': rows}, 'page': {'has_more': has_more},
    })


class UserDetailProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = read_registry()

    def _client(self, metadata=None, total=2):
        client = object.__new__(GravityInsightClient)
        client._export_contracts = CONTRACTS
        client._export_policy = PolicyEngine(self.registry, effect_routes=CONTRACTS.effect_routes())
        client._export_runtime = FakeRuntime([{'code': 0, 'data': {'task_id': 17}}])
        client._operation_catalog = SimpleNamespace(guard=Mock())
        client._executor = SimpleNamespace(execute=Mock(return_value=_metadata_result(_metadata() if metadata is None else metadata)))
        client._load_field_metadata = Mock(side_effect=AssertionError('cached metadata must not validate export fields'))
        client.read = Mock(return_value={'ok': True, 'page': {'total_items': total}})
        return client

    def _start(self, client, payload=None, columns=None):
        payload = payload or _payload()
        return client.export_start(OPERATION, payload, requested_columns=columns or tuple(payload['field_map']), idempotency_key='synthetic-export-key-203')

    def test_contract_expands_only_observed_fields_and_declares_sorting(self):
        description = CONTRACT.description()['columns']
        self.assertEqual({row['code'] for row in EVIDENCE['columns']}, set(description['allowed_codes']))
        self.assertFalse(description['must_match_input_order_exactly'])
        self.assertEqual('request_code_lexicographic', description['column_order'])
        self.assertEqual(['ClientID', 'CreateTime'], description['required_codes'])

    def test_metadata_preflight_create_and_resume_share_the_projection_and_total(self):
        client = self._client()
        def preflight(selector, inputs):
            self.assertEqual([], client._export_runtime.calls)
            self.assertEqual('analysis.user_detail.list', selector)
            self.assertEqual({'app_id': '101', 'fields': list(CODES), 'page': 1, 'page_size': 1,
                              **{k: v for k, v in _payload().items() if k not in {'app_id', 'field_map', 'task_name'}}}, inputs)
            pinned = selected_metadata_loader(client._load_field_metadata)('analysis.user_property.list', {'app_id': '101'})
            self.assertEqual(_metadata(), pinned['data']['list'])
            return {'ok': True, 'page': {'total_items': 2}}
        client.read.side_effect = preflight
        start = self._start(client, columns=tuple(reversed(CODES)))
        self.assertEqual(list(CODES), list(client._export_runtime.calls[0][3]['field_map']))
        self.assertEqual(1, client._export_runtime.calls[0][4]['attempts'])
        self.assertEqual('17', start['completeness']['job_id'])
        self.assertEqual(list(CODES), start['completeness']['requested_columns'])
        client._executor.execute.assert_called_once_with('analysis.user_property.list', {'app_id': '101', 'page': 1, 'page_size': 2000})
        with tempfile.TemporaryDirectory() as root, patch('gravity_insight.export_client.ExportOrchestrator') as orchestrator, patch('gravity_insight.export_client._export_result_envelope'):
            client.export_download(OPERATION, '17', Path(root) / 'output.xlsx', completeness=start['completeness'])
            args = orchestrator.return_value.resume.call_args
            self.assertEqual(tuple(LABELS[code] for code in CODES), args.args[3].required_columns)
            self.assertEqual(2, args.kwargs['completeness']['known_total_items'])
        client.read.assert_called_once()

    def test_unknown_or_unverified_field_fails_before_metadata_list_or_create(self):
        client = self._client()
        payload = _payload()
        payload['field_map']['unverified_property'] = 'synthetic-label'
        with self.assertRaises(ExportRuntimeError) as raised:
            self._start(client, payload)
        self.assertEqual('EXPORT_COLUMNS_INVALID', raised.exception.code)
        client._executor.execute.assert_not_called()
        client.read.assert_not_called()
        self.assertEqual([], client._export_runtime.calls)

    def test_absent_changed_or_ambiguous_metadata_fails_before_list_and_create(self):
        cases = [_metadata()[:-1], [* _metadata(), _metadata()[0]]]
        nested = _metadata()
        nested[0] = {'name': 'synthetic-container', 'dim_table': [nested[0]]}
        cases.append(nested)
        for key, value in [('data_type', 'NUMBER'), ('cname', 'changed-label'), ('app_id', 202), ('visible', False)]:
            rows = _metadata()
            rows[0][key] = value
            cases.append(rows)
        for rows in cases:
            with self.subTest(metadata_case=len(rows)):
                client = self._client(rows)
                with self.assertRaises(ExportRuntimeError) as raised:
                    self._start(client)
                self.assertEqual('metadata', raised.exception.stage)
                self.assertNotIn('changed-label', str(raised.exception))
                client.read.assert_not_called()
                self.assertEqual([], client._export_runtime.calls)

    def test_metadata_pagination_is_complete_before_accepting_fields(self):
        client = self._client()
        client._executor.execute.side_effect = [_metadata_result(_metadata()[:2], has_more=True), _metadata_result(_metadata()[2:])]
        self._start(client)
        self.assertEqual([1, 2], [call.args[1]['page'] for call in client._executor.execute.call_args_list])

    def test_failed_metadata_or_total_never_creates(self):
        client = self._client()
        client._executor.execute.return_value = SimpleNamespace(to_dict=lambda: {'ok': False, 'status': 'error', 'error': {'message': 'synthetic-secret'}})
        with self.assertRaises(ExportRuntimeError) as raised:
            self._start(client)
        self.assertNotIn('synthetic-secret', str(raised.exception))
        client = self._client(total=True)
        with self.assertRaises(ExportRuntimeError):
            self._start(client)
        self.assertEqual([], client._export_runtime.calls)

    def test_two_original_columns_remain_usable_without_custom_metadata(self):
        client = self._client()
        payload = _payload()
        payload['field_map'] = {code: LABELS[code] for code in ('ClientID', 'CreateTime')}
        self._start(client, payload)
        client._executor.execute.assert_not_called()
        self.assertEqual(1, len(client._export_runtime.calls))

    def test_resume_requires_same_task_projection_before_status(self):
        client = self._client()
        with tempfile.TemporaryDirectory() as root:
            for receipt in (None, {'job_id': 'wrong', 'requested_columns': list(CODES)}):
                with self.subTest(receipt=receipt), self.assertRaises(ExportRuntimeError):
                    client.export_download(OPERATION, '17', Path(root) / 'out.xlsx', completeness=receipt)
        self.assertEqual([], client._export_runtime.calls)

    def test_timeout_retains_projection_total_and_download_instructions(self):
        snapshot = self._start(self._client())['completeness']
        gateway = SimpleNamespace(create=Mock(return_value=ExportJobSnapshot('17', ExportState.QUEUED, completeness=snapshot)))
        clock = iter([0, 10])
        with tempfile.TemporaryDirectory() as root:
            policy, privacy = export_file_policies(CONTRACT, Path(root), requested_columns=CODES)
            request = ExportCreationRequest({}, privacy.allowed_columns, 'synthetic-export-key-203', snapshot)
            result = ExportOrchestrator(gateway, Mock(), monotonic_clock=lambda: next(clock)).start(request, 'out.xlsx', policy, privacy, timeout_seconds=1)
        self.assertEqual(ExportState.TIMED_OUT, result.state)
        self.assertEqual(snapshot, result.completeness)
        workflow = CONTRACT.description()['workflow']
        self.assertIn('--completeness <receipt.json>', workflow['commands'][-1])
        self.assertIn('not the full envelope', workflow['recovery'])


class UserDetailFileTests(unittest.TestCase):
    def _finalize(self, source, destination, columns=CODES):
        _, privacy = export_file_policies(CONTRACT, destination.parent, requested_columns=columns)
        return ExportPrivacyFinalizer(privacy).finalize(source, destination, _xlsx_metadata(source))

    def test_string_precision_sparse_nulls_and_snapshot_semantics(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / 'source.part', Path(root) / 'out.final'
            _workbook(source)
            result = self._finalize(source, destination)
            self.assertEqual(source.read_bytes(), destination.read_bytes())
            self.assertEqual(2, result.rows_processed)
            self.assertEqual({LABELS[code]: int(code.startswith('user')) for code in CODES}, result.details['empty_values_by_column'])
            self.assertEqual('current-at-extraction', result.details['temporal_semantics'])
            receipt = SimpleNamespace(destination=destination, size_bytes=1, source_size_bytes=1, source_sha256='0'*64,
                                      committed_sha256='0'*64, content_type='xlsx', extension='.xlsx', etag=None, last_modified=None, finalization=result)
            public = _file_receipt(receipt)
            self.assertEqual(result.details['empty_values_by_column'], public['empty_values_by_column'])
            self.assertNotIn(VALUES['ClientID'], json.dumps(public))

    def test_missing_requested_column_and_reordered_file_fail_closed(self):
        for codes, missing in ((CODES[:-1], 1), (tuple(reversed(CODES)), None)):
            with self.subTest(codes=codes), tempfile.TemporaryDirectory() as root:
                source, destination = Path(root) / 'source.part', Path(root) / 'out.xlsx'
                _workbook(source, codes=codes)
                with self.assertRaises(ExportRuntimeError) as raised:
                    self._finalize(source, destination)
                diagnostic = _failure_diagnostics(raised.exception)['diagnostics']
                self.assertEqual(('headers', 'schema_mismatch'), (diagnostic['stage'], diagnostic['reason']))
                self.assertEqual(missing, diagnostic.get('missing_column_count'))
                self.assertFalse(destination.exists())

    def test_headers_are_exact_text_and_never_formulas(self):
        for kwargs in ({'labels': {**LABELS, 'ClientID': ' ' + LABELS['ClientID']}},
                       {'header_overrides': {'ClientID': lambda cell: ET.SubElement(cell, 'f')}}):
            with self.subTest(kind=next(iter(kwargs))), tempfile.TemporaryDirectory() as root:
                source, destination = Path(root) / 'source.part', Path(root) / 'out.xlsx'
                _workbook(source, **kwargs)
                with self.assertRaises(ExportRuntimeError):
                    self._finalize(source, destination)
                self.assertFalse(destination.exists())

    def test_identifier_number_version_text_and_datetime_number_are_not_coerced(self):
        for code, value in [('ClientID', 9007199254740993), ('useraccount_id', 123), ('Version', '12'), ('Version', float('nan')), ('CreateTime', 46000), ('userfirst_login_time', 46000)]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as root:
                source, destination = Path(root) / 'source.part', Path(root) / 'out.xlsx'
                _workbook(source, records=[{**VALUES, code: value}])
                with self.assertRaises(ExportRuntimeError) as raised:
                    self._finalize(source, destination)
                diagnostic = _failure_diagnostics(raised.exception)['diagnostics']
                self.assertEqual('cell_type_mismatch', diagnostic['reason'])
                self.assertEqual(CODES.index(code) + 1, diagnostic['column'])
                self.assertNotIn(VALUES['ClientID'], str(raised.exception))
                self.assertFalse(destination.exists())

    def test_formula_cannot_hide_behind_cached_string(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / 'source.part', Path(root) / 'out.xlsx'
            _workbook(source, overrides={'useruser_ab': lambda cell: ET.SubElement(cell, 'f')})
            with self.assertRaises(ExportRuntimeError) as raised:
                self._finalize(source, destination)
            self.assertEqual('xlsx_framing', raised.exception.stage)

    def test_date_style_cannot_turn_version_integer_into_a_date(self):
        styles = [
            ('<styleSheet><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>', 'cell_types'),
            ('<styleSheet><numFmts><numFmt numFmtId="0" formatCode="yyyy-mm-dd"/></numFmts><cellXfs><xf numFmtId="0"/><xf numFmtId="0"/></cellXfs></styleSheet>', 'xlsx_framing'),
        ]
        for xml, stage in styles:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as root:
                source, destination = Path(root) / 'source.part', Path(root) / 'out.xlsx'
                _workbook(source, overrides={'Version': lambda cell: cell.set('s', '1')}, styles=xml)
                with self.assertRaises(ExportRuntimeError) as raised:
                    self._finalize(source, destination)
                self.assertEqual(stage, raised.exception.stage)
                self.assertFalse(destination.exists())

    def test_projection_subset_requires_only_selected_headers(self):
        columns = ('ClientID', 'CreateTime', 'useruser_ab')
        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / 'source.part', Path(root) / 'out.xlsx'
            _workbook(source, codes=columns)
            result = self._finalize(source, destination, columns)
            self.assertEqual(tuple(LABELS[code] for code in columns), result.schema)

    def test_empty_values_are_orthogonal_to_missing_rows_or_truncation(self):
        for rows, total, expected in [(2, 2, 'complete'), (1, 2, 'partial'), (0, 2, 'partial'), (0, 0, 'empty'), (1_000_000, 1_000_001, 'truncated')]:
            with self.subTest(rows=rows, total=total):
                snapshot = classify_export_rows(rows, {'known_total_items': total})
                result = SimpleNamespace(error=None, receipt=SimpleNamespace(finalization=SimpleNamespace(rows_processed=rows)), completeness=snapshot)
                self.assertEqual(expected, result_completion_status(result))
                if rows == 0 and total > 0:
                    self.assertNotEqual('complete', export_result_obligations(result).data_completeness.state.value)


if __name__ == '__main__':
    unittest.main()
