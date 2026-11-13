"""ops_rerecord_session_choices: the repair re-selects stale sessions and refuses to move canonical."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts.ops.bars import ops_rerecord_session_choices as mod


def test_the_window_covers_one_session_and_stays_in_one_utc_day_pair():
    start, end = mod._day_window(date(2006, 12, 27))
    assert start == datetime(2006, 12, 27, 12, 0, tzinfo=UTC)
    assert (end - start).total_seconds() == 12 * 3600


def _params():
    return SimpleNamespace(kind_order={"x": 0}, write=SimpleNamespace(batch_rows=100))


def _run(result):
    conn = MagicMock()
    with (
        patch.object(mod, "read_raw_params", return_value=_params()),
        patch.object(mod, "select_and_write", return_value=result) as writer,
    ):
        changed = mod.rerecord(conn, {("A", "5m"): [date(2006, 12, 27)]})
    return changed, writer


def test_a_repair_that_changes_no_canonical_row_reports_zero():
    changed, writer = _run(SimpleNamespace(new=0, changed=0))
    assert changed == 0
    assert writer.call_args.kwargs["symbols"] == ["A"]
    assert writer.call_args.kwargs["policy_rows"] is None


def test_a_repair_that_would_change_canonical_is_reported_for_abort():
    changed, _ = _run(SimpleNamespace(new=1, changed=2))
    assert changed == 3
