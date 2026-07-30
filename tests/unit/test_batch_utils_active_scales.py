"""Unit tests: services/_batch_utils.py's canonicalize_active_scales() and
ACTIVE_SCALES_FALLBACKS_BY_TF (per-tf active-scale-set design, 2026-07-30 spec)."""

from __future__ import annotations

import pytest

from services._batch_utils import (
    ACTIVE_SCALES_FALLBACKS_BY_TF,
    canonicalize_active_scales,
)


def test_canonicalize_preserves_canonical_order_regardless_of_input_order():
    assert canonicalize_active_scales(["mid", "fast"]) == ("fast", "mid")
    assert canonicalize_active_scales(["extended", "fast", "slow", "mid"]) == (
        "fast",
        "mid",
        "slow",
        "extended",
    )


def test_canonicalize_accepts_tuple_input():
    assert canonicalize_active_scales(("mid", "fast")) == ("fast", "mid")


def test_canonicalize_deduplicates():
    assert canonicalize_active_scales(["fast", "fast", "mid"]) == ("fast", "mid")


def test_canonicalize_rejects_unknown_scale_name():
    """Silent wrong answers are worse than loud crashes (CLAUDE.md) -- a typo'd
    scale name (e.g. 'fsat') must raise, not silently produce a smaller active set."""
    with pytest.raises(ValueError, match="fsat"):
        canonicalize_active_scales(["fsat", "mid"])


def test_canonicalize_empty_input_returns_empty_tuple():
    assert canonicalize_active_scales([]) == ()


def test_active_scales_fallbacks_cover_all_four_tfs():
    assert set(ACTIVE_SCALES_FALLBACKS_BY_TF.keys()) == {"5m", "15m", "1h", "1d"}


def test_active_scales_fallback_1h_reverted_to_all_four():
    """1h's earlier slow/extended exclusion was based on 0.000 completeness measured
    under the same-ET-session gate that forward_return_writer.py has since removed
    (todo 208, migration 272) -- that gate was the sole reason 1h's slow/extended
    read as unmeasurable, not a property of 1h itself. Reverted to all four."""
    assert ACTIVE_SCALES_FALLBACKS_BY_TF["1h"] == ("fast", "mid", "slow", "extended")


def test_active_scales_fallback_other_tfs_keep_all_four():
    for tf in ("5m", "15m", "1h", "1d"):
        assert ACTIVE_SCALES_FALLBACKS_BY_TF[tf] == ("fast", "mid", "slow", "extended")


def test_active_scales_fallbacks_already_canonically_ordered():
    for tf, scales in ACTIVE_SCALES_FALLBACKS_BY_TF.items():
        assert scales == canonicalize_active_scales(
            scales
        ), f"ACTIVE_SCALES_FALLBACKS_BY_TF[{tf!r}] is not canonically ordered"
