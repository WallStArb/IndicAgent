from services.ensemble_trainer import _meta_eligible


def test_meta_eligible_boundary_inclusive():
    rows = [
        {"feature_name": "momentum_z_fast", "fdr_pass_rate": 0.60, "n_cells": 200},
        {"feature_name": "noise_feat", "fdr_pass_rate": 0.10, "n_cells": 200},
        {"feature_name": "edge_feat", "fdr_pass_rate": 0.50, "n_cells": 150},
    ]
    result = _meta_eligible(rows, 0.50)
    assert result == {"momentum_z_fast", "edge_feat"}  # 0.50 is inclusive
    assert "noise_feat" not in result


def test_meta_eligible_strict_threshold():
    rows = [
        {"feature_name": "momentum_z_fast", "fdr_pass_rate": 0.60, "n_cells": 200},
        {"feature_name": "edge_feat", "fdr_pass_rate": 0.50, "n_cells": 150},
    ]
    assert _meta_eligible(rows, 0.70) == set()  # nothing meets 0.70


def test_meta_eligible_empty_input():
    assert _meta_eligible([], 0.50) == set()
