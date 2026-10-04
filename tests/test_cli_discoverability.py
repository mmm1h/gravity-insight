"""Discoverable CLI limits, output requirements and runtime version (#241, #243, #246, #223)."""

from __future__ import annotations

import contextlib
import io
from unittest.mock import patch

from gravity_insight import __version__
from gravity_insight.__main__ import main
from gravity_insight.cli import build_parser
from gravity_insight.material_performance_result import _failure_action


def _help(*argv: str) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.suppress(SystemExit):
        build_parser().parse_args([*argv, "--help"])
    return " ".join(buffer.getvalue().split())


def test_version_is_offline_and_listed_in_help():
    out = io.StringIO()
    with patch("gravity_insight.__main__._startup_upgrade_exit", side_effect=AssertionError("network")), \
            contextlib.redirect_stdout(out):
        assert main(["--version"]) == 0
    assert out.getvalue() == f"gravity-insight {__version__}\n"
    listing = io.StringIO()
    with patch("gravity_insight.__main__._startup_upgrade_exit", return_value=None), \
            patch("gravity_insight.__main__._startup_skill_maintenance"), contextlib.redirect_stdout(listing):
        main(["--help"])
    assert "gravity --version" in listing.getvalue()


def test_help_states_enforced_limit_range_and_all_pages_output_requirement():
    for command in (("metadata", "properties"), ("metadata", "search")):
        assert "1-100" in _help(*command) and "--offset" in _help(*command)
    assert "--all-pages Follow the manifest pagination contract; requires --output <path> or --format ndjson" in _help("multidim", "query")


def test_material_page_budget_limit_does_not_blame_app_dates_or_platform():
    action = _failure_action("PAGINATION_LIMIT", "caller")
    assert "--max-pages" in action and "not a wrong App" in action
    assert _failure_action("INPUT_INVALID", "caller").startswith("Correct the selected App")
