"""Unit test: regime writer run-status classification.

Verifies _determine_run_status() correctly distinguishes a total failure
(every attempted write failed) from a partial failure (some writes failed,
others succeeded) and a clean run. Confirmed 2026-08-13: a disk-full/Postgres-
crash window caused every symbol/tf write in a 9h40m HMM run to fail, and the
run still logged regime_writer.run_complete because the prior logic only
checked `if failures:` for a warning, never gating overall status on whether
any write actually succeeded.

No DB, no Kafka. Pure function.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.regime_writer import _determine_run_status


def test_total_failure_is_marked_failure():
    """Zero rows written despite attempted work must be a hard failure."""
    status = _determine_run_status(total_updated=0, failures=["AAPL/1m", "MSFT/1m"])
    assert status == "failure"


def test_partial_failure_is_still_success():
    """Some cells failing while others succeed remains a success run."""
    status = _determine_run_status(total_updated=42, failures=["AAPL/1m"])
    assert status == "success"


def test_clean_run_with_no_failures_is_success():
    status = _determine_run_status(total_updated=100, failures=[])
    assert status == "success"


def test_no_work_attempted_and_no_failures_is_success():
    """Zero updates with zero failures means nothing was attempted, not a failure."""
    status = _determine_run_status(total_updated=0, failures=[])
    assert status == "success"
