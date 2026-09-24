"""S1: one walk-forward refit, production statistics on point-in-time rows.

Pre-registration sections 4.2 and 6. For refit date T_k this runs, in production order:
pooled 1d IC cells for every enabled regime group (amendment A1) through ic_engine's own cell
functions, cluster representatives, one BH pass over this refit's representatives (D1), IC
shrinkage over this refit's rows (D7), the trainer's meta-FDR and eligibility rules, then
stratum_fit's selection and weight fit for each equity label. Nothing is copied.

Imported private production symbols (debt owned by todo 214): ic_engine._compute_one_cross_
sectional_cell, _compute_one_broadcast_cell, _mark_cluster_representatives,
_derive_worker_rng_seed, _FEATURE_NAMES, _CROSS_SECTIONAL_SYMBOL; ensemble_trainer._meta_eligible,
_resolve_ic_input_column; ConfigService._cache/_parse_value (the same cache-only load
_batch_utils.load_config_service_sync does, without its DB cursor). Those production modules
are deliberately not edited: ic_engine fingerprints every module it imports.

Embargo (V6): a row at session t trains scale h only if its exit open t+h+1 falls on or before
the session `embargo` sessions before T_k; rows past the h=1 cutoff are dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from scripts.analysis.sleeve_walk_forward.results import (
    GroupArrays,
    RefitOutput,
    Snapshot,
    StratumWeights,
)
from scripts.analysis.sleeve_walk_forward.sessions import label_cutoff
from scripts.ops.alpha.ops_ic_shrinkage import compute_shrinkage_updates
from services import ic_engine
from services._batch_utils import resolve_per_tf
from services.ensemble_trainer import EnsembleConfig, _meta_eligible, _resolve_ic_input_column
from src.config.config_service import ConfigService
from src.intelligence.ensemble.stratum_fit import fit_stratum_weights, select_stratum
from src.intelligence.statistics.ic_math import apply_bh_fdr

_TF = "1d"
_ZERO_WEIGHT = 1e-10


def ic_engine_config(apr: dict[str, tuple[str, str]]) -> ic_engine.ICEngineConfig:
    svc = ConfigService(database_url="")
    for key, (value, value_type) in apr.items():
        svc._cache[key] = svc._parse_value(value, value_type)
    return ic_engine.ICEngineConfig.from_apr(svc)


def raw_apr(apr: dict[str, tuple[str, str]]) -> dict[str, str]:
    """The trainer's view: raw config_value text by key."""
    return {key: value for key, (value, _t) in apr.items()}


def eligible(row: dict, sign_symmetric: bool, *, require_fdr: bool = True) -> bool:
    """ensemble_trainer._eligibility_where in Python, SQL NULL semantics (None fails every
    comparison). require_fdr=False is the base clause the meta-FDR denominator uses."""

    def gt0(v: Any) -> bool:
        return v is not None and v > 0

    def lt0(v: Any) -> bool:
        return v is not None and v < 0

    if sign_symmetric:
        significant = (row["ic_sign"] == 1 and gt0(row["ic_ci_lower"])) or (
            row["ic_sign"] == -1 and lt0(row["ic_ci_upper"])
        )
    else:
        significant = gt0(row["ic_ci_lower"])
    base = (
        row["symbol"] == ic_engine._CROSS_SECTIONAL_SYMBOL
        and row["is_pooled"] is True
        and row["regime"] is not None
        and row["regime"] != "_pooled"
        and row["regime_scope"] is not None
        and row["regime_scope"] != "earnings_season"
        and significant
        and row["reliable"] is True
        and row["ic_sharpe_hac"] is not None
        and row["passes_walkforward"] is True
    )
    return base and (not require_fdr or row["passes_fdr"] is True)


def training_arrays(
    group: GroupArrays, cutoff: int, lookaheads: list[int], start_idx: int, refit_idx: int
) -> tuple[np.ndarray, np.ndarray, int]:
    """(row mask, complete matrix, n_embargo_excluded) for one group at one refit.
    n_embargo_excluded counts (row, scale) labels the embargo removed: scales cut from kept rows,
    plus every scale of rows between the h=1 cutoff and the refit date."""
    t = group.session_idx
    in_span = (t >= start_idx) & (t < refit_idx)
    keep = in_span & (t + lookaheads[0] + 1 <= cutoff)
    exits_ok = np.stack([t[keep] + h + 1 <= cutoff for h in lookaheads], axis=1)
    complete = group.complete[keep] & exits_ok
    dropped = in_span & ~keep
    n_excluded = int((group.complete[keep] & ~exits_ok).sum() + group.complete[dropped].sum())
    return keep, complete, n_excluded


