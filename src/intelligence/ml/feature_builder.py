"""Feature matrix construction for ML training (Phase 070).

Called from MLTrainer on the nightly training cycle.
Independent failure domain: any exception propagates to caller, which catches
at the top level and exits 0 to preserve systemd timer cadence.

Algorithm:
  1. Query signal_ledger (resolved, non-shadow, schema v2) JOIN intelligence_features
     to extract the features_snapshot JSONB + bar context columns
  2. No-lookahead enforced by SQL clause: f.ts < sl.activated_at
  3. Flatten features_snapshot keys into top-level DataFrame columns
  4. Provide one-hot encoding for categorical features
  5. Provide walk-forward 60/20/20 temporal split (no shuffling)
  6. Provide segment filtering by hmm_regime

CANONICAL FIELD NAMES:
  - volume_z_score is the i1 JSONB key (always use this exact name)
  - Bar context fields: hmm_regime, trend_regime, session_type, atr_pct,
    volume_z_score, tod_multiplier
"""

from __future__ import annotations

from typing import Any

import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# Minimum resolved signals required to fit any segment model
_MIN_SAMPLE_SIZE = 100

# 25 keys verbatim from confidence_utils.py capture_signal_features()
# 2 metadata + 6 I6 CTF confluence + 4 I4 macro + 2 I6 momentum divergence +
# 2 I6 S/R confluence + 2 I6 HMM regime agreement + 2 I6 volatility divergence +
# 2 I6 orderflow alignment + 3 exhaustion = 25
SHADOW_FEATURE_KEYS: tuple[str, ...] = (
    "profile",
    "existing_confidence",
    "ctf_score",
    "ctf_trend_alignment",
    "ctf_structure_alignment",
    "ctf_regime_agreement",
    "ctf_fvg_alignment",
    "ctf_ob_alignment",
    "vix_level",
    "vix_z",
    "eq_spread_z",
    "eq_pairs_confirming",
    "ctf_momentum_divergence",
    "ctf_momentum_regime",
    "ctf_sr_confluence",
    "ctf_sr_regime",
    "ctf_hmm_regime_agreement",
    "ctf_hmm_regime_label",
    "ctf_volatility_divergence",
    "ctf_volatility_regime",
    "ctf_orderflow_alignment",
    "ctf_orderflow_regime",
    "exhaustion_score",
    "exhaustion_side",
    "exhaustion_bars",
)

# Categorical feature keys that require one-hot encoding
_CATEGORICAL_KEYS: tuple[str, ...] = (
    "profile",
    "ctf_momentum_regime",
    "ctf_sr_regime",
    "ctf_hmm_regime_label",
    "ctf_volatility_regime",
    "ctf_orderflow_regime",
    "exhaustion_side",
    "hmm_regime",
    "session_type",
)

# Training SQL — selects from signal_ledger JOIN intelligence_features.
# tod_multiplier sourced from trading_signals JSONB array element 0 (the I7 trading signal payload).
# COALESCE to 1.0 so inference and training feature vectors keep identical shape when absent.
# No-lookahead enforced: f.ts < sl.activated_at.
# V2.11_ACTIVATED: counterfactual_pnl_r gates resolved signals (returns empty until populated).
_TRAINING_SQL = """
SELECT
    sl.signal_id,
    sl.timestamp,
    sl.timeframe,
    sl.counterfactual_pnl_r AS pnl_r,
    (sl.counterfactual_pnl_r > 0)::int                             AS win_label,
    tf_sig.value->'features_snapshot'                              AS features_snapshot,
    (f.regime_features->>'hmm_regime')::int                        AS hmm_regime,
    (f.regime_features->>'trend_regime')::float                    AS trend_regime,
    f.session_type,
    (f.technical_indicators->>'atr_pct')::float                    AS atr_pct,
    (f.technical_indicators->>'volume_z_score')::float             AS volume_z_score,
    COALESCE((tf_sig.value->>'tod_multiplier')::float, 1.0)        AS tod_multiplier
FROM signal_ledger sl
JOIN intelligence_features f
  ON f.symbol = sl.symbol
 AND f.tf = sl.feature_tf
 AND f.ts = sl.feature_ts
 AND f.ts < sl.activated_at
JOIN LATERAL jsonb_array_elements(f.trading_signals) AS tf_sig(value)
  ON tf_sig.value->>'signal_id' = sl.signal_id::text
WHERE sl.counterfactual_pnl_r IS NOT NULL
  AND sl.is_shadow = FALSE
  AND sl.entry_zone_low IS NOT NULL
  AND tf_sig.value->'features_snapshot' IS NOT NULL
ORDER BY sl.timestamp
"""

# Metadata columns not used as model features
_META_COLS = frozenset(
    {"signal_id", "timestamp", "timeframe", "pnl_r", "win_label", "features_snapshot"}
)


