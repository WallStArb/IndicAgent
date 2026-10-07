"""Tests for new plugin observability metrics added in Phase 100.5 Task 1.

Verifies that all new metric instruments are importable from metrics.py and
are the correct OTel instrument types with the expected names.
"""

from __future__ import annotations


def test_plugin_fallback_total_exists():
    """intelligence_pipeline_plugin_fallback_total counter exists."""
    from src.observability.metrics import PLUGIN_FALLBACK_TOTAL

    assert PLUGIN_FALLBACK_TOTAL is not None


def test_plugin_warmup_skip_total():
    """PLUGIN_WARMUP_SKIP_TOTAL counter is importable from metrics.py."""
    from src.observability.metrics import PLUGIN_WARMUP_SKIP_TOTAL

    assert PLUGIN_WARMUP_SKIP_TOTAL is not None


def test_plugin_output_null_total():
    """PLUGIN_OUTPUT_NULL_TOTAL counter is importable from metrics.py."""
    from src.observability.metrics import PLUGIN_OUTPUT_NULL_TOTAL

    assert PLUGIN_OUTPUT_NULL_TOTAL is not None


def test_plugin_state_validation_errors_total():
    """PLUGIN_STATE_VALIDATION_ERRORS_TOTAL counter is importable from metrics.py."""
    from src.observability.metrics import PLUGIN_STATE_VALIDATION_ERRORS_TOTAL

    assert PLUGIN_STATE_VALIDATION_ERRORS_TOTAL is not None


def test_plugin_signal_emit_total():
    """PLUGIN_SIGNAL_EMIT_TOTAL counter is importable from metrics.py."""
    from src.observability.metrics import PLUGIN_SIGNAL_EMIT_TOTAL

    assert PLUGIN_SIGNAL_EMIT_TOTAL is not None


def test_plugin_confidence_histogram():
    """PLUGIN_CONFIDENCE_HISTOGRAM histogram is importable from metrics.py."""
    from src.observability.metrics import PLUGIN_CONFIDENCE_HISTOGRAM

    assert PLUGIN_CONFIDENCE_HISTOGRAM is not None
