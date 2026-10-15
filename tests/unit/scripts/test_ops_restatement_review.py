"""scripts/ops/bars/ops_restatement_review.py: the basis-change review queue (fourth review of
plan 191-07, finding 2). Fakes only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from scripts.ops.bars import ops_restatement_review as review

_ROW = (
    uuid.UUID(int=1),
    "GE",
    "5m",
    "ibkr",
    "named",
    1014,
    1014,
    1.0,
    ["share"],
    "changed 1014 / stored 1014 = 1.0000",
    datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
)


def test_a_flag_line_names_the_load_series_share_and_review():
    line = review.format_flag(_ROW)
    assert line.startswith(str(uuid.UUID(int=1))) and "GE 5m ibkr/named" in line
    assert "changed 1014/1014 (100.00%)" in line and "reviewed" not in line
    reviewed = _ROW + (datetime(2026, 10, 16, tzinfo=UTC), "brandon", "precision change")
    assert "reviewed 2026-10-16 by brandon: precision change" in review.format_flag(reviewed)


def test_marking_needs_a_reviewer_and_a_note():
    with pytest.raises(SystemExit):
        review.main(["--mark", str(uuid.UUID(int=1)), "--by", "brandon"])
