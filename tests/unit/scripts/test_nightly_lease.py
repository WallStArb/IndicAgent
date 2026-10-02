"""Unit tests for the nightly's lease behavior (phase 185 plan 09, D-29).

The nightly no longer skips when another backfill runs: its legs take the
ibkr_history_stream lease at priority tier with a wait bound from APR, and a leg
that cannot get the lease in time fails loudly (status failed_lease_timeout, an
integrity fact, a nonzero exit) instead of silently costing the daily bars a
night. Everything here runs against fakes; no DB, no subprocess.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.infrastructure.backfill import infrastructure_nightly_backfill as nightly
from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
    EXIT_LEASE_TIMEOUT,
)
from tests.unit._source_grep_helpers import read_source


def test_pgrep_skip_is_gone():
    source = read_source(
        "scripts", "infrastructure", "backfill", "infrastructure_nightly_backfill.py"
    )
    assert "_is_another_backfill_running" not in source
    assert "skipped_concurrent_run" not in source


def _drive_main(monkeypatch, returncodes, wait_minutes=60):
    """Run nightly.main() with both legs non-empty and patched dispatch."""
    statuses: list[str] = []
    facts: list[tuple] = []
    delegate_calls: list[tuple] = []

    by_leg = {leg.name: [f"{leg.name.upper()}1"] for leg in nightly._LEGS}

    def _fake_delegate(symbols, extra_args):
        delegate_calls.append((tuple(symbols), tuple(extra_args)))
        return returncodes.pop(0)

    def _fake_emit(conn, monitor_type, subject, metric_name, *args, **kwargs):
        facts.append((monitor_type, subject, metric_name))

    job_counter = MagicMock()
    job_counter.add.side_effect = lambda _n, labels: statuses.append(labels["status"])

    with (
        patch.object(nightly, "setup_service_logging"),
        patch.object(nightly, "Settings"),
        patch.object(nightly, "connect_db"),
        patch.object(nightly, "_select_stalest", side_effect=lambda _c, leg: by_leg[leg.name]),
        patch.object(nightly, "_load_lease_wait_minutes", return_value=wait_minutes),
        patch.object(nightly, "_run_delegate", side_effect=_fake_delegate),
        patch.object(nightly, "_run_daily_stage", return_value=0),
        patch.object(nightly, "emit_integrity_fact_sync", side_effect=_fake_emit),
        patch.object(nightly, "flush_and_shutdown_metrics"),
        patch.object(nightly, "JOB_COMPLETED_TOTAL", job_counter),
    ):
        rc = nightly.main()

    return SimpleResult(rc=rc, statuses=statuses, facts=facts, delegate_calls=delegate_calls)


class SimpleResult(dict):  # attribute access on a dict, keeps _drive_main readable
    __getattr__ = dict.__getitem__


def test_legs_run_at_priority_tier_with_apr_wait_bound(monkeypatch):
    result = _drive_main(monkeypatch, [0, 0], wait_minutes=45)
    assert result.rc == 0
    # Every delegate dispatch carries the priority tier and the APR wait bound.
    for _symbols, extra_args in result.delegate_calls:
        assert "--lease-tier" in extra_args
        assert extra_args[extra_args.index("--lease-tier") + 1] == "priority"
        assert "--lease-wait-minutes" in extra_args
        assert extra_args[extra_args.index("--lease-wait-minutes") + 1] == "45"
    # Both legs ran.
    assert len(result.delegate_calls) == 2


def test_lease_timeout_leg_fails_loudly_and_later_legs_still_run(monkeypatch):
    result = _drive_main(monkeypatch, [EXIT_LEASE_TIMEOUT, 0])
    # Non-zero exit, failed_lease_timeout status, an integrity fact recorded.
    assert result.rc == EXIT_LEASE_TIMEOUT
    assert result.statuses == ["failed_lease_timeout"]
    assert len(result.facts) == 1
    monitor_type, subject, metric_name = result.facts[0]
    assert metric_name == "nightly_lease_timeout"
    assert subject  # names the leg that timed out
    # The second leg still ran after the first timed out.
    assert len(result.delegate_calls) == 2


def test_plain_failure_is_not_a_lease_timeout(monkeypatch):
    result = _drive_main(monkeypatch, [2, 0])
    assert result.rc == 2
    assert result.statuses == ["failed"]
    assert result.facts == []


class TestLoadLeaseWaitMinutes:
    def _conn(self, value):
        cursor = MagicMock()
        cursor.execute.return_value = None
        if value is None:
            cursor.fetchone.return_value = None
        else:
            cursor.fetchone.return_value = (value,)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        conn.cursor.return_value.__exit__.return_value = None
        return conn, cursor

    def test_reads_the_apr_key(self):
        conn, cursor = self._conn("90")
        assert nightly._load_lease_wait_minutes(conn) == 90
        assert "config_state" in cursor.execute.call_args[0][0]
        assert cursor.execute.call_args[0][1] == ("infra.ibkr_history_lease.nightly_wait_minutes",)

    def test_falls_back_to_the_seed_when_absent(self):
        conn, _cursor = self._conn(None)
        assert nightly._load_lease_wait_minutes(conn) == 60
