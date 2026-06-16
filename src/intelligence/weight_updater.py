"""CIS Weight Updater — adaptive weight learning via logistic regression.

Runs nightly or when 20 new outcomes accumulate. Reads resolved signals from
signal_ledger (bucket_scores + outcome), trains LogisticRegression on binary
win/loss labels, writes new version row to cis_weights table.

Bootstrap transition rules (from CONTEXT.md):
  - n_resolved < 50:   use designed weights, no retraining → returns None
  - 50 <= n < 100:     train, blend 70% designed / 30% learned → returns blended weights
  - n >= 100:           full learned weights → returns learned weights

Cluster segmentation: when a (asset_cluster, timeframe) group has >= 100 signals,
a separate per-cluster model is trained and written. Global model always trained.

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
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from statsmodels.stats.proportion import proportions_ztest

from src.persistence.repository.signal_events_repository import WIN_OUTCOMES

from .ml.confidence_calibrator import run_calibration_update
from .trading.cis_scorer import BOOTSTRAP_WEIGHTS, BUCKET_NAMES

logger = logging.getLogger(__name__)

MIN_SAMPLES_TRAIN = 50
MIN_SAMPLES_FULL = 100
MIN_WEIGHT = 0.05
BLEND_DESIGNED_RATIO = 0.70  # at 50-99 samples: 70% designed

ASSET_CLUSTER_MAP: dict[str, str] = {
    # eq_index: equity index futures
    "ES": "eq_index",
    "NQ": "eq_index",
    "RTY": "eq_index",
    "YM": "eq_index",
    # commodity: energy + metals
    "CL": "commodity",
    "GC": "commodity",
    "SI": "commodity",
    "NG": "commodity",
    "HG": "commodity",
    "PL": "commodity",
    "PA": "commodity",
    # rates: interest rate futures
    "ZN": "rates",
    "ZB": "rates",
    "ZF": "rates",
    "ZT": "rates",
    # crypto
    "BTC": "crypto",
    "ETH": "crypto",
    "SOL": "crypto",
    # agriculture
    "ZC": "ag",
    "ZS": "ag",
    "ZW": "ag",
}


def get_asset_cluster(symbol: str) -> str:
    """Map base symbol to asset cluster. Returns 'global' for unmapped symbols."""
    return ASSET_CLUSTER_MAP.get(symbol, "global")


@dataclass
class WeightUpdateResult:
    """Result of a weight computation run."""

    n_resolved: int
    weights_type: str  # 'designed' | 'learned' | 'blended'
    weights: dict[str, float]
    win_rate: float  # fraction of wins in training set
    did_retrain: bool
    asset_cluster: str = "global"
    timeframe: str = "global"


def _softmax(x: np.ndarray) -> np.ndarray:
    """3-line inline softmax — avoids scipy dependency."""
    e = np.exp(x - x.max())
    return e / e.sum()


def _clip_and_renormalize(weights: np.ndarray, min_w: float = MIN_WEIGHT) -> np.ndarray:
    """Enforce minimum weight per bucket and renormalize to sum=1.0."""
    clipped = np.maximum(weights, min_w)
    return clipped / clipped.sum()


async def _calibrate_pattern_reliability(
    db_manager: Any,
) -> dict[str, Any] | None:
    """Calibrate pattern_reliability table from signal_ledger outcomes.

    Queries resolved CandlestickPatternSetup signals, computes win_rate and
    p_value per (pattern_name, timeframe), updates pattern_reliability when
    sample_size >= 30 and p < 0.05. Sets is_bootstrap=false on promotion.

    Returns:
        Dict with calibration stats or None if no patterns eligible.
    """
    # Query resolved candlestick signals with pattern name extracted.
    # signal_type format: "candlestick_{pattern_name}_{long|short}"
    # e.g. "candlestick_abandoned_baby_long" → pattern_name "abandoned_baby"
    # regexp_replace strips the prefix and suffix to recover multi-word pattern_name.
    win_outcomes_sql = ", ".join(f"'{o}'" for o in sorted(WIN_OUTCOMES))
    rows = await db_manager.execute_query(f"""
        SELECT
            regexp_replace(
                regexp_replace(signal_type, '^candlestick_', ''),
                '_(long|short)$', ''
            ) AS pattern_name,
            timeframe,
            COUNT(*) AS sample_size,
            AVG(CASE WHEN outcome IN ({win_outcomes_sql}) THEN 1.0 ELSE 0.0 END) AS win_rate
        FROM signal_ledger sl
        LEFT JOIN signal_outcomes so USING (signal_id)
        WHERE setup_plugin = 'trad_CandlestickPatternSetup'
            AND so.outcome IS NOT NULL
            AND is_shadow = FALSE
        GROUP BY pattern_name, timeframe
        HAVING COUNT(*) >= 30
    """)

    if not rows:
        logger.info("Pattern calibration: no patterns with sample_size >= 30")
        return None

    calibration_stats: dict[str, Any] = {}
    for row in rows:
        pattern_name = row["pattern_name"]
        timeframe = row["timeframe"]
        n = int(row["sample_size"])
        win_rate = float(row["win_rate"])

        # One-proportion z-test: is win_rate significantly different from 50% (chance)?
        wins = int(round(win_rate * n))
        if wins == 0 or wins == n:
            p_value = 1.0  # No variance, not significant
        else:
            try:
                _stat, p_value = proportions_ztest(count=wins, nobs=n, value=0.5)
                p_value = float(p_value)
            except Exception:
                p_value = 1.0

        # Only update if statistically significant (p < 0.05)
        if p_value < 0.05:
            # ic_score placeholder — ML analysis will populate when available
            ic_score = None

            await db_manager.execute_command(
                """
                UPDATE pattern_reliability
                SET
                    base_confidence = $1,
                    sample_size = $2,
                    win_rate = $3,
                    p_value = $4,
                    ic_score = $5,
                    is_bootstrap = false,
                    last_updated = NOW()
                WHERE pattern_name = $6 AND timeframe = $7
                """,
                win_rate,
                n,
                win_rate,
                p_value,
                ic_score,
                pattern_name,
                timeframe,
            )

            calibration_stats[f"{pattern_name}:{timeframe}"] = {
                "pattern_name": pattern_name,
                "timeframe": timeframe,
                "sample_size": n,
                "win_rate": win_rate,
                "p_value": p_value,
                "promoted": True,
            }
            logger.info(
                "Pattern calibration: %s (%s) promoted to data-driven weight: "
                "win_rate=%.3f, n=%d, p=%.3f",
                pattern_name,
                timeframe,
                win_rate,
                n,
                p_value,
            )
        else:
            calibration_stats[f"{pattern_name}:{timeframe}"] = {
                "pattern_name": pattern_name,
                "timeframe": timeframe,
                "sample_size": n,
                "win_rate": win_rate,
                "p_value": p_value,
                "promoted": False,
            }
            logger.info(
                "Pattern calibration: %s (%s) not significant (p=%.3f, n=%d), "
                "keeping bootstrap weight",
                pattern_name,
                timeframe,
                p_value,
                n,
            )

    return calibration_stats if calibration_stats else None


def compute_new_weights(
    resolved_signals: list[dict[str, Any]],
) -> WeightUpdateResult | None:
    """Compute new CIS weights from resolved signals.

    Parameters
    ----------
    resolved_signals:
        List of dicts with keys: bucket_scores (dict or JSON string),
        outcome (str from WIN_OUTCOMES or loss string). Only rows where
        both bucket_scores and outcome are present are used.
        signal_quality is ignored — binary outcome labels are used.

    Returns
    -------
    WeightUpdateResult or None if fewer than MIN_SAMPLES_TRAIN resolved
    signals or if LogisticRegression training is degenerate.
    """
    # Filter to rows with both bucket_scores and outcome
    valid = [
        s
        for s in resolved_signals
        if s.get("bucket_scores") is not None and s.get("outcome") is not None
    ]
    n = len(valid)

    if n < MIN_SAMPLES_TRAIN:
        logger.info(
            "Not enough resolved signals for retraining (n=%d, required=%d)",
            n,
            MIN_SAMPLES_TRAIN,
        )
        return None

    # Build feature matrix X (n, 6) and binary win/loss labels
    bucket_list = list(BUCKET_NAMES)
    x_rows = []
    for row in valid:
        bs = row["bucket_scores"]
        if isinstance(bs, str):
            bs = json.loads(bs)
        x_rows.append([float(bs.get(b, 0.0)) for b in bucket_list])

    x = np.array(x_rows)

    # Binary target: 1.0 if outcome is a win, 0.0 otherwise
    y = np.array([1.0 if row.get("outcome") in WIN_OUTCOMES else 0.0 for row in valid])
    win_rate = float(y.mean())

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
            BLEND_DESIGNED_RATIO * designed_arr + (1 - BLEND_DESIGNED_RATIO) * learned_arr_blend
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
        win_rate=win_rate,
        did_retrain=True,
    )


async def _write_weights_to_db(
    db_manager: Any,
    result: WeightUpdateResult,
    asset_cluster: str,
    timeframe: str,
) -> None:
    """Write a WeightUpdateResult to the cis_weights table.

    Parameters
    ----------
    db_manager:
        DatabaseManager instance with execute_query / execute_command methods.
    result:
        Computed weights to persist.
    asset_cluster:
        Cluster key (e.g. 'global', 'eq_index', 'crypto').
    timeframe:
        Timeframe key (e.g. 'global', '1m', '5m').
    """
    existing = await db_manager.execute_query(
        "SELECT MAX(version) as max_v FROM cis_weights WHERE asset_cluster = $1 AND timeframe = $2",
        asset_cluster,
        timeframe,
    )
    next_version = ((existing[0]["max_v"] or 0) if existing else 0) + 1
    await db_manager.execute_command(
        """INSERT INTO cis_weights (version, weights_type, symbol, timeframe, asset_cluster,
            trend_w, momentum_w, structure_w, pattern_w, institutional_w, regime_w,
            sample_size)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
        next_version,
        result.weights_type,
        "global",  # symbol retained for backward compatibility
        timeframe,
        asset_cluster,
        result.weights["trend"],
        result.weights["momentum"],
        result.weights["structure"],
        result.weights["pattern"],
        result.weights["institutional"],
        result.weights["regime"],
        result.n_resolved,
    )
    logger.info(
        "Wrote CIS weights to DB (version=%d, cluster=%s, tf=%s, type=%s, n=%d)",
        next_version,
        asset_cluster,
        timeframe,
        result.weights_type,
        result.n_resolved,
    )


