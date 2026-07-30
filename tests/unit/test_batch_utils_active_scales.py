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


def test_active_scales_fallback_1h_excludes_slow_extended():
    """1h's slow/extended have 0.000 measured completeness under the current
    same-session gate (see todo 208) -- the fallback reflects today's data, not a
    permanent commitment. Reversible via config alone once todo 208 resolves."""
    assert ACTIVE_SCALES_FALLBACKS_BY_TF["1h"] == ("fast", "mid")


def test_active_scales_fallback_other_tfs_keep_all_four():
    for tf in ("5m", "15m", "1d"):
        assert ACTIVE_SCALES_FALLBACKS_BY_TF[tf] == ("fast", "mid", "slow", "extended")


def test_active_scales_fallbacks_already_canonically_ordered():
    for tf, scales in ACTIVE_SCALES_FALLBACKS_BY_TF.items():
        assert scales == canonicalize_active_scales(
            scales
        ), f"ACTIVE_SCALES_FALLBACKS_BY_TF[{tf!r}] is not canonically ordered"
