"""CIS Weight Updater — adaptive weight learning via logistic regression.

Runs nightly or when 20 new outcomes accumulate. Reads resolved signals from
signal_ledger (bucket_scores + signal_quality), trains LogisticRegression,
writes new version row to cis_weights table.

Bootstrap transition rules (from CONTEXT.md):
  - n_resolved < 50:   use designed weights, no retraining → returns None
  - 50 <= n < 100:     train, blend 70% designed / 30% learned → returns blended weights
  - n >= 100:           full learned weights → returns learned weights

Usage:
    # Standalone:
    python -m src.intelligence.weight_updater

    # Importable (for testing / service integration):
    from src.intelligence.weight_updater import compute_new_weights
    result = compute_new_weights(resolved_signals)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression

from .trading.cis_scorer import BOOTSTRAP_WEIGHTS, BUCKET_NAMES

logger = logging.getLogger(__name__)

MIN_SAMPLES_TRAIN = 50
MIN_SAMPLES_FULL = 100
MIN_WEIGHT = 0.05
BLEND_DESIGNED_RATIO = 0.70  # at 50-99 samples: 70% designed


@dataclass
class WeightUpdateResult:
    """Result of a weight computation run."""

    n_resolved: int
    weights_type: str          # 'designed' | 'learned' | 'blended'
    weights: dict[str, float]
    signal_quality_mean: float
    did_retrain: bool


def _softmax(x: np.ndarray) -> np.ndarray:
    """3-line inline softmax — avoids scipy dependency."""
    e = np.exp(x - x.max())
    return e / e.sum()


def _clip_and_renormalize(weights: np.ndarray, min_w: float = MIN_WEIGHT) -> np.ndarray:
    """Enforce minimum weight per bucket and renormalize to sum=1.0."""
    clipped = np.maximum(weights, min_w)
    return clipped / clipped.sum()


def compute_new_weights(
    resolved_signals: list[dict[str, Any]],
) -> WeightUpdateResult | None:
    """Compute new CIS weights from resolved signals.

    Parameters
    ----------
    resolved_signals:
        List of dicts with keys: bucket_scores (dict or JSON string),
        signal_quality (float). Only rows where both are present are used.

    Returns
    -------
    WeightUpdateResult or None if fewer than MIN_SAMPLES_TRAIN resolved
    signals or if LogisticRegression training is degenerate.
    """
    # Filter to rows with both bucket_scores and signal_quality
    valid = [
        s for s in resolved_signals
        if s.get("bucket_scores") is not None and s.get("signal_quality") is not None
    ]
    n = len(valid)

    if n < MIN_SAMPLES_TRAIN:
        logger.info(
            "Not enough resolved signals for retraining (n=%d, required=%d)",
            n,
            MIN_SAMPLES_TRAIN,
        )
        return None

    # Build feature matrix X (n, 6) and quality scores
    bucket_list = list(BUCKET_NAMES)
    x_rows = []
    qualities = []
    for row in valid:
        bs = row["bucket_scores"]
        if isinstance(bs, str):
            bs = json.loads(bs)
        x_rows.append([float(bs.get(b, 0.0)) for b in bucket_list])
        qualities.append(float(row["signal_quality"]))

    x = np.array(x_rows)
    qualities_arr = np.array(qualities)
    quality_mean = float(qualities_arr.mean())

    # Binary target: above-mean signal quality
    y = (qualities_arr >= quality_mean).astype(int)

    # Need both classes for LogisticRegression
    if y.sum() == 0 or y.sum() == len(y):
        logger.warning("Degenerate target — all same class, skipping retraining")
        return None

    # Train LogisticRegression
    model = LogisticRegression(C=1.0, max_iter=500, random_state=42)
    model.fit(x, y)

    # Extract and normalize coefficients
    # Use abs(coef) — direction of bucket influence comes from score sign, not weight sign
    raw_coef = model.coef_[0]
    softmax_weights = _softmax(np.abs(raw_coef))
    learned_arr = _clip_and_renormalize(softmax_weights)
    learned_weights = {b: float(learned_arr[i]) for i, b in enumerate(bucket_list)}

    if n < MIN_SAMPLES_FULL:
        # Blend: 70% designed / 30% learned
        designed_arr = np.array([BOOTSTRAP_WEIGHTS[b] for b in bucket_list])
        learned_arr_blend = np.array([learned_weights[b] for b in bucket_list])
        blended_arr = (
            BLEND_DESIGNED_RATIO * designed_arr
            + (1 - BLEND_DESIGNED_RATIO) * learned_arr_blend
        )
        blended_arr = _clip_and_renormalize(blended_arr)
        final_weights = {b: float(blended_arr[i]) for i, b in enumerate(bucket_list)}
        weights_type = "blended"
    else:
        final_weights = learned_weights
        weights_type = "learned"

    return WeightUpdateResult(
        n_resolved=n,
        weights_type=weights_type,
        weights=final_weights,
        signal_quality_mean=quality_mean,
        did_retrain=True,
    )


async def run_weight_update(db_manager: Any) -> WeightUpdateResult | None:
    """Query DB and run weight update. Returns None if no update needed.

    Parameters
    ----------
    db_manager:
        DatabaseManager instance with execute_query / execute_command methods.
    """
    rows = await db_manager.execute_query(
        """
        SELECT bucket_scores, signal_quality, confidence
        FROM signal_ledger
        WHERE signal_quality IS NOT NULL
          AND bucket_scores IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT 10000
        """
    )
    if not rows:
        return None

    result = compute_new_weights(rows)
    if result is None or not result.did_retrain:
        return result

    # Write new version to cis_weights
    existing = await db_manager.execute_query(
        "SELECT MAX(version) as max_v FROM cis_weights WHERE symbol = 'global'"
    )
    next_version = ((existing[0]["max_v"] or 1) if existing else 1) + 1
    await db_manager.execute_command(
        """
        INSERT INTO cis_weights (version, weights_type, symbol, timeframe,
            trend_w, momentum_w, structure_w, pattern_w, institutional_w, regime_w,
            n_training_samples, signal_quality_mean)
        VALUES ($1, $2, 'global', 'global', $3, $4, $5, $6, $7, $8, $9, $10)
        """,
        next_version,
        result.weights_type,
        result.weights["trend"],
        result.weights["momentum"],
        result.weights["structure"],
        result.weights["pattern"],
        result.weights["institutional"],
        result.weights["regime"],
        result.n_resolved,
        result.signal_quality_mean,
    )
    logger.info(
        "New weights written (version=%d, type=%s, n=%d)",
        next_version,
        result.weights_type,
        result.n_resolved,
    )
    return result


if __name__ == "__main__":
    import asyncio
    import sys

    sys.path.insert(0, ".")
    from src.config.settings import Settings  # noqa: E402
    from src.core.database_manager import DatabaseManager  # noqa: E402

    async def _main() -> None:
        settings = Settings()
        db = DatabaseManager(settings.database_url)
        await db.connect()
        run_result = await run_weight_update(db)
        if run_result:
            print(
                f"Updated: {run_result.weights_type}, "
                f"n={run_result.n_resolved}, "
                f"weights={run_result.weights}"
            )
        else:
            print("No update needed (insufficient resolved signals)")
        await db.disconnect()

    asyncio.run(_main())