async def build_training_matrix(pool: Any) -> pl.DataFrame:
    """Query signal_ledger + intelligence_features and return a training-ready polars DataFrame.

    Flattens features_snapshot JSONB into top-level columns. Returns rows sorted ascending
    by timestamp (SQL guarantees this). Empty DataFrame returned if no rows match.

    Args:
        pool: asyncpg connection pool.

    Returns:
        polars DataFrame with signal metadata columns + bar context columns +
        flattened features_snapshot keys as individual columns.
    """
    async with pool.acquire() as conn:
        records = await conn.fetch(_TRAINING_SQL)

    if not records:
        logger.warning("feature_builder.no_rows")
        return pl.DataFrame()

    # Convert asyncpg Records to plain dicts
    rows: list[dict[str, Any]] = [dict(r) for r in records]

    # Flatten features_snapshot JSONB into top-level keys
    flat_rows: list[dict[str, Any]] = []
    for row in rows:
        snapshot: dict[str, Any] = row.get("features_snapshot") or {}
        flat = {
            "signal_id": str(row["signal_id"]) if row["signal_id"] is not None else None,
            "timestamp": row["timestamp"],
            "timeframe": row["timeframe"],
            "pnl_r": row["pnl_r"],
            "win_label": row["win_label"],
            "features_snapshot": snapshot,
            "hmm_regime": row["hmm_regime"],
            "trend_regime": row["trend_regime"],
            "session_type": row["session_type"],
            "atr_pct": row["atr_pct"],
            "volume_z_score": row["volume_z_score"],
            "tod_multiplier": row["tod_multiplier"],
        }
        # Flatten each features_snapshot key into a top-level column
        for key in SHADOW_FEATURE_KEYS:
            flat[key] = snapshot.get(key)
        flat_rows.append(flat)

    # Build polars DataFrame — asyncpg already returns JSONB as dict (no json.loads needed)
    df = pl.from_dicts(flat_rows, infer_schema_length=500)

    # Defensive: drop any rows where existing_confidence key is absent from features_snapshot.
    # SQL already filters features_snapshot IS NOT NULL, but older signals may have snapshots
    # that predate the existing_confidence key. Log any dropped rows so training operators
    # can detect unexpected training set shrinkage during early Phase 70 deployment.
    if "existing_confidence" in df.columns:
        pre_filter_len = len(df)
        df = df.filter(pl.col("existing_confidence").is_not_null())
        dropped = pre_filter_len - len(df)
        if dropped > 0:
            logger.warning(
                "feature_builder.existing_confidence_filter_dropped",
                dropped=dropped,
                total=pre_filter_len,
            )

    logger.info(
        "feature_builder.matrix_built",
        n_rows=len(df),
        n_cols=len(df.columns),
    )
    return df


def encode_features(df: pl.DataFrame, feature_cols: list[str]) -> tuple[Any, Any, list[str]]:
    """One-hot encode categorical columns and convert to numpy for LightGBM.

    Args:
        df:           Training DataFrame from build_training_matrix().
        feature_cols: Column names to include as model features.

    Returns:
        (X, y, final_feature_cols) where:
          X                — numpy float64 array, shape (n_samples, n_features)
          y                — numpy int array, shape (n_samples,)
          final_feature_cols — post-encoding column name list (inference contract)
    """
    import numpy as np

    # Only encode categoricals that are both requested and present
    cats_present = [k for k in _CATEGORICAL_KEYS if k in feature_cols and k in df.columns]
    non_cats = [c for c in feature_cols if c not in cats_present and c in df.columns]

    if cats_present:
        # polars to_dummies() one-hot encodes a column in-place, returning a new DataFrame
        encoded_df = df.select(non_cats + cats_present)
        for cat_col in cats_present:
            encoded_df = encoded_df.with_columns(pl.col(cat_col).cast(pl.Utf8))
        encoded_df = encoded_df.to_dummies(columns=cats_present)
    else:
        encoded_df = df.select([c for c in non_cats if c in df.columns])

    final_feature_cols = encoded_df.columns
    X = encoded_df.to_numpy().astype(np.float64)
    y = df["win_label"].to_numpy()
    return X, y, final_feature_cols


def split_walk_forward(
    df: pl.DataFrame,
    train_frac: float = 0.60,
    val_frac: float = 0.20,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Temporal 60/20/20 walk-forward split. No shuffling.

    The SQL query guarantees ORDER BY timestamp, so no re-sort is needed here.

    Args:
        df:         Training DataFrame sorted ascending by timestamp.
        train_frac: Fraction of rows for training set (default 0.60).
        val_frac:   Fraction of rows for validation set (default 0.20).

    Returns:
        (train_df, val_df, test_df) — temporally ordered, no overlap.
    """
    n = len(df)
    n_train = int(n * train_frac)
    n_val = int(n * (train_frac + val_frac))
    return df[:n_train], df[n_train:n_val], df[n_val:]


def filter_segment(df: pl.DataFrame, segment: dict[str, Any]) -> pl.DataFrame:
    """Filter DataFrame to a specific training segment.

    Segments:
      {"global": True}      — return all rows unchanged
      {"hmm_regime": N}     — return rows where hmm_regime == N

    # Future: is_swarm_available gate for swarm-augmented features (D-03)
    # When swarm signals are captured in features_snapshot, add a branch here
    # to optionally include swarm_multiplier / adjusted_confidence as features.

    Args:
        df:      Full training DataFrame.
        segment: Segment specifier dict.

    Returns:
        Filtered polars DataFrame.
    """
    if segment.get("global"):
        return df
    if "hmm_regime" in segment:
        regime_val = segment["hmm_regime"]
        return df.filter(pl.col("hmm_regime") == regime_val)
    logger.warning("feature_builder.unknown_segment", segment=str(segment))
    return df
