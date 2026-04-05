# src/intelligence/metrics/validator.py
"""Data quality validation for signal_ledger rows before metrics computation.

Four gates applied in order — first failure short-circuits.
NULL pnl_r (zone never activated) passes validation; it is excluded from
performance metrics but counted toward never_activated_pct.

Never modifies raw signal_ledger rows. Invalid rows are logged to
signal_metrics_dq_failures by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass

# ES/NQ minimum tick size in points. Signals with |entry - stop| < this
# produce pnl_r blowups (CVDDivergence -496 Sharpe bug).
MIN_TICK_SIZE: float = 0.25

# Signals with |pnl_r| > this are data anomalies, not market moves.
# 10R in a single trade requires price to move 10x the initial risk — possible
# only with near-zero stops, which Gate 2 should catch first.
MAX_VALID_R: float = 10.0


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    reason_code: str | None  # None when valid


_VALID = ValidationResult(is_valid=True, reason_code=None)


def validate_signal_row(
    direction: int | None,
    entry_price: float | None,
    stop_loss: float | None,
    pnl_r: float | None,
    hmm_regime_at_fire: int | None,
) -> ValidationResult:
    """Apply 4 data quality gates to a signal_ledger row.

    Call with zone-track fields (pnl_r, entry_price, stop_loss) for zone
    validation, or with market-track fields for market validation.

    Args:
        direction:         +1 (long) or -1 (short)
        entry_price:       signal entry price (entry_price column)
        stop_loss:         signal stop loss (stop_loss column)
        pnl_r:             realised P&L in R-multiples; None = never activated
        hmm_regime_at_fire: HMM state at signal fire time (0/1/2)

    Returns:
        ValidationResult(is_valid=True, reason_code=None) when valid.
    """
    # NULL pnl_r = zone never activated. Valid — not a DQ failure.
    if pnl_r is None:
        return _VALID

    # Gate 1: direction must be +1 or -1
    if direction not in (1, -1):
        return ValidationResult(is_valid=False, reason_code="invalid_direction")

    # Gate 2: risk must be at least one tick (prevents pnl_r blowup)
    if entry_price is None or stop_loss is None:
        return ValidationResult(is_valid=False, reason_code="risk_below_min_tick")
    if abs(entry_price - stop_loss) < MIN_TICK_SIZE:
        return ValidationResult(is_valid=False, reason_code="risk_below_min_tick")

    # Gate 3: pnl_r magnitude must be plausible
    if abs(pnl_r) > MAX_VALID_R:
        return ValidationResult(is_valid=False, reason_code="pnl_r_outlier")

    # Gate 4: regime must be known for regime-conditioned segmentation
    if hmm_regime_at_fire is None:
        return ValidationResult(is_valid=False, reason_code="missing_regime")

    return _VALID
