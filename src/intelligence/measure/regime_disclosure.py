"""regime_volatility-stratified IC, disclosure only (D-17, design section 11).

The only regime-stratified IC the package computes. The per-symbol x regime grid is gone; the
name and signature are specific to `regime_volatility` on purpose.
"""

from __future__ import annotations

import numpy as np

from src.intelligence.measure.ic import IcCell, existing_rows, observation_rows, pooled_rank_ic
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import TargetStack, stride


def _is_missing_label(v: object) -> bool:
    return v is None or v == "" or (isinstance(v, float) and v != v)


def _labelled(labels: np.ndarray) -> np.ndarray:
    """bool [n, m], False where the label is missing (NaN, None or an empty string)."""
    if labels.dtype.kind in "fc":
        return ~np.isnan(labels)
    if labels.dtype.kind in "iub":
        return np.ones(labels.shape, dtype=bool)
    if labels.dtype.kind == "U":
        return labels != ""
    return ~np.frompyfunc(_is_missing_label, 1, 1)(labels).astype(bool)


def regime_volatility_disclosure(
    features: np.ndarray,
    feature_names: tuple[str, ...],
    stack: TargetStack,
    regime_volatility: np.ndarray,
    params: MeasureParams,
    *,
    present: np.ndarray,
) -> tuple[dict[str, IcCell], int]:
    """One pooled cell per distinct `regime_volatility` label present, each equal to
    `pooled_rank_ic` on that label's rows at stride max(params.min_stride, horizon).

    `regime_volatility` is [n, m] aligned to the stack (the 186-14 writer loads the column from
    feature_vectors and aligns it like a feature; integer codes or strings). Returns the cells
    keyed by str(label) and the count of existing-row observations (traded bar, feature row
    present) with no label, which are counted, never assigned to a regime.
    """
    n, m = stack.targets.shape
    if regime_volatility.shape != (n, m):
        raise ValueError(f"regime_volatility {regime_volatility.shape} != stack grid {(n, m)}")
    valid = existing_rows(stack.valid_grid(), present)
    labelled = _labelled(regime_volatility)
    n_unlabelled = int((valid & ~labelled).sum())
    cells: dict[str, IcCell] = {}
    rows = valid & labelled
    distinct, code = np.unique(regime_volatility[rows].astype(str), return_inverse=True)
    codes = np.full((n, m), -1, dtype=np.intp)
    codes[rows] = code.reshape(-1)
    for j, label in enumerate(distinct):
        X, y = observation_rows(features, stack.targets, codes == j)
        cells[str(label)] = pooled_rank_ic(
            X, y, stride=stride(stack, params), params=params, feature_names=feature_names
        )
    return cells, n_unlabelled
