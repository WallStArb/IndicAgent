"""Frozen data passed between harness stages. No logic."""

from __future__ import annotations

import dataclasses

import numpy as np


@dataclasses.dataclass(frozen=True)
class StratumWeights:
    """One equity stratum's fitted weights, in selection order."""

    feature_names: list[str]
    weights: np.ndarray
    ic_signs: np.ndarray
    method_used: str
    effective_n: float


@dataclasses.dataclass(frozen=True)
class RefitOutput:
    refit_date: np.datetime64
    strata: dict[str, StratumWeights]  # equity label -> weights
    skipped: dict[str, str]  # equity label -> skip reason
    ic_rows: list[dict]
    n_embargo_excluded: int


@dataclasses.dataclass(frozen=True)
class GroupArrays:
    """1d rows sorted by (bar_ts, symbol), like ic_engine's chunk_sql."""

    symbols: np.ndarray
    bar_ts: np.ndarray  # datetime64[D]
    session_idx: np.ndarray  # int, index into Snapshot.sessions
    X: np.ndarray  # float32 [rows, len(_FEATURE_NAMES)], NULL -> NaN
    returns: np.ndarray  # [rows, n_scales]
    complete: np.ndarray  # bool [rows, n_scales]
    labels: np.ndarray  # this group's market_regimes label per row, "" if none


@dataclasses.dataclass(frozen=True)
class Snapshot:
    sessions: np.ndarray  # datetime64[D], NYSE sessions
    groups: dict[str, GroupArrays]  # regime group -> its routed symbols' rows
    all_1d: GroupArrays  # every 1d symbol, equity labels (the trainer's stratum X)
    sleeve_features: np.ndarray  # [n_sessions, n_sleeve, n_features], NULL -> NaN
    sleeve_has_row: np.ndarray  # bool [n_sessions, n_sleeve]
    sleeve_opens: np.ndarray  # [n_sessions, n_sleeve]
    sleeve_closes: np.ndarray  # [n_sessions, n_sleeve]
    equity_labels: np.ndarray  # [n_sessions], "" if none
    feature_names: list[str]
    broadcast_mask: np.ndarray  # bool over feature_names
    feature_to_group: dict[str, str]
    apr: dict[str, str]
    manifest: dict
