"""D-06 job-label contract for signal_probe_auditor.py.

Extracted 2026-07-14 from test_i6_hmm_confidence_wiring.py (deleted - the rest of that
file tested archived I6/I7 plugin confidence wiring with no live consumer). This one
test was unrelated to that subject and covers a live oneshot service's D-06 compliance,
so it moved here rather than being deleted along with the archived-plugin tests.
"""

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit


class TestJobLabelContract:
    """Guards the D-06 oneshot completion counter label contract."""

    def test_job_label_matches_unit_suffix(self):
        """The job label constant must be 'signal-probe-auditor' (matches unit name suffix)."""
        src_path = (
            pathlib.Path(__file__).resolve().parents[3] / "services" / "signal_probe_auditor.py"
        )
        if not src_path.exists():
            pytest.skip("signal_probe_auditor.py not yet created")

        tree = ast.parse(src_path.read_text())
        found = any(
            isinstance(node, ast.Constant) and node.value == "signal-probe-auditor"
            for node in ast.walk(tree)
        )
        assert (
            found
        ), "D-06 contract: 'signal-probe-auditor' job label must appear in signal_probe_auditor.py"
