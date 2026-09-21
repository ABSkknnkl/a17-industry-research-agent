"""Expose report-fusion fixtures to reporting tests.

Pytest only discovers conftest fixtures down a directory tree.  The canonical
fixtures live in the sibling ``tests/agents/report_fusion`` directory, so this
small forwarding module keeps one fixture implementation while making the
documented reporting-test command work.
"""

from tests.agents.report_fusion.conftest import (  # noqa: F401
    report_analysis,
    report_chapters,
    report_charts,
)
