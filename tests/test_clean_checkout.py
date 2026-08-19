"""A fresh clone must be able to run the suite without creating anything first."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CleanCheckoutTests(unittest.TestCase):
    def test_repo_local_tmp_survives_a_fresh_clone(self) -> None:
        """The census fixtures build under ``tmp/``; git only ships it via the sentinel.

        ``tmp/*`` is ignored with a ``!tmp/.gitkeep`` exception, so the directory
        reaches a new clone only while that one file stays tracked. Delete it and
        the census tests fail with ``FileNotFoundError`` on a temp path, which
        names neither ``tmp/`` nor the sentinel.
        """

        sentinel = "tmp/.gitkeep"
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", sentinel],
            cwd=ROOT, check=False, capture_output=True,
        )
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", sentinel], cwd=ROOT, check=False
        )

        self.assertEqual(
            0, tracked.returncode, f"{sentinel} must stay tracked; it is the only "
            "thing that puts tmp/ in a fresh clone",
        )
        self.assertNotEqual(
            0, ignored.returncode, f"{sentinel} must be exempt from the tmp/* ignore",
        )
        self.assertTrue((ROOT / "tmp").is_dir())

    def test_every_repo_local_tmp_user_is_covered_by_that_sentinel(self) -> None:
        """Keep the guard honest if a fourth test file starts using ``tmp/``."""

        users = sorted(
            path.name
            for path in (ROOT / "tests").glob("test_*.py")
            # This file names the pattern to search for, so it matches itself.
            if path.name != Path(__file__).name
            and 'REPO_ROOT / "tmp"' in path.read_text(encoding="utf-8")
        )

        self.assertEqual(
            [
                "test_gravity_census_params.py",
                "test_gravity_census_pipeline.py",
                "test_gravity_census_response.py",
            ],
            users,
        )


if __name__ == "__main__":
    unittest.main()