def assert_embargo(t: np.ndarray, lookaheads: list[int], complete: np.ndarray, cutoff: int) -> None:
    """V6: every label a refit trains on exits on or before the cutoff session."""
    if list(lookaheads) != sorted(lookaheads):
        raise AssertionError(f"V6: lookaheads must be ascending, got {lookaheads}")
    exits = t[:, None] + np.asarray(lookaheads)[None, :] + 1
    late = complete & (exits > cutoff)
    if late.any():
        raise AssertionError(
            f"V6: {int(late.sum())} training labels exit after cutoff session {cutoff}"
        )


def run_refit(
    snapshot: Snapshot,
    refit_date: np.datetime64,
    cfg: HarnessConfig,
    excluded: frozenset[str],
    controls: frozenset[str] = frozenset(),
    fidelity_window_end: np.datetime64 | None = None,
) -> RefitOutput:
    """excluded: removed before measurement (no IC rows). controls: measured like any feature
    (their rows feed V5 and the BH family, as in production) but never selected or weighted.
    fidelity_window_end (V4 only): train the way production's corpus run does, on every bar
    up to that window end with the stored completeness flags and no embargo, so the rows can be
    compared with production's feature_ic_scores. Never used for an out-of-sample refit."""
    config = ic_engine_config(snapshot.apr)
    raw = raw_apr(snapshot.apr)
    ens = EnsembleConfig.from_apr(raw)
    lookaheads = [config.lookaheads_for(_TF)[s] for s in ("fast", "mid", "slow", "extended")]
    cutoff = label_cutoff(snapshot.sessions, refit_date, cfg.embargo_sessions)
    refit_idx = cutoff + cfg.embargo_sessions
    start_idx = int(np.searchsorted(snapshot.sessions, np.datetime64(cfg.training_start)))
    window_end = (
        snapshot.sessions[cutoff - lookaheads[0] - 1]
        if fidelity_window_end is None
        else fidelity_window_end
    )
    run_ts = datetime.fromisoformat(str(refit_date)).replace(tzinfo=UTC)
    excluded_mask = np.array([f in excluded for f in snapshot.feature_names])
    cs_mask = snapshot.broadcast_mask | excluded_mask
    bc_mask = snapshot.broadcast_mask & ~excluded_mask

    rows: list[dict] = []
    pvals: list[float] = []
    rep_idx: list[int] = []
    n_embargo_excluded = 0
    for group_name in sorted(snapshot.groups):
        group = snapshot.groups[group_name]
        if fidelity_window_end is None:
            keep, complete, n_excl = training_arrays(
                group, cutoff, lookaheads, start_idx, refit_idx
            )
            assert_embargo(group.session_idx[keep], lookaheads, complete, cutoff)
        else:
            keep = (group.session_idx >= start_idx) & (group.bar_ts <= fidelity_window_end)
            complete, n_excl = group.complete[keep], 0
        n_embargo_excluded += n_excl
        if fidelity_window_end is None and keep.any() and group.bar_ts[keep].max() >= refit_date:
            raise AssertionError(f"V6: {group_name} training row on or after {refit_date}")
        labels = group.labels[keep]
        X_kept, returns_kept, bar_ts_kept = group.X[keep], group.returns[keep], group.bar_ts[keep]
        for label in sorted({x for x in labels if x}):
            m = labels == label
            X_raw = np.ascontiguousarray(X_kept[m], dtype=np.float32)
            returns_mat = returns_kept[m]
            complete_mat = complete[m]
            rng = np.random.default_rng(
                ic_engine._derive_worker_rng_seed(
                    f"{refit_date}|{group_name}|{label}", config.bootstrap_seed
                )
            )
            common = dict(
                X_raw=X_raw,
                returns_mat=returns_mat,
                complete_mat=complete_mat,
                config=config,
                tf=_TF,
                rng=rng,
                training_window_end=window_end,
                run_ts=run_ts,
            )
            cell, _ = ic_engine._compute_one_cross_sectional_cell(
                label, prior_e_values={}, broadcast_mask=cs_mask, **common
            )
            bcell, _ = ic_engine._compute_one_broadcast_cell(
                label, bar_ts_arr=bar_ts_kept[m], broadcast_mask=bc_mask, **common
            )
            cell_rows = cell + bcell
            cell_pvals: list[float] = []
            cell_idx: list[int] = []
            ic_engine._mark_cluster_representatives(cell_rows, cell_pvals, cell_idx)
            pvals += cell_pvals
            rep_idx += [len(rows) + i for i in cell_idx]
            rows += cell_rows

    if pvals:
        reject, p_corr = apply_bh_fdr(pvals, alpha=config.fdr_alpha)
        for i, idx in enumerate(rep_idx):
            rows[idx]["bh_adjusted_p"] = float(p_corr[i])
            rows[idx]["passes_fdr"] = bool(reject[i])

    _apply_shrinkage(rows, snapshot.feature_to_group, raw)
    meta = _meta_eligible(
        _fdr_pass_rows(rows, ens.sign_symmetric),
        raw,
        ens.meta_fdr_min_fraction,
        ens.meta_fdr_min_cells,
    ).get(_TF, set())
    strata, skipped = _fit_equity_strata(
        snapshot, rows, meta, excluded | controls, ens, raw, refit_date
    )
    return RefitOutput(refit_date, strata, skipped, rows, n_embargo_excluded)


