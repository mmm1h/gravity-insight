from __future__ import annotations

import unittest

import gravity_sdk
from gravity_sdk import GravitySDK
from gravity_sdk.analysis_artifact import AnalysisArtifactService
from tests.test_analysis_result_contract import success_result


class AnalysisArtifactSurfaceTests(unittest.TestCase):
    def test_root_exports_are_reachable_and_share_the_canonical_service(self):
        artifact = gravity_sdk.compile_analysis_artifact(success_result())
        self.assertEqual(artifact, gravity_sdk.validate_analysis_artifact(artifact))
        self.assertEqual(
            artifact,
            gravity_sdk.verify_analysis_artifact_source(artifact, success_result()),
        )
        rendering = gravity_sdk.render_analysis_artifact_markdown(artifact)
        self.assertEqual("gravity.analysis-rendering.v1", rendering["schema_version"])
        self.assertIs(gravity_sdk.AnalysisArtifactService, AnalysisArtifactService)

    def test_sdk_service_is_lazy_cached_and_constructs_no_clients(self):
        sdk = GravitySDK(
            insight_factory=lambda: self.fail("Artifact delivery must stay offline"),
            sql_factory=lambda: self.fail("Artifact delivery must stay offline"),
        )
        first = sdk.analysis_artifacts
        second = sdk.analysis_artifacts
        self.assertIs(first, second)
        artifact = first.compile(success_result())
        self.assertEqual("gravity.analysis-artifact.v1", artifact["schema_version"])
        self.assertFalse(artifact["network_called"])


if __name__ == "__main__":
    unittest.main()
