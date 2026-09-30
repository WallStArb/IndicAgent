"""Proposer job: pooled cross-sectional IC per feature x tf x horizon (D-17)."""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.measure.ic import IcCell, existing_rows, observation_rows, pooled_rank_ic
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import TargetStack, stride
from src.intelligence.statistics.ic_math import apply_bh_fdr


@dataclasses.dataclass(frozen=True)
class ProposerResult:
    """The pooled cell plus Benjamini-Hochberg across the features it holds."""

    cell: IcCell
    bh_adjusted_p: np.ndarray  # [k], NaN where the cell has no p-value
    passes_fdr: np.ndarray  # [k] bool


def propose_cell(
    features: np.ndarray,
    feature_names: tuple[str, ...],
    stack: TargetStack,
    params: MeasureParams,
    *,
    present: np.ndarray,
    complete: np.ndarray | None = None,
) -> IcCell:
    """One pooled IC cell over every existing row of `stack` for the feature block `features`
    [n, m, k] (aligned to stack.timestamps x stack.symbols). A row exists where the bar traded
    and the slot received a feature row (`present` [n, m], `SlotMap.present`), the rows ic_engine
    strides over. Stride is max(params.min_stride, horizon), the formula stored cells use.

    Features arrive in blocks the caller chooses; nothing here assumes the whole feature set fits
    in memory. A caller that blocks the family passes `complete`, the family's row completeness
    (`ic.FamilyCompleteness`), and applies `family_fdr` once over the merged cells: neither the
    cell values nor the FDR decisions then depend on the block size."""
    n, m = stack.targets.shape
    if features.shape[:2] != (n, m):
        raise ValueError(f"features {features.shape[:2]} do not match the stack grid {(n, m)}")
    X, y = observation_rows(features, stack.targets, existing_rows(stack.valid_grid(), present))
    return pooled_rank_ic(
        X,
        y,
        stride=stride(stack, params),
        params=params,
        feature_names=feature_names,
        complete=complete,
    )


def family_fdr(p_value: np.ndarray, fdr_alpha: float) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg over the finite p-values of ONE family: (adjusted p, rejected), NaN and
    False where a feature has no p-value.

    The family is every feature of one tf at the proposer horizon. ic_engine corrects one family
    per training window, all features, symbols, tfs, regimes and horizons together, over cluster
    representatives (services/ic_engine.py `_backfill_bh_fdr` 5570-5620, representatives
    3196-3240); the fresh writer has no clusters and runs one tf per unit, so its family is the
    tf's whole feature set, never a memory block of it."""
    adjusted = np.full(len(p_value), np.nan)
    passes = np.zeros(len(p_value), dtype=bool)
    has_p = np.isfinite(p_value)
    if has_p.any():
        reject, corrected = apply_bh_fdr(p_value[has_p].tolist(), fdr_alpha)
        adjusted[has_p], passes[has_p] = corrected, reject
    return adjusted, passes


def propose(
    features: np.ndarray,
    feature_names: tuple[str, ...],
    stack: TargetStack,
    params: MeasureParams,
    *,
    present: np.ndarray,
    complete: np.ndarray | None = None,
) -> ProposerResult:
    """`propose_cell` plus `family_fdr` over the features passed: the caller passes the whole
    family (one block). A caller that blocks the family calls the two parts itself."""
    cell = propose_cell(features, feature_names, stack, params, present=present, complete=complete)
    adjusted, passes = family_fdr(cell.p_value, params.fdr_alpha)
    return ProposerResult(cell=cell, bh_adjusted_p=adjusted, passes_fdr=passes)
