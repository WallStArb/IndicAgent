"""Unit tests for _annotate_signal() pipeline-layer annotation (Phase 126-06).

Invariants:
  1. _annotate_signal() sets context_features = full flat_features snapshot
  2. ctf_score / ctf_confirmed / zone_friction_score are derived from flat_features
  3. ctf_confirmed = abs(ctf_score) >= MIN_CTF_SCORE (or None on cold-start)
  4. zone_friction_score is None when absent from flat_features (cold-start)
  5. Extensibility: new keys added to flat_features appear in context_features
     automatically without any code change
  6. No plugin body calls capture_signal_features() (annotation is pipeline-layer)
"""

from __future__ import annotations

import ast
import os

import pytest

from src.intelligence.pipeline.signal_processor import (
    _annotate_signal,
    annotate_signal_with_context,
)
from src.intelligence.trading.confidence import MIN_CTF_SCORE

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_flat_features(**overrides) -> dict:
    """Minimal flat_features dict simulating what build_flat_features() produces."""
    base = {
        "ctf_score": 0.6,
        "ctf_trend_alignment": 0.7,
        "ctf_structure_alignment": 0.5,
        "exhaustion_score": 0.2,
        "vix_level": 18.5,
        "zone_friction_score": 0.42,
    }
    base.update(overrides)
    return base


def _empty_signal() -> dict:
    """Minimal signal dict as returned by make_signal_from_frame()."""
    return {
        "type": "signal.v1",
        "direction": 1,
        "confidence": 0.7,
        "ctf_score": None,
        "ctf_confirmed": None,
        "zone_friction_score": None,
        "context_features": {},
        "factor_scores": {},
    }


# ---------------------------------------------------------------------------
# Core annotation tests
# ---------------------------------------------------------------------------


def test_annotate_signal_with_context_public_name_populates_ecl_keys():
    """annotate_signal_with_context (public alias) sets all 4 ECL keys; factor_scores absent."""
    sig = _empty_signal()
    ff = _base_flat_features(ctf_score=0.55, zone_friction_score=0.3)
    annotate_signal_with_context(sig, ff)
    assert sig["context_features"] is ff
    assert sig["ctf_score"] == pytest.approx(0.55)
    assert sig["ctf_confirmed"] is True
    assert sig["zone_friction_score"] == pytest.approx(0.3)
    assert "factor_scores" not in sig or sig["factor_scores"] == {}  # factor_scores is plugin-local


def test_annotate_sets_context_features_to_full_snapshot():
    """context_features must be the full flat_features dict (not a subset)."""
    sig = _empty_signal()
    ff = _base_flat_features()
    _annotate_signal(sig, ff)
    assert (
        sig["context_features"] is ff
    ), "context_features must be the same object as flat_features"


def test_annotate_ctf_score_float():
    """ctf_score must be extracted as float from flat_features."""
    sig = _empty_signal()
    _annotate_signal(sig, _base_flat_features(ctf_score=0.45))
    assert sig["ctf_score"] == pytest.approx(0.45)
    assert isinstance(sig["ctf_score"], float)


def test_annotate_ctf_score_none_when_absent():
    """ctf_score must be None when flat_features has no ctf_score (cold-start)."""
    sig = _empty_signal()
    ff = _base_flat_features()
    del ff["ctf_score"]
    _annotate_signal(sig, ff)
    assert sig["ctf_score"] is None


def test_annotate_ctf_confirmed_true_above_threshold():
    """ctf_confirmed = True when abs(ctf_score) >= MIN_CTF_SCORE."""
    sig = _empty_signal()
    _annotate_signal(sig, _base_flat_features(ctf_score=MIN_CTF_SCORE))
    assert sig["ctf_confirmed"] is True


def test_annotate_ctf_confirmed_false_below_threshold():
    """ctf_confirmed = False when 0 < abs(ctf_score) < MIN_CTF_SCORE."""
    sig = _empty_signal()
    _annotate_signal(sig, _base_flat_features(ctf_score=MIN_CTF_SCORE * 0.5))
    assert sig["ctf_confirmed"] is False


