"""IC term structure: the proposer's cells across in-session horizons (D-17, D-18)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

import numpy as np

from src.intelligence.measure.ic import existing_rows, pooled_rank_ic_prepared, prepare_features
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import (
    check_horizon,
    stack_at_horizon,
    stack_grid,
    stride,
)
from src.intelligence.research.panel import Panel


@dataclasses.dataclass(frozen=True)
class TermStructure:
    features: tuple[str, ...]
    horizons: tuple[int, ...]
    ic: np.ndarray  # [k, H]
    n_obs: np.ndarray  # [k, H] strided valid pairs
    p_value: np.ndarray  # [k, H]
    peak_horizon: np.ndarray  # [k] horizon of max |ic|; 0 when no horizon has a finite IC


def term_structure(
    features: np.ndarray,
    feature_names: tuple[str, ...],
    panels: list[Panel],
    horizons: tuple[int, ...],
    end_exclusive: str,
    params: MeasureParams,
    *,
    present: np.ndarray,
    complete: np.ndarray | None = None,
) -> TermStructure:
    """The same pooled cells at each horizon, over the rows that exist (traded bar and a
    feature row, `present` [n, m] from `SlotMap.present`). Every horizon is checked before anything is
    computed; an intraday horizon that would leave the session is the caller's 1d run. `complete`
    is the family's row completeness when the features are one block of a larger family
    (`ic.FamilyCompleteness`)."""
    for horizon in horizons:
        check_horizon(panels[0].tf, panels[0].bars_per_session, horizon)
    k, n_h = len(feature_names), len(horizons)
    ic = np.full((k, n_h), np.nan)
    n_obs = np.zeros((k, n_h), dtype=np.int64)
    p_value = np.full((k, n_h), np.nan)
    # Nothing but the target depends on the horizon: the union grid, the rows that exist, the
    # masked feature copy and the per-column std and finite masks are built once, and each
    # horizon only ANDs its target's mask into them and takes its own stride.
    grid = stack_grid(panels, end_exclusive)
    n, m = len(grid.timestamps), len(grid.symbols)
    if features.shape[:2] != (n, m):
        raise ValueError(f"features {features.shape[:2]} do not match the stack grid {(n, m)}")
    rows = np.flatnonzero(existing_rows(grid.valid_grid(), present).reshape(n * m))
    prepared = prepare_features(
        features.reshape(n * m, features.shape[2])[rows], params, feature_names, complete=complete
    )
    for h_idx, horizon in enumerate(horizons):
        stack = stack_at_horizon(grid, panels, horizon)
        cell = pooled_rank_ic_prepared(
            prepared,
            stack.targets.reshape(n * m)[rows],
            stride=stride(stack, params),
            params=params,
        )
        ic[:, h_idx], n_obs[:, h_idx], p_value[:, h_idx] = cell.ic, cell.n_independent, cell.p_value
    magnitude = np.where(np.isfinite(ic), np.abs(ic), -np.inf)
    best = np.argmax(magnitude, axis=1)
    has_any = np.isfinite(ic).any(axis=1)
    peak = np.where(has_any, np.asarray(horizons)[best], 0)
    return TermStructure(
        features=tuple(feature_names),
        horizons=tuple(horizons),
        ic=ic,
        n_obs=n_obs,
        p_value=p_value,
        peak_horizon=peak,
    )


def merge_term_structures(parts: Sequence[TermStructure]) -> TermStructure:
    """The term structures of feature blocks over the same horizons as one, features in block
    order."""
    if not parts:
        raise ValueError("no term structures to merge")
    if len({p.horizons for p in parts}) != 1:
        raise ValueError("term structures disagree on the horizons")
    return TermStructure(
        features=tuple(f for p in parts for f in p.features),
        horizons=parts[0].horizons,
        ic=np.concatenate([p.ic for p in parts]),
        n_obs=np.concatenate([p.n_obs for p in parts]),
        p_value=np.concatenate([p.p_value for p in parts]),
        peak_horizon=np.concatenate([p.peak_horizon for p in parts]),
    )
