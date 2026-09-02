from __future__ import annotations

import unittest

from gravity_insight.skill_package import (
    MAX_FILE_BYTES,
    MAX_PACKAGE_FILES,
    MAX_TOTAL_BYTES,
    SkillPackageError,
    validate_package_entries,
)


class SkillPackageTests(unittest.TestCase):
    def test_unsafe_unbounded_and_script_entries_fail_closed(self):
        cases = (
            {"../GUIDE.md": b"x"},
            {"C:/GUIDE.md": b"x"},
            {"scripts/run.py": b"print('no')"},
            {"GUIDE.md": b"x" * (MAX_FILE_BYTES + 1)},
            {"A.md": b"a", "a.md": b"b"},
            {
                f"references/{index}.md": b"x"
                for index in range(MAX_PACKAGE_FILES + 1)
            },
            {"a/b/c/d/e/f/g.md": b"x"},
            {
                f"references/{index}.bin": b"x" * (MAX_FILE_BYTES - 1)
                for index in range(MAX_TOTAL_BYTES // MAX_FILE_BYTES + 2)
            },
        )
        for entries in cases:
            with self.subTest(entries=list(entries)), self.assertRaises(
                SkillPackageError
            ):
                validate_package_entries(entries)

if __name__ == "__main__":
    unittest.main()
