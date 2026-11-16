"""The row builder keeps a missing macro value missing (todo 463, D1 rules 1 and 5).

Rows reach feature_vectors through `feature_vector_row_values`, which maps a missing macro
value (the kernels' NaN before the first daily record, 186 review F9/B5a) to NULL, never 0.0 and
never the text NaN.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from src.intelligence.features.feature_vector_persistence import (
    feature_vector_row_values,
    feature_vectors_numeric_columns,
)
from tests.unit.intelligence import test_macro_alignment as tma


def test_the_rebuild_row_builder_writes_the_early_nan_as_null_not_zero():
    """The row builder maps the kernels' NaN to None (NULL after COPY)."""
    numeric_names = feature_vectors_numeric_columns()
    numeric = [1.0] * len(numeric_names)
    for name in ("vix_z", "tip_tlt_ret_z", "hyg_lqd_ret_z", "equity_beta_z"):
        numeric[numeric_names.index(name)] = np.float32("nan")
    row = feature_vector_row_values(
        "QQQ", "5m", tma._row_ts(tma.TARGET_SESSION, 14, 0), None, None, numeric
    )
    values = row[5:]
    for name in ("vix_z", "tip_tlt_ret_z", "hyg_lqd_ret_z", "equity_beta_z"):
        assert values[numeric_names.index(name)] is None, name

    import services.backfill_feature_factory as bff

    rebuild_source = Path(bff.__file__).read_text()
    forbidden = ("FeatureFactory.compute", "build_feature_vector_row", "validate_feature_vector")
    for needle in forbidden:
        assert needle not in rebuild_source, needle
