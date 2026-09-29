"""IC term structure: the proposer's cells across in-session horizons (D-17, D-18)."""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.proposer import propose
from src.intelligence.measure.targets import check_horizon, stack_targets
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
) -> TermStructure:
    """The same pooled cells at each horizon. Every horizon is checked before anything is
    computed; an intraday horizon that would leave the session is the caller's 1d run."""
    for horizon in horizons:
        check_horizon(panels[0].tf, panels[0].bars_per_session, horizon)
    k, n_h = len(feature_names), len(horizons)
    ic = np.full((k, n_h), np.nan)
    n_obs = np.zeros((k, n_h), dtype=np.int64)
    p_value = np.full((k, n_h), np.nan)
    for h_idx, horizon in enumerate(horizons):
        stack = stack_targets(panels, horizon, end_exclusive)
        cell = propose(features, feature_names, stack, params).cell
        ic[:, h_idx], n_obs[:, h_idx], p_value[:, h_idx] = cell.ic, cell.n_independent, cell.p_value
    magnitude = np.where(np.isfinite(ic), np.abs(ic), -np.inf)
    best = np.argmax(magnitude, axis=1)
    has_any = np.isfinite(ic).any(axis=1)
    peak = np.where(has_any, np.asarray(horizons)[best], 0)
    return TermStructure(
        features=feature_names,
        horizons=horizons,
        ic=ic,
        n_obs=n_obs,
        p_value=p_value,
        peak_horizon=peak,
    )