def test_annotate_ctf_confirmed_true_negative_ctf():
    """ctf_confirmed uses abs(ctf_score); negative values above threshold confirm."""
    sig = _empty_signal()
    _annotate_signal(sig, _base_flat_features(ctf_score=-MIN_CTF_SCORE - 0.01))
    assert sig["ctf_confirmed"] is True


def test_annotate_ctf_confirmed_none_on_cold_start():
    """ctf_confirmed = None when ctf_score is absent (cold-start)."""
    sig = _empty_signal()
    ff = _base_flat_features()
    del ff["ctf_score"]
    _annotate_signal(sig, ff)
    assert sig["ctf_confirmed"] is None


def test_annotate_zone_friction_score_present():
    """zone_friction_score extracted from flat_features when present."""
    sig = _empty_signal()
    _annotate_signal(sig, _base_flat_features(zone_friction_score=0.72))
    assert sig["zone_friction_score"] == pytest.approx(0.72)


def test_annotate_zone_friction_score_none_on_cold_start():
    """zone_friction_score = None when absent from flat_features (no zones detected)."""
    sig = _empty_signal()
    ff = _base_flat_features()
    del ff["zone_friction_score"]
    _annotate_signal(sig, ff)
    assert sig["zone_friction_score"] is None


def test_annotate_zero_zone_friction_distinct_from_none():
    """0.0 zone_friction_score (genuine neutral) must not be conflated with None."""
    sig = _empty_signal()
    _annotate_signal(sig, _base_flat_features(zone_friction_score=0.0))
    assert sig["zone_friction_score"] == pytest.approx(0.0)
    assert sig["zone_friction_score"] is not None


# ---------------------------------------------------------------------------
# Extensibility test
# ---------------------------------------------------------------------------


def test_extensibility_new_key_appears_in_context_features_automatically():
    """New key added to flat_features appears in context_features without code change.

    This is the core extensibility guarantee: build_flat_features() iterates all
    tier sub-models. When a new sub-model field is added (e.g., a new I4 macro
    signal), it flows into context_features automatically via _annotate_signal.
    No plugin changes required.
    """
    sig = _empty_signal()
    ff = _base_flat_features()
    ff["new_experimental_feature"] = 0.99  # simulate a future tier output
    _annotate_signal(sig, ff)
    assert (
        "new_experimental_feature" in sig["context_features"]
    ), "New flat_features key must appear in context_features without any code change"
    assert sig["context_features"]["new_experimental_feature"] == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# No-plugin-annotation sweep (AST check)
# ---------------------------------------------------------------------------

_TRADING_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",  # unit/
    "..",  # tests/
    "..",  # repo root
    "src",
    "intelligence",
    "trading",
)


def _get_python_files_in_dir(directory: str) -> list[str]:
    """Return absolute paths to all .py files in directory."""
    result = []
    abs_dir = os.path.abspath(directory)
    for fname in os.listdir(abs_dir):
        if fname.endswith(".py"):
            result.append(os.path.join(abs_dir, fname))
    return sorted(result)


def _ast_contains_call(tree: ast.AST, func_name: str) -> bool:
    """Return True if the AST contains a Call to func_name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == func_name:
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr == func_name:
                return True
    return False


@pytest.mark.parametrize("filepath", _get_python_files_in_dir(_TRADING_DIR))
def test_no_plugin_calls_capture_signal_features(filepath: str):
    """No I7 plugin body may call capture_signal_features() — Phase 126-06.

    Annotation is infrastructure responsibility. AST-level check prevents
    regressions where a new plugin accidentally calls the deprecated function.

    Exempt: confidence.py (defines the function),
            test_capture_signal_features.py (tests the deprecated function itself).
    """
    basename = os.path.basename(filepath)
    if basename in {"confidence.py"}:
        pytest.skip(f"{basename}: defines capture_signal_features (not a caller)")

    with open(filepath) as f:
        source = f.read()

    if "capture_signal_features" not in source:
        return  # fast path: function not mentioned at all

    tree = ast.parse(source, filename=filepath)
    assert not _ast_contains_call(tree, "capture_signal_features"), (
        f"{basename}: calls capture_signal_features() — remove it (Phase 126-06). "
        f"Annotation is pipeline-layer responsibility (_annotate_signal in signal_processor)."
    )