async def run_weight_update(db_manager: Any) -> WeightUpdateResult | None:
    """Query DB and run weight update. Returns None if no update needed.

    Trains global model on all resolved, non-shadow signals. Additionally
    trains per-(asset_cluster, timeframe) models when cluster has >= 100 signals.

    Parameters
    ----------
    db_manager:
        DatabaseManager instance with execute_query / execute_command methods.
    """
    rows = await db_manager.execute_query("""
        SELECT sl.bucket_scores, so.outcome, sl.symbol, sl.timeframe
        FROM signal_ledger sl
        LEFT JOIN signal_outcomes so USING (signal_id)
        WHERE so.outcome IS NOT NULL
            AND sl.bucket_scores IS NOT NULL
            AND sl.is_shadow = FALSE
        ORDER BY sl.timestamp DESC
        LIMIT 10000
        """)
    if not rows:
        return None

    # Train global model on all signals
    global_result = compute_new_weights(rows)
    if global_result is None:
        return None

    if global_result.did_retrain:
        await _write_weights_to_db(
            db_manager, global_result, asset_cluster="global", timeframe="global"
        )

    # Train per-cluster models when cluster has >= MIN_SAMPLES_FULL signals
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        cluster = get_asset_cluster(row["symbol"])
        if cluster == "global":
            continue  # unmapped symbols go to global only
        groups[(cluster, row["timeframe"])].append(row)

    for (cluster, tf), group_rows in groups.items():
        if len(group_rows) < MIN_SAMPLES_FULL:
            continue
        cluster_result = compute_new_weights(group_rows)
        if cluster_result is not None and cluster_result.did_retrain:
            await _write_weights_to_db(
                db_manager, cluster_result, asset_cluster=cluster, timeframe=tf
            )

    # CAL-02: Run calibration update in independent failure domain.
    # Failure here does not affect weight update completion.
    try:
        await run_calibration_update(db_manager)
    except Exception:
        logger.error("CIS weight calibration failed", exc_info=True)

    # Phase 42: Run pattern reliability calibration in independent failure domain.
    # Failure here does not affect CIS weight update completion.
    try:
        pattern_stats = await _calibrate_pattern_reliability(db_manager)
        if pattern_stats:
            promoted_count = sum(1 for s in pattern_stats.values() if s.get("promoted", False))
            logger.info(
                "Pattern calibration complete: %d patterns analyzed, %d promoted to "
                "data-driven weights",
                len(pattern_stats),
                promoted_count,
            )
    except Exception:
        logger.error("Pattern reliability calibration failed", exc_info=True)

    return global_result


if __name__ == "__main__":
    import asyncio
    import sys

    sys.path.insert(0, ".")
    from src.config.settings import Settings  # noqa: E402
    from src.core.database_manager import DatabaseManager  # noqa: E402

    async def _main() -> None:
        settings = Settings()
        db = DatabaseManager(settings.database_url)
        await db.initialize()

        # Existing CIS weight update
        run_result = await run_weight_update(db)
        if run_result:
            print(
                f"CIS weights updated: {run_result.weights_type}, "
                f"n={run_result.n_resolved}, "
                f"weights={run_result.weights}"
            )
        else:
            print("CIS weights: no update needed (insufficient resolved signals)")

        # New: setup performance update (FEED-01)
        from src.intelligence.setup_performance_updater import (  # noqa: E402
            run_setup_performance_update,
        )

        perf_weights = await run_setup_performance_update(db)
        if perf_weights:
            print(f"Setup performance weights updated: {len(perf_weights)} eligible setups")
            for plugin, multiplier in perf_weights.items():
                print(f"  {plugin}: {multiplier:.3f}")
        else:
            print("Setup performance: no eligible setups (n<30 for all)")

        await db.close()

    asyncio.run(_main())
