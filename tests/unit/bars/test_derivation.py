"""Tests for src/intelligence/bars/derivation.py, the record types d2-v2 shares.

The d2-v1 rule (derive_daily) and its tests were deleted in plan 185-42; daily_rule.py's tests
cover the rule. What stays here is the contract of the shared types.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime

import pytest

from src.intelligence.bars import derivation
from src.intelligence.bars.derivation import CanonicalBar, Observation, SplitRecord


def test_frozen_dataclasses_reject_mutation():
    bar = CanonicalBar(
        bar_date=date(2024, 1, 2),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10,
        source="ibkr_named",
        request_ids=("r",),
        flags=(),
    )
    with pytest.raises(FrozenInstanceError):
        bar.close = 2.0  # type: ignore[misc]


def test_defaults_observation_is_trades_and_split_has_no_evidence():
    obs = Observation(
        request_id="r",
        route="SMART",
        bar_date=date(2024, 1, 2),
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=None,
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
        legacy=False,
    )
    split = SplitRecord(
        effective_date=date(2024, 6, 10),
        recorded_at=datetime(2024, 6, 11, tzinfo=UTC),
        factor=2.0,
    )
    assert obs.what_to_show == "TRADES"
    assert split.evidence_request_ids == ()


def test_the_d2v1_rule_is_gone():
    for name in ("derive_daily", "RULE_VERSION", "split_staleness_threshold"):
        assert not hasattr(derivation, name), name
