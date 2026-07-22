"""Unit tests: AlphaScorer (SCORE-01) decile bucketing + monotonicity diagnostic.

Wave 0 stub -- services/alpha_scorer.py does not exist yet. These are RED-by-construction
placeholders naming the concrete targets Wave 2's SCORE-01 build plan (148-02) fills in.
Do NOT import services.alpha_scorer at module scope: the module doesn't exist yet, and a
module-scope import would break `pytest --collect-only` with an ImportError instead of a
clean RED failure.

No DB, no Kafka -- these will be pure-function tests once implemented, mirroring
tests/unit/test_ensemble_ic_gate.py's shape.
"""

from __future__ import annotations

import pytest


def test_buckets_deciles_and_filters_min_strategy_n():
    """AlphaScorer buckets alpha_frames into (symbol, tf, regime, decile) cells and
    filters out cells with sample_n < alpha.scoring.min_strategy_n.

    Wave 2 (148-02) implements services/alpha_scorer.py's decile-binning + N-floor
    filtering logic; this test will exercise it directly once it exists.
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")


def test_ic_alpha_score_corr_monotonic():
    """ic_alpha_score_corr (correlation between alpha_score_decile rank and
    mean_pnl_r) is computed correctly as a monotonicity diagnostic -- DIAGNOSTIC-ONLY,
    not a gate threshold (alpha.scoring.min_ic_alpha_score_corr, migration 248).

    Wave 2 (148-02) implements the corr computation in services/alpha_scorer.py.
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")
