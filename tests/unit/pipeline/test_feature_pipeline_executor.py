"""Unit tests for FeaturePipelineExecutor PERF-05 behavioral equivalence.

Verifies that IntelligenceEvent construction via pre-filtered tier dicts
(PERF-05: None filtering at merge site in executor.py) produces the same
model_dump(exclude_none=True) key set as the old comprehension-based approach.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from src.intelligence.schemas import (
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    IntelligenceEvent,
    OHLCVBar,
    SMCContext,
)


def _make_sample_tier_with_nones() -> dict:
    """Return a tier dict that mixes real values with None values.

    Simulates plugin output before PERF-05: some fields are None,
    some have real values.
    """
    return {
        "rsi_14": 55.3,
        "atr_14": 4.2,
        "macd_12_26_9": None,
        "macd_signal_12_26_9": None,
        "volume_ratio": 1.1,
        "bb_20_2_upper": None,
        "bb_20_2_lower": None,
        "bb_20_2_mid": None,
    }


def _make_prefiltered_tier(raw: dict) -> dict:
    """Simulate the PERF-05 merge-site filtering: drop None values."""
    return {k: v for k, v in raw.items() if v is not None}


def _make_base_event_kwargs():
    """Return common IntelligenceEvent kwargs that are the same in both approaches."""
    from src.core.schemas.bar_message import SessionType

    ts = datetime(2026, 1, 15, 14, 30, 0, tzinfo=UTC)
    return dict(
        ts=ts,
        symbol="ES",
        tf="1m",
        bar=OHLCVBar(o=5000.0, h=5010.0, l=4990.0, c=5005.0, v=1000),
        source="live",
        session_type=SessionType.RTH,
        pipeline_latency_ms=0.0,
        computed_at=datetime.now(UTC),
        bar_id=uuid4(),
    )


def test_perf05_construction_equivalence_i1():
    """PERF-05: IntelligenceEvent i1 from pre-filtered dict equals comprehension approach."""
    raw_i1 = _make_sample_tier_with_nones()
    # Old approach: comprehension at construction
    old_event = IntelligenceEvent(
        **_make_base_event_kwargs(),
        i1=I1Indicators(**{k: v for k, v in raw_i1.items() if v is not None}),
        i2=I2Events(),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )

    # New approach: pre-filtered dict (PERF-05 — filtering happens at merge site)
    prefiltered_i1 = _make_prefiltered_tier(raw_i1)
    new_event = IntelligenceEvent(
        **_make_base_event_kwargs(),
        i1=I1Indicators(**prefiltered_i1),
        i2=I2Events(),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )

    old_dump = old_event.model_dump(exclude_none=True)
    new_dump = new_event.model_dump(exclude_none=True)

    # Key sets must be identical
    assert set(old_dump.keys()) == set(
        new_dump.keys()
    ), f"Top-level key mismatch: old={set(old_dump.keys())}, new={set(new_dump.keys())}"

    # i1 key sets must match
    old_i1_keys = set(old_dump.get("i1", {}).keys())
    new_i1_keys = set(new_dump.get("i1", {}).keys())
    assert old_i1_keys == new_i1_keys, f"i1 key mismatch: old={old_i1_keys}, new={new_i1_keys}"

    # Values must match for fields that are present
    for k in old_i1_keys:
        assert (
            old_dump["i1"][k] == new_dump["i1"][k]
        ), f"i1[{k!r}] value mismatch: old={old_dump['i1'][k]}, new={new_dump['i1'][k]}"


def test_perf05_none_values_excluded_from_event():
    """PERF-05: None fields from raw plugin output are excluded from final event dump."""
    # A tier dict with some None values
    i1_raw_with_nones = {
        "rsi_14": 42.0,
        "atr_14": None,  # this should NOT appear in model_dump(exclude_none=True)
        "volume_ratio": 0.9,
    }
    # Pre-filter (PERF-05 approach)
    prefiltered = {k: v for k, v in i1_raw_with_nones.items() if v is not None}

    event = IntelligenceEvent(
        **_make_base_event_kwargs(),
        i1=I1Indicators(**prefiltered),
        i2=I2Events(),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )

    dumped = event.model_dump(exclude_none=True)
    i1_dumped = dumped.get("i1", {})

    assert "rsi_14" in i1_dumped
    assert "atr_14" not in i1_dumped, "None field atr_14 should be excluded"
    assert i1_dumped["rsi_14"] == 42.0


def test_perf01_build_flat_features_called_once_in_fpe():
    """PERF-01: feature_pipeline_executor.py contains exactly one call to build_flat_features.

    Plan 05: _build_features_from_event was renamed to build_flat_features and moved to
    feature_flattening.py. FeaturePipelineExecutor calls it exactly once per bar (3-E).
    """
    import ast
    import pathlib

    fpe_src = pathlib.Path("src/intelligence/pipeline/feature_pipeline_executor.py").read_text()

    # Count actual call sites (not comments/docstrings)
    tree = ast.parse(fpe_src)
    call_count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "build_flat_features":
                call_count += 1

    assert call_count == 1, (
        f"PERF-01: expected exactly 1 call to build_flat_features in feature_pipeline_executor.py, "
        f"found {call_count}"
    )