def _apply_shrinkage(rows: list[dict], feature_to_group: dict[str, str], raw: dict) -> None:
    candidates = [
        r
        for r in rows
        if r["reliable"] is True
        and r["ic_sharpe_hac"] is not None
        and r["regime_scope"] != "earnings_season"
    ]
    k = float(raw.get("alpha.ic.shrinkage_k", "100"))
    updates = compute_shrinkage_updates(candidates, feature_to_group, k)
    by_key = {(u[2], u[3], u[5], u[6]): (u[0], u[1]) for u in updates}
    for r in rows:
        r["ic_shrunk"], r["shrinkage_weight"] = by_key.get(
            (r["feature_name"], r["symbol"], r["regime"], r["lookahead_bars"]), (None, None)
        )


def _fdr_pass_rows(rows: list[dict], sign_symmetric: bool) -> list[dict]:
    """The trainer's meta-FDR SQL: per feature, share of base-eligible rows with passes_fdr."""
    counts: dict[str, list[int]] = {}
    for r in rows:
        if eligible(r, sign_symmetric, require_fdr=False):
            c = counts.setdefault(r["feature_name"], [0, 0])
            c[0] += r["passes_fdr"] is True
            c[1] += 1
    return [
        {"feature_name": f, "tf": _TF, "fdr_pass_rate": p / n, "n_cells": n}
        for f, (p, n) in counts.items()
    ]


def _fit_equity_strata(
    snapshot: Snapshot,
    rows: list[dict],
    meta: set[str],
    excluded: frozenset[str],
    ens: EnsembleConfig,
    raw: dict,
    refit_date: np.datetime64,
) -> tuple[dict[str, StratumWeights], dict[str, str]]:
    ic_col = _resolve_ic_input_column(ens.ic_input)
    min_features = resolve_per_tf(
        raw, "alpha.ensemble.min_passing_features", _TF, ens.min_passing_features
    )
    max_weight = resolve_per_tf(
        raw, "alpha.ensemble.max_feature_weight", _TF, ens.max_feature_weight
    )
    fit_rows = snapshot.all_1d.bar_ts < refit_date
    strata: dict[str, StratumWeights] = {}
    skipped: dict[str, str] = {}
    equity_labels = sorted({x for x in snapshot.groups["equity"].labels if x})
    for label in equity_labels:
        ic_rows = [
            r
            for r in rows
            if r["regime"] == label
            and eligible(r, ens.sign_symmetric)
            and r["feature_name"] in meta
            and r["feature_name"] not in excluded
            and (ic_col != "ic_shrunk" or r["ic_shrunk"] is not None)
        ]
        if not ic_rows:
            skipped[label] = "no_ic_rows"
            continue
        selection, reason, _n = select_stratum(
            ic_rows,
            ic_input_column=ic_col,
            sharpe_floor=ens.sharpe_floor,
            feature_cols=snapshot.feature_names,
            min_passing_features=min_features,
        )
        if selection is None:
            skipped[label] = reason
            continue
        m = fit_rows & (snapshot.all_1d.labels == label)
        cols = [snapshot.feature_names.index(f) for f in selection.feature_names]
        X = np.nan_to_num(snapshot.all_1d.X[m][:, cols]).astype(np.float32)
        fit = fit_stratum_weights(
            selection,
            X,
            list(snapshot.all_1d.bar_ts[m]),
            weight_method=ens.weight_method,
            max_feature_weight=max_weight,
            max_cluster_corr=ens.max_cluster_corr,
            max_cluster_weight=ens.max_cluster_weight,
            mv_condition_max=ens.mv_condition_max,
        )
        if fit.n_fit_rows < 2:
            skipped[label] = "insufficient_fit_bars"
            continue
        if float(fit.result.weights.sum()) < _ZERO_WEIGHT:
            skipped[label] = "zero_weight_vector"
            continue
        strata[label] = StratumWeights(
            selection.feature_names,
            fit.result.weights,
            selection.ic_signs,
            fit.result.method_used,
            fit.effective_n,
        )
    return strata, skipped
