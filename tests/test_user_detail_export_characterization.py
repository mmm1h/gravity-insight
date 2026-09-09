"""Issue 203 evidence and retained generic finalizer characterization.

Typed user-detail acceptance is covered in test_user_detail_export_projection.
Untyped generic contracts retain their characterized behavior. All cell values below
are synthetic; the evidence fixture contains only field metadata and counts.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock
from xml.etree import ElementTree as ET
import zipfile

from gravity_insight.export_contracts import ExportContractRegistry
from gravity_insight.export_models import ExportPrivacyContract, ExportRuntimeError
from gravity_insight.export_privacy import ExportPrivacyFinalizer, _validate_actual_schema
from gravity_insight.export_scope_total import pin_export_scope_total
from gravity_insight.paths import CONTRACT_ROOT
from gravity_insight.registry import PolicyEngine
from tests.test_gravity_insight_export_integration import _xlsx_metadata, read_registry


EVIDENCE = json.loads(
    (Path(__file__).parent / 'fixtures/user_detail_export_projection_evidence.json')
    .read_text(encoding='utf-8')
)
OPERATION = EVIDENCE['operation_id']


def _payload():
    labels = {row['code']: row['header'] for row in EVIDENCE['columns']}
    return {
        'app_id': 101,
        'field_map': {code: labels[code] for code in EVIDENCE['request_order']},
        'task_name': 'synthetic-profile-characterization',
        'global_conditions': [{
            'field': 'create_date_list', 'operator': 'RANGE_IN', 'type': 'default_user',
            'value': ['2026-01-01 00:00:00', '2026-01-01 23:59:59'],
        }],
        'postback_conditions': [], 'user_cond_logic': 'AND', 'postback_cond_logic': 'AND',
    }


def _synthetic_xlsx(path, *, numeric_identifier=False):
    headers = ('identifier', 'profile', 'version')
    rows = (
        headers,
        (9007199254740993 if numeric_identifier else '9007199254740993', 'fixture-a', 12),
        ('000000000000000002', None, 12),
    )
    worksheet = ET.Element('worksheet')
    data = ET.SubElement(worksheet, 'sheetData')
    strings = ET.Element('sst')
    count = 0
    for row_index, row in enumerate(rows, 1):
        element = ET.SubElement(data, 'row', r=str(row_index))
        for index, value in enumerate(row):
            if value is None:
                continue
            cell = ET.SubElement(element, 'c', r=f'{chr(65 + index)}{row_index}', t='s' if isinstance(value, str) else 'n')
            if isinstance(value, str):
                ET.SubElement(ET.SubElement(strings, 'si'), 't').text = value
                ET.SubElement(cell, 'v').text = str(count)
                count += 1
            else:
                ET.SubElement(cell, 'v').text = str(value)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('xl/sharedStrings.xml', ET.tostring(strings))
        archive.writestr('xl/worksheets/sheet1.xml', ET.tostring(worksheet))
    return headers


class UserDetailExportCharacterizationTests(unittest.TestCase):
    def test_effect_receipt_sorts_projection_before_transport(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_ROOT / 'exports/routes-v1.json')
        policy = PolicyEngine(read_registry(), effect_routes=contracts.effect_routes())
        payload = _payload()
        receipt = policy._prepare_effect_request(OPERATION, 'export_job_create', payload)
        _, body = policy._consume_effect_request(
            receipt, method=receipt.method, path=receipt.path,
            query=receipt.query, body=receipt.body,
        )
        self.assertEqual(EVIDENCE['authorized_wire_and_file_order'], list(body['field_map']))
        self.assertNotEqual(list(payload['field_map']), list(body['field_map']))

    def test_current_header_gate_rejects_absence_but_accepts_reordering(self):
        contract = ExportPrivacyContract(('identifier', 'profile'), ('identifier', 'profile'), classification='user_level', format='xlsx')
        _validate_actual_schema(('profile', 'identifier'), contract)
        with self.assertRaises(ExportRuntimeError) as raised:
            _validate_actual_schema(('identifier',), contract)
        self.assertEqual(['profile'], raised.exception.details['missing_required_columns'])

    def test_sparse_file_keeps_text_bytes_but_has_no_empty_value_audit(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / 'source.xlsx', Path(root) / 'output.xlsx'
            headers = _synthetic_xlsx(source)
            contract = ExportPrivacyContract(headers, headers, classification='user_level', format='xlsx')
            result = ExportPrivacyFinalizer(contract).finalize(source, output, _xlsx_metadata(source))
            self.assertEqual(source.read_bytes(), output.read_bytes())
            self.assertEqual(2, result.rows_processed)
            self.assertEqual({'worksheets': 1}, dict(result.details))

    def test_current_gate_has_no_numeric_identifier_type_rejection(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / 'source.xlsx', Path(root) / 'output.xlsx'
            headers = _synthetic_xlsx(source, numeric_identifier=True)
            contract = ExportPrivacyContract(headers, headers, classification='user_level', format='xlsx')
            result = ExportPrivacyFinalizer(contract).finalize(source, output, _xlsx_metadata(source))
            self.assertEqual(2, result.rows_processed)
            self.assertTrue(output.is_file())

    def test_user_detail_now_pins_a_task_bound_total(self):
        client = SimpleNamespace(read=Mock(return_value={'ok': True, 'page': {'total_items': 1176}}))
        snapshot = pin_export_scope_total(client, OPERATION, _payload())
        self.assertEqual(1176, snapshot['known_total_items'])
        self.assertEqual('create_time_preflight', snapshot['known_total_freshness'])
        client.read.assert_called_once()

    def test_sanitized_evidence_distinguishes_empty_cells_from_missing_rows(self):
        total = EVIDENCE['completeness_evidence']['known_total_items']
        self.assertEqual(total, EVIDENCE['file']['rows'])
        for column in EVIDENCE['columns']:
            with self.subTest(code=column['code']):
                self.assertTrue(column['upstream_returned'])
                self.assertEqual(total, column['empty_rows'] + column['nonempty_rows'])


if __name__ == '__main__':
    unittest.main()
