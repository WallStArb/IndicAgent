"""Shared guards for script tests.

The nightly backfill records its status in logs/nightly_backfill_status.json and runs the D7
reconciliation audit as a subprocess against the live database on every main() path (plan
185-23). Every test in this package that drives the nightly gets the status file redirected
to a temp dir and the audit replaced by a mock, so no test writes the production status file
or spawns a live audit. Tests that assert on the audit call request `nightly_audit` by name.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

_NIGHTLY = "scripts.infrastructure.backfill.infrastructure_nightly_backfill"


@pytest.fixture(autouse=True)
def nightly_audit(monkeypatch, tmp_path):
    module = sys.modules.get(_NIGHTLY)
    if module is None:
        yield None
        return
    audit = MagicMock(return_value=0)
    monkeypatch.setattr(module, "_STATUS_FILE", tmp_path / "nightly_backfill_status.json")
    monkeypatch.setattr(module, "_run_reconciliation_audit", audit)
    yield audit
