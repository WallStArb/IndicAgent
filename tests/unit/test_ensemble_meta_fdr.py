from services.ensemble_trainer import _meta_eligible


def test_meta_eligible_boundary_inclusive():
    rows = [
        {"feature_name": "momentum_z_fast", "tf": "5m", "fdr_pass_rate": 0.60, "n_cells": 200},
        {"feature_name": "noise_feat", "tf": "5m", "fdr_pass_rate": 0.10, "n_cells": 200},
        {"feature_name": "edge_feat", "tf": "5m", "fdr_pass_rate": 0.50, "n_cells": 150},
    ]
    result = _meta_eligible(rows, min_fraction=0.50, min_cells=3)
    assert result == {"5m": {"momentum_z_fast", "edge_feat"}}  # 0.50 is inclusive


def test_meta_eligible_strict_threshold():
    rows = [
        {"feature_name": "momentum_z_fast", "tf": "5m", "fdr_pass_rate": 0.60, "n_cells": 200},
        {"feature_name": "edge_feat", "tf": "5m", "fdr_pass_rate": 0.50, "n_cells": 150},
    ]
    assert _meta_eligible(rows, min_fraction=0.70, min_cells=3) == {}


def test_meta_eligible_empty_input():
    assert _meta_eligible([], min_fraction=0.50, min_cells=3) == {}


def test_meta_eligible_scopes_per_timeframe():
    """A feature strong at 1d but weak at 5m must be admitted for 1d only -- pooling
    across timeframes would silently veto it everywhere (the bug this replaces)."""
    rows = [
        {"feature_name": "vix_z", "tf": "1d", "fdr_pass_rate": 0.75, "n_cells": 4},
        {"feature_name": "vix_z", "tf": "5m", "fdr_pass_rate": 0.20, "n_cells": 40},
    ]
    result = _meta_eligible(rows, min_fraction=0.50, min_cells=3)
    assert result == {"1d": {"vix_z"}}
    assert "5m" not in result or "vix_z" not in result.get("5m", set())


def test_meta_eligible_min_cells_floor_excludes_single_cell():
    """A single-cell 100% pass rate is a tautology, not replication evidence."""
    rows = [
        {"feature_name": "ofi_z", "tf": "15m", "fdr_pass_rate": 1.0, "n_cells": 1},
    ]
    assert _meta_eligible(rows, min_fraction=0.50, min_cells=3) == {}


def test_meta_eligible_min_cells_floor_boundary_inclusive():
    rows = [
        {"feature_name": "atr_z", "tf": "1d", "fdr_pass_rate": 0.6667, "n_cells": 3},
    ]
    result = _meta_eligible(rows, min_fraction=0.50, min_cells=3)
    assert result == {"1d": {"atr_z"}}
