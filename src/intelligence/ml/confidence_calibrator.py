"""Confidence calibration — isotonic regression curves per (plugin_name, timeframe).

Called from weight_updater.py after run_weight_update() on the 30-min timer tick.
Independent failure domain: any exception is caught and logged; weight update completes.

Algorithm:
  - Query signal_ledger for resolved non-shadow signals (outcome IS NOT NULL, is_shadow=FALSE)
  - Group by (setup_plugin, timeframe); gate at N >= 100
  - Fit IsotonicRegression(out_of_bounds="clip") on (confidence, win_label)
  - Extract breakpoints (X_thresholds_) and values (y_thresholds_) arrays — no sklearn pickling
  - Compute ECE (10 equal-width bins)
  - Upsert to confidence_calibration; delete stale rows for groups that dropped below N=100
"""
from __future__ import annotations

import collections
from typing import Any

import numpy as np
import structlog
from sklearn.isotonic import IsotonicRegression

from ..trading.signal_ledger import WIN_OUTCOMES as _WIN_OUTCOMES

logger = structlog.get_logger(__name__)

# Minimum resolved signals required to fit a calibration curve
_MIN_SAMPLE_SIZE = 100

# ECE bins
_ECE_BINS = 10


def _compute_ece(confidences: np.ndarray, win_labels: np.ndarray) -> float:
    """Expected Calibration Error — 10 equal-width bins."""
    bin_edges = np.linspace(0.0, 1.0, _ECE_BINS + 1)
    ece = 0.0
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (confidences >= lo) & (confidences < hi)
        if mask.sum() == 0:
            continue
        frac_win = float(win_labels[mask].mean())
        mean_conf = float(confidences[mask].mean())
        ece += float(mask.mean()) * abs(frac_win - mean_conf)
    return round(ece, 6)


def _fit_curve(
    confidences: list[float], win_labels: list[float]
) -> tuple[list[float], list[float], float]:
    """Fit isotonic regression curve; return (breakpoints, values, ece)."""
    x = np.array(confidences, dtype=np.float64)
    y = np.array(win_labels, dtype=np.float64)
    ir = IsotonicRegression(out_of_bounds="clip")
    ir.fit(x, y)
    breakpoints = ir.X_thresholds_.tolist()
    values = ir.y_thresholds_.tolist()
    ece = _compute_ece(x, y)
    return breakpoints, values, ece


async def run_calibration_update(db_manager: Any) -> None:
    """Train isotonic regression calibration curves and upsert to confidence_calibration.

    Called immediately after run_weight_update() on the 30-min timer tick.
    Independent failure domain: exception caught and logged; caller (weight_updater) is unaffected.

    N >= 100 gate: only (plugin_name, timeframe) pairs with sufficient resolved non-shadow
    signals produce a calibration curve.  Pairs that drop below threshold have their
    confidence_calibration row deleted so callers never see stale curves.
    """
    try:
        rows = await db_manager.execute_query(
            """
            SELECT setup_plugin, timeframe, confidence, outcome
            FROM signal_ledger
            WHERE outcome IS NOT NULL
              AND is_shadow = FALSE
            ORDER BY computed_at DESC
            LIMIT 50000
            """
        )
        if not rows:
            logger.info("calibration_update: no resolved signals — skipping")
            return

        # Group by (setup_plugin, timeframe)
        groups: dict[tuple[str, str], list] = collections.defaultdict(list)
        for row in rows:
            key = (row["setup_plugin"], row["timeframe"])
            groups[key].append(row)

        trained_keys: list[tuple[str, str]] = []
        for (plugin_name, timeframe), group_rows in groups.items():
            n = len(group_rows)
            if n < _MIN_SAMPLE_SIZE:
                continue

            confidences = [float(r["confidence"]) for r in group_rows]
            win_labels = [
                1.0 if r["outcome"] in _WIN_OUTCOMES else 0.0 for r in group_rows
            ]
            breakpoints, values, ece = _fit_curve(confidences, win_labels)

            await db_manager.execute_command(
                """
                INSERT INTO confidence_calibration
                    (plugin_name, timeframe, breakpoints, values, ece, sample_size, updated_at)
                VALUES ($1, $2, $3::double precision[], $4::double precision[], $5, $6, NOW())
                ON CONFLICT (plugin_name, timeframe) DO UPDATE
                SET breakpoints  = EXCLUDED.breakpoints,
                    values       = EXCLUDED.values,
                    ece          = EXCLUDED.ece,
                    sample_size  = EXCLUDED.sample_size,
                    updated_at   = NOW()
                """,
                plugin_name,
                timeframe,
                breakpoints,
                values,
                ece,
                n,
            )
            trained_keys.append((plugin_name, timeframe))
            logger.info(
                "calibration_curve_updated",
                plugin_name=plugin_name,
                timeframe=timeframe,
                n=n,
                ece=ece,
            )

        # Delete stale rows for (plugin_name, timeframe) pairs that dropped below N=100.
        # Without this, old curves from previously-sufficient groups mislead callers
        # if that plugin has since lost signal history (e.g. after a pipeline reset).
        if trained_keys:
            # Build exclusion list as a set of composite strings for ALL() operator
            trained_pairs = [f"{pn}::{tf}" for pn, tf in trained_keys]
            await db_manager.execute_command(
                """
                DELETE FROM confidence_calibration
                WHERE (plugin_name || '::' || timeframe) != ALL($1::text[])
                """,
                trained_pairs,
            )
        else:
            # No curves trained at all — clear the entire table to avoid serving stale data
            await db_manager.execute_command(
                "DELETE FROM confidence_calibration"
            )
            logger.info("calibration_update: no groups met N>=100 — cleared all curves")

        logger.info("calibration_update_complete", curves_trained=len(trained_keys))

    except Exception:
        logger.exception("calibration_update_failed — weight update not affected")
