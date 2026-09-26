"""The evidence record (evidence framework section 5, D-09, methodology-change-ledger E16, E17).

The decision block is the E17 statistic: the one-sided HAC t of the timing P&L (weights against
returns net of the memory-lagged cell mean), the memory L and history floor it used, its mean, HAC standard error, p, lag and session count, and
its annualized Sharpe. The shift-null readout (excess Sharpe over the null median, bootstrap
interval, permutation p, per-period estimates, shape) is kept as a diagnostic block. Also:
power (None for an evidence run, D-21), coverage, turnover and a cost band, the resolution
time the decision Sharpe implies, the hashes and the guard summary. No token: an evidence run
gates nothing. A book test adds its screen outcome (decision p against alpha / M).

Turnover and the cost band are diagnostics only, never a gate (standing directive; family 1
prereg section 4). Every value goes through ledger.jsonable, so NaN becomes null and numpy
types become plain Python.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

from src.intelligence.research.evaluate import SESSIONS_PER_YEAR, EvaluationResult
from src.intelligence.research.guards import IntegrityReport
from src.intelligence.research.ledger import jsonable
from src.intelligence.research.spec import CostSpec
from src.intelligence.research.timing import TimingResult

SCHEMA = "research_evidence_v3"  # v3: E17 decision statistic (v2: E16), shift null diagnostic
_BPS = 1e-4  # one basis point


def resolution_years(estimate: float | None) -> float | None:
    """Years of data for 80% power at one-sided 0.05 on an annualized excess Sharpe
    (evidence framework section 2): ((z_0.95 + z_0.80) / e)^2. None unless e is finite and > 0."""
    if estimate is None or not math.isfinite(estimate) or estimate <= 0:
        return None
    return float(((norm.ppf(0.95) + norm.ppf(0.80)) / estimate) ** 2)


def turnover_per_session(
    weights: np.ndarray, has_position: np.ndarray, trade: np.ndarray, bars_per_session: int
) -> float:
    """Mean traded notional per scored session. Each row's book is opened and closed within
    its horizon, so a row with a position trades 2 * sum_i |w[t, i]|; rows are summed per
    session and averaged over the sessions that have any scored row."""
    per_row = np.where(has_position & trade, 2.0 * np.abs(weights).sum(axis=1), 0.0)
    per_session = per_row.reshape(-1, bars_per_session).sum(axis=1)
    scored = trade.reshape(-1, bars_per_session).any(axis=1)
    return float(per_session[scored].mean()) if scored.any() else float("nan")


def coverage_summary(report: IntegrityReport, alpha: np.ndarray, trade: np.ndarray) -> dict:
    """Coverage over scored rows where any alpha is finite."""
    rows = trade & np.isfinite(alpha).any(axis=1)
    cov = report.coverage[rows]
    cov = cov[np.isfinite(cov)]
    return {
        "mean": float(cov.mean()) if cov.size else None,
        "p05": float(np.percentile(cov, 5)) if cov.size else None,
        "min": float(cov.min()) if cov.size else None,
        "rows_with_position": int(rows.sum()),
        "mean_finite_names": (
            float(np.isfinite(alpha[rows]).sum(axis=1).mean()) if rows.any() else None
        ),
    }


def _shift_null(res: EvaluationResult | None, n_shifts: int, sub_periods) -> dict | None:
    """The shift-null readout, a diagnostic since E16 (None when no shift was admissible)."""
    if res is None:
        return None
    return {
        "estimate": float(res.excess[0]),
        "bootstrap_se": None if res.excess_se is None else float(res.excess_se[0]),
        "bootstrap_ci": res.excess_ci[0],
        "permutation_p": float(res.adjusted_p[0]),
        "sharpe_observed": float(res.sharpe_obs[0]),
        "null_median_sharpe": float(np.median(res.sharpe_null[:, 0])),
        "per_period": [
            {"start": a, "end": b, "mean_session_excess": res.sub_period_excess[0, j]}
            for j, (a, b) in enumerate(sub_periods)
        ],
        "shape": res.diagnostics,
        "n_shifts": n_shifts,
    }


def evidence_record(
    timing: TimingResult,
    shift_null: EvaluationResult | None,
    *,
    kind: str,
    subject: str,
    n_shifts: int,
    power: dict | None,
    coverage: dict,
    turnover: float,
    costs: CostSpec,
    hashes: dict,
    guards: dict,
    sub_periods,
    screen: dict | None = None,
) -> dict:
    """The E17 record: the decision statistic is the HAC timing t; the shift null is kept as
    a diagnostic block."""
    h = timing.hac
    record = {
        "schema": SCHEMA,
        "kind": kind,
        "subject": subject,
        "decision": {
            "statistic": "hac_timing_t_e17",
            "memory_sessions": timing.memory_sessions,
            "min_history_sessions": timing.min_history_sessions,
            "mean_session_pnl": h.mean,
            "se": h.se,
            "t": h.t,
            "p": h.p,
            "lag": h.lag,
            "n_sessions": h.n,
            "warmup_sessions": timing.warmup_sessions,
            "annualized_sharpe": timing.annualized_sharpe,
        },
        "shift_null": _shift_null(shift_null, n_shifts, sub_periods),
        "power": power,
        "coverage": coverage,
        "turnover_per_session": turnover,
        "cost_band": {
            "bps_low": costs.bps_low,
            "bps_high": costs.bps_high,
            "annual_drag_low": turnover * costs.bps_low * _BPS * SESSIONS_PER_YEAR,
            "annual_drag_high": turnover * costs.bps_high * _BPS * SESSIONS_PER_YEAR,
            "diagnostic_only": True,
        },
        "resolution_years_80pct_power": resolution_years(timing.annualized_sharpe),
        "hashes": hashes,
        "guards": guards,
    }
    if screen is not None:
        record["screen"] = screen
    return jsonable(record)
