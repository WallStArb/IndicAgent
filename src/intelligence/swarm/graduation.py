"""graduation.py -- Pure-function validation module for alpha modifier graduation.

Single source of truth for graduation gate constants and Renaissance compute
functions. Used by both GraduationComputeAgent (always-on) and
scripts/validate_skeptic.py (on-demand CLI).

DataFrame input contract: columns ``multiplier`` (float) and ``pnl_r`` (float).
High multiplier = high confidence = expected positive pnl_r.

Note on sign: ``validate_skeptic.py`` uses ``failure_probability`` (high = bad).
This module uses ``multiplier`` (high = good). Gate signs are flipped accordingly.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pandas as pd
from scipy.stats import norm, spearmanr

# ---------------------------------------------------------------------------
# Gate constants (LOCKED — exact values; no modifications without plan approval)
# ---------------------------------------------------------------------------

GATE_SPEARMAN_RHO = 0.15  # positive: high multiplier → high pnl_r
GATE_CALIBRATION_MAX_ERROR = 0.10
GATE_CVAR_BOTTOM_DECILE = -0.5
GATE_SEGMENT_MIN_N = 30
GATE_SEGMENT_RHO = 0.15
GATE_SEGMENT_POWER = 0.80
EVAL_RESOLUTION_THRESHOLD = 20
EVAL_ROLLING_WINDOW_DAYS = 90
EVAL_EXPIRY_DAYS = 90
EVAL_WALK_FORWARD_FRACTION = 0.7

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ANNUALISATION = math.sqrt(252)


def _sharpe(returns: pd.Series) -> float:
    """Annualised Sharpe ratio. Returns 0.0 if fewer than 2 obs or zero std."""
    if len(returns) < 2:
        return 0.0
    std = float(returns.std())
    if std == 0.0:
        return 0.0
    return float(returns.mean() / std * _ANNUALISATION)


# ---------------------------------------------------------------------------
# Compute functions (LOCKED signatures)
# ---------------------------------------------------------------------------


def compute_spearman(df: pd.DataFrame) -> dict:
    """Spearman rank correlation between ``multiplier`` and ``pnl_r``.

    Returns:
        dict with keys ``rho``, ``p_value``, ``n``, ``pass``.
        ``pass`` is True iff rho >= GATE_SPEARMAN_RHO and n >= 10.
    """
    valid = df.dropna(subset=["multiplier", "pnl_r"])
    n = len(valid)
    if n < 10:
        return {"rho": float("nan"), "p_value": float("nan"), "n": n, "pass": False}

    rho, p_value = spearmanr(valid["multiplier"].values, valid["pnl_r"].values)
    rho = float(rho)
    p_value = float(p_value)
    passes = rho >= GATE_SPEARMAN_RHO and n >= 10
    return {"rho": rho, "p_value": p_value, "n": n, "pass": passes}


def compute_calibration(df: pd.DataFrame) -> pd.DataFrame:
    """Calibration table: predicted failure vs actual failure rate per decile.

    Deciles are based on ``multiplier`` (low multiplier = high expected failure).
    ``avg_predicted_failure`` = 1 - mean(multiplier) per decile.
    ``actual_failure_rate`` = fraction of rows with pnl_r <= 0 per decile.

    Returns an empty DataFrame if n < 30.
    """
    valid = df.dropna(subset=["multiplier", "pnl_r"])
    if len(valid) < 30:
        return pd.DataFrame(
            columns=[
                "decile",
                "n",
                "avg_predicted_failure",
                "actual_failure_rate",
                "avg_pnl_r",
                "calibration_error",
            ]
        )

    valid = valid.copy()
    valid["decile"] = pd.qcut(valid["multiplier"], q=10, labels=False, duplicates="drop")

    rows = []
    for decile, group in valid.groupby("decile"):
        n_d = len(group)
        avg_mult = float(group["multiplier"].mean())
        avg_predicted_failure = 1.0 - avg_mult
        actual_failure_rate = float((group["pnl_r"] <= 0).mean())
        avg_pnl_r = float(group["pnl_r"].mean())
        calibration_error = abs(avg_predicted_failure - actual_failure_rate)
        rows.append(
            {
                "decile": int(decile),
                "n": n_d,
                "avg_predicted_failure": avg_predicted_failure,
                "actual_failure_rate": actual_failure_rate,
                "avg_pnl_r": avg_pnl_r,
                "calibration_error": calibration_error,
            }
        )

    return pd.DataFrame(rows)


def compute_expected_shortfall(df: pd.DataFrame) -> dict:
    """CVaR of the bottom decile of multiplier.

    Bottom decile = lowest multiplier values (worst-rated by the transform).
    Gate passes iff the mean pnl_r of that bottom decile <= GATE_CVAR_BOTTOM_DECILE.

    Returns:
        dict with keys ``cvar``, ``n_tail``, ``pass``.
    """
    valid = df.dropna(subset=["multiplier", "pnl_r"])
    if len(valid) < 10:
        return {"cvar": float("nan"), "n_tail": 0, "pass": False}

    threshold = valid["multiplier"].quantile(0.10)
    tail = valid[valid["multiplier"] <= threshold]
    if tail.empty:
        return {"cvar": float("nan"), "n_tail": 0, "pass": False}

    cvar = float(tail["pnl_r"].mean())
    passes = cvar <= GATE_CVAR_BOTTOM_DECILE
    return {"cvar": cvar, "n_tail": len(tail), "pass": passes}


def compute_segment_power(n: int, alpha: float = 0.05, power: float = 0.80) -> float:
    """Minimum detectable Spearman |rho| (MDE) for given n, alpha, power.

    Uses the Fisher z-transform approximation. Returns float('inf') if n < 10.

    Args:
        n: Number of observations.
        alpha: Type-I error rate (two-tailed). Default 0.05.
        power: Desired statistical power. Default 0.80.

    Returns:
        Minimum detectable effect size as a positive float, or inf.
    """
    if n < 10:
        return float("inf")

    z_alpha = norm.ppf(1.0 - alpha / 2.0)
    z_beta = norm.ppf(power)
    # Required z_delta under Fisher transform
    sigma = 1.0 / math.sqrt(n - 3)
    z_effect = (z_alpha + z_beta) * sigma
    # Convert Fisher z back to Spearman rho
    mde = math.tanh(z_effect)
    return float(mde)


def compute_walk_forward(
    df: pd.DataFrame, train_fraction: float = EVAL_WALK_FORWARD_FRACTION
) -> dict:
    """Temporal walk-forward validation: train on first fraction, validate on rest.

    DataFrame is sorted by ``ts`` column before splitting.

    Returns:
        dict with keys ``train_n``, ``val_n``, ``train_rho``, ``val_rho``,
        ``val_passes``, ``overfitting``.
    """
    valid = df.dropna(subset=["multiplier", "pnl_r"]).sort_values("ts").reset_index(drop=True)
    n = len(valid)
    if n < 10:
        return {
            "train_n": 0,
            "val_n": 0,
            "train_rho": float("nan"),
            "val_rho": float("nan"),
            "val_passes": False,
            "overfitting": False,
        }

    split = int(n * train_fraction)
    train = valid.iloc[:split]
    val = valid.iloc[split:]

    def _rho(part: pd.DataFrame) -> float:
        if len(part) < 3:
            return float("nan")
        r, _ = spearmanr(part["multiplier"].values, part["pnl_r"].values)
        return float(r)

    train_rho = _rho(train)
    val_rho = _rho(val)
    val_passes = (not math.isnan(val_rho)) and val_rho >= GATE_SPEARMAN_RHO
    # Overfitting heuristic: train much better than val
    overfitting = (
        not math.isnan(train_rho) and not math.isnan(val_rho) and (train_rho - val_rho) > 0.20
    )
    return {
        "train_n": len(train),
        "val_n": len(val),
        "train_rho": train_rho,
        "val_rho": val_rho,
        "val_passes": val_passes,
        "overfitting": overfitting,
    }


def compute_value_add(df: pd.DataFrame) -> dict:
    """Compare Sharpe ratio of all trades vs high-confidence subset.

    Filter: multiplier > 0.5 (high-confidence keepers).
    ``pass`` is True iff sharpe_filtered > sharpe_all (delta > 0).

    Returns:
        dict with keys ``sharpe_all``, ``sharpe_filtered``, ``n_filtered``,
        ``delta``, ``pass``.
    """
    valid = df.dropna(subset=["multiplier", "pnl_r"])
    sharpe_all = _sharpe(valid["pnl_r"])
    filtered = valid[valid["multiplier"] > 0.5]
    sharpe_filtered = _sharpe(filtered["pnl_r"])
    delta = sharpe_filtered - sharpe_all
    return {
        "sharpe_all": sharpe_all,
        "sharpe_filtered": sharpe_filtered,
        "n_filtered": len(filtered),
        "delta": delta,
        "pass": delta > 0,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def evaluate_all(
    df: pd.DataFrame,
    transform_id: str,
    transform_version: str = "v1",
    segment_key: str = "__global__",
) -> dict:
    """Run all 6 validation functions and return a GraduationResult payload dict.

    Keys returned match the ``transform_graduation`` schema exactly.

    Args:
        df: DataFrame with columns ``multiplier``, ``pnl_r``, ``ts``.
        transform_id: Identifier for the transform being evaluated.
        transform_version: Semver/label for the transform variant. Default "v1".
        segment_key: Segment identifier (e.g. "trend.5m"). Default "__global__".

    Returns:
        dict matching the GraduationResult Kafka payload schema.
    """
    now = datetime.now(UTC)
    expires = now + timedelta(days=EVAL_EXPIRY_DAYS)
    evaluated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = expires.strftime("%Y-%m-%dT%H:%M:%SZ")

    valid = df.dropna(subset=["multiplier", "pnl_r"])
    n = len(valid)

    spearman = compute_spearman(df)
    calibration_df = compute_calibration(df)
    shortfall = compute_expected_shortfall(df)
    wf = compute_walk_forward(df)
    value_add = compute_value_add(df)

    # Calibration max error (None if insufficient data)
    calibration_max_error: float | None = None
    if not calibration_df.empty:
        calibration_max_error = float(calibration_df["calibration_error"].max())

    # MDE for segment power
    mde: float | None = None
    mde_val = compute_segment_power(n)
    if mde_val != float("inf"):
        mde = mde_val

    # Graduation: all gates must pass
    spearman_pass = spearman.get("pass", False)
    calibration_pass = (
        calibration_max_error is not None and calibration_max_error < GATE_CALIBRATION_MAX_ERROR
    )
    cvar_pass = shortfall.get("pass", False)
    wf_val_pass = wf.get("val_passes", False)
    value_add_pass = value_add.get("pass", False)
    is_graduated = bool(
        spearman_pass and calibration_pass and cvar_pass and wf_val_pass and value_add_pass
    )

    spearman_rho = spearman.get("rho")
    spearman_p = spearman.get("p_value")
    cvar_bottom = shortfall.get("cvar")
    val_rho = wf.get("val_rho")
    sharpe_delta = value_add.get("delta")

    def _nan_to_none(v: float | None) -> float | None:
        return None if (v is not None and math.isnan(v)) else v

    return {
        "transform_id": transform_id,
        "transform_version": transform_version,
        "segment_key": segment_key,
        "n": n,
        "spearman_rho": _nan_to_none(spearman_rho),
        "spearman_p": _nan_to_none(spearman_p),
        "calibration_max_error": calibration_max_error,
        "cvar_bottom_decile": _nan_to_none(cvar_bottom),
        "mde": mde,
        "val_rho": _nan_to_none(val_rho),
        "overfitting_risk": bool(wf.get("overfitting", False)),
        "sharpe_delta": _nan_to_none(sharpe_delta),
        "is_graduated": is_graduated,
        "evaluated_at": evaluated_at,
        "expires_at": expires_at,
    }
