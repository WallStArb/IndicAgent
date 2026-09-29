"""regime_volatility-stratified IC, disclosure only (D-17, design section 11).

The only regime-stratified IC the package computes. The per-symbol x regime grid is gone; the
name and signature are specific to `regime_volatility` on purpose.
"""

from __future__ import annotations

import numpy as np

from src.intelligence.measure.ic import IcCell, observation_rows, pooled_rank_ic
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import TargetStack


def _labelled(labels: np.ndarray) -> np.ndarray:
    """bool [n, m], False where the label is missing (NaN, None or an empty string)."""
    if labels.dtype.kind in "fc":
        return ~np.isnan(labels)
    if labels.dtype.kind in "iub":
        return np.ones(labels.shape, dtype=bool)
    return np.array(
        [
            [not (v is None or v == "" or (isinstance(v, float) and v != v)) for v in row]
            for row in labels
        ],
        dtype=bool,
    ).reshape(labels.shape)


def regime_volatility_disclosure(
    features: np.ndarray,
    feature_names: tuple[str, ...],
    stack: TargetStack,
    regime_volatility: np.ndarray,
    params: MeasureParams,
) -> tuple[dict[str, IcCell], int]:
    """One pooled cell per distinct `regime_volatility` label present, each equal to
    `pooled_rank_ic` on that label's rows at stride max(params.min_stride, horizon).

    `regime_volatility` is [n, m] aligned to the stack (the 186-14 writer loads the column from
    feature_vectors and aligns it like a feature; integer codes or strings). Returns the cells
    keyed by str(label) and the count of valid-row observations with no label, which are counted,
    never assigned to a regime.
    """
    n, m = stack.targets.shape
    if regime_volatility.shape != (n, m):
        raise ValueError(f"regime_volatility {regime_volatility.shape} != stack grid {(n, m)}")
    valid = np.broadcast_to(stack.valid[:, None], (n, m))
    labelled = _labelled(regime_volatility)
    n_unlabelled = int((valid & ~labelled).sum())
    stride = max(params.min_stride, stack.horizon)
    cells: dict[str, IcCell] = {}
    present = np.unique(regime_volatility[valid & labelled].astype(str))
    as_text = regime_volatility.astype(str)
    for label in present:
        mask = valid & labelled & (as_text == label)
        X, y = observation_rows(features, stack.targets, mask)
        cells[str(label)] = pooled_rank_ic(
            X, y, stride=stride, params=params, feature_names=feature_names
        )
    return cells, n_unlabelled
