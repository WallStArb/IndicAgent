"""regime_volatility-stratified IC, disclosure only (D-17, design section 11).

The only regime-stratified IC the package computes. The per-symbol x regime grid is gone; the
name and signature are specific to `regime_volatility` on purpose.
"""

from __future__ import annotations

from collections.abc import Mapping

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


def label_row_masks(
    existing: np.ndarray, regime_volatility: np.ndarray
) -> tuple[dict[str, np.ndarray], int]:
    """[n, m] bool row mask of each distinct `regime_volatility` label (str(label), sorted) over
    the existing rows `existing` (traded bar, feature row present), and the count of existing
    rows with no label, which belong to no regime. The one label-to-rows assignment both the
    disclosure and the writer's family completeness use."""
    if regime_volatility.shape != existing.shape:
        raise ValueError(f"regime_volatility {regime_volatility.shape} != grid {existing.shape}")
    labelled = _labelled(regime_volatility)
    n_unlabelled = int((existing & ~labelled).sum())
    rows = existing & labelled
    distinct, code = np.unique(regime_volatility[rows].astype(str), return_inverse=True)
    codes = np.full(existing.shape, -1, dtype=np.intp)
    codes[rows] = code.reshape(-1)
    return {str(label): codes == j for j, label in enumerate(distinct)}, n_unlabelled


def regime_volatility_disclosure(
    features: np.ndarray,
    feature_names: tuple[str, ...],
    stack: TargetStack,
    regime_volatility: np.ndarray,
    params: MeasureParams,
    *,
    present: np.ndarray,
    complete: Mapping[str, np.ndarray] | None = None,
) -> tuple[dict[str, IcCell], int]:
    """One pooled cell per distinct `regime_volatility` label present, each equal to
    `pooled_rank_ic` on that label's rows at stride max(params.min_stride, horizon).

    `regime_volatility` is [n, m] aligned to the stack (the 186-14 writer loads the column from
    feature_vectors and aligns it like a feature; integer codes or strings). Returns the cells
    keyed by str(label) and the count of existing-row observations (traded bar, feature row
    present) with no label, which are counted, never assigned to a regime.

    `complete` maps each label to the family's row completeness over that label's rows
    (`ic.FamilyCompleteness`) when the features are one block of a larger family."""
    n, m = stack.targets.shape
    if regime_volatility.shape != (n, m):
        raise ValueError(f"regime_volatility {regime_volatility.shape} != stack grid {(n, m)}")
    masks, n_unlabelled = label_row_masks(
        existing_rows(stack.valid_grid(), present), regime_volatility
    )
    cells: dict[str, IcCell] = {}
    for label, mask in masks.items():
        X, y = observation_rows(features, stack.targets, mask)
        cells[label] = pooled_rank_ic(
            X,
            y,
            stride=stride(stack, params),
            params=params,
            feature_names=feature_names,
            complete=None if complete is None else complete[label],
        )
    return cells, n_unlabelled
