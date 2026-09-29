"""Proposer job: pooled cross-sectional IC per feature x tf x horizon (D-17)."""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.measure.ic import IcCell, observation_rows, pooled_rank_ic
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import TargetStack
from src.intelligence.statistics.ic_math import apply_bh_fdr


@dataclasses.dataclass(frozen=True)
class ProposerResult:
    """The pooled cell plus Benjamini-Hochberg across the block's features."""

    cell: IcCell
    bh_adjusted_p: np.ndarray  # [k], NaN where the cell has no p-value
    passes_fdr: np.ndarray  # [k] bool


def propose(
    features: np.ndarray,
    feature_names: tuple[str, ...],
    stack: TargetStack,
    params: MeasureParams,
) -> ProposerResult:
    """One pooled IC cell over every valid row of `stack` for the feature block `features`
    [n, m, k] (aligned to stack.timestamps x stack.symbols). Stride is
    max(params.min_stride, horizon), the formula stored cells use. Features arrive in blocks the
    caller chooses; nothing here assumes the whole feature set fits in memory."""
    n, m = stack.targets.shape
    if features.shape[:2] != (n, m):
        raise ValueError(f"features {features.shape[:2]} do not match the stack grid {(n, m)}")
    row_mask = np.broadcast_to(stack.valid[:, None], (n, m))
    X, y = observation_rows(features, stack.targets, row_mask)
    cell = pooled_rank_ic(
        X,
        y,
        stride=max(params.min_stride, stack.horizon),
        params=params,
        feature_names=feature_names,
    )
    adjusted = np.full(len(cell.ic), np.nan)
    passes = np.zeros(len(cell.ic), dtype=bool)
    has_p = np.isfinite(cell.p_value)
    if has_p.any():
        reject, corrected = apply_bh_fdr(cell.p_value[has_p].tolist(), params.fdr_alpha)
        adjusted[has_p], passes[has_p] = corrected, reject
    return ProposerResult(cell=cell, bh_adjusted_p=adjusted, passes_fdr=passes)
