from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight.governance.module_graph import (
    MODULE_GRAPH_BASELINE_PATH, MODULE_GRAPH_DEFINITION_PATH,
    module_graph_baseline, module_graph_definition, module_graph_canonical_sha256,
)
from scripts.audit_agent_module_references import refresh_module_graph_baseline


class MachineOwnerMigrationTests(unittest.TestCase):
    def test_graph_owners_serve_reviewed_baseline_without_markdown(self):
        original = Path.read_text
        def without_markdown(path, *args, **kwargs):
            if path.suffix == ".md":
                raise FileNotFoundError(path)
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", without_markdown):
            self.assertEqual(
                "b3e0b2a61cb32c8069acec07315c1c65b94a3506c05133c7878a7a2c967f6326",
                module_graph_canonical_sha256(module_graph_definition()),
            )
            self.assertEqual(
                "a9233233fdbc928ca614a88de135a2c05d3a47a8885d2b3834f01b83c3119df0",
                module_graph_canonical_sha256(module_graph_baseline()),
            )

    def test_refresh_writes_only_structured_owners(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            definition = root / MODULE_GRAPH_DEFINITION_PATH.name
            baseline = root / MODULE_GRAPH_BASELINE_PATH.name
            definition.write_bytes(MODULE_GRAPH_DEFINITION_PATH.read_bytes())
            refresh_module_graph_baseline(baseline, definition_path=definition)
            self.assertEqual(module_graph_baseline(), module_graph_baseline(baseline))
            self.assertEqual({definition, baseline}, set(root.iterdir()))
