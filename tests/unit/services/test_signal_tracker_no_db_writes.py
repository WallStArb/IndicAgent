"""Static source-text assertion: SignalTracker has no DB write statements.

ComputeAgent role: zero DB writes. This test reads the source file and
asserts that none of the forbidden SQL/DB-write patterns are present.

test_compute_agent_no_db_writes:
  - Reads services/signal_tracker_compute_agent.py as plain text
  - Asserts each forbidden pattern is absent (case-insensitive)
"""

import re
from pathlib import Path

import pytest


class TestComputeAgentNoDbWrites:
    """Static check: no INSERT/UPDATE/DELETE on signal_ledger in the compute agent."""

    @pytest.mark.unit
    def test_compute_agent_no_db_writes(self):
        """SignalTracker source must not contain DB write statements."""
        source = Path("services/signal_tracker_compute_agent.py").read_text()

        forbidden_patterns = [
            r"INSERT\s+INTO\s+signal_ledger",
            r"UPDATE\s+signal_ledger",
            r"DELETE\s+FROM\s+signal_ledger",
            r"bulk_startup_expire",
            r"orphaned_pre_restart",
            r"activation_probability",
        ]

        violations = []
        for pattern in forbidden_patterns:
            match = re.search(pattern, source, re.IGNORECASE)
            if match:
                # Find line number for helpful failure message
                pos = match.start()
                line_number = source[:pos].count("\n") + 1
                violations.append(
                    f"  Pattern {pattern!r} found at line {line_number}: "
                    f"{source.splitlines()[line_number - 1].strip()!r}"
                )

        assert not violations, (
            "SignalTracker contains forbidden DB-write patterns "
            "(ComputeAgent must be DB-ignorant):\n" + "\n".join(violations)
        )
