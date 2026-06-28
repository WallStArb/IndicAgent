#!/usr/bin/env python3
"""
debug_batch_agent_memory.py — nightly agent memory backfill and calibration promotion

Runs four steps: epoch detection from KS alarms, regime transitions, episode backfill
from resolved signals, and cohort promotion with BH-FDR and bootstrap calibration.
Run nightly via systemd timer at 21:00; safe to rerun idempotently.
Requires TimescaleDB and resolved signal_ledger data.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Project root on sys.path -- same pattern as roll_batch.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg
import structlog

from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    MEMORY_COHORTS_PROMOTED_TOTAL,
    MEMORY_COHORTS_QUARANTINED_TOTAL,
    MEMORY_EPISODES_LABELED,
    MEMORY_PROMOTION_SKIPPED_N_ELIGIBLE,
    flush_and_shutdown_metrics,
)

_logger = structlog.get_logger("memory_batch")

# Metric aliases kept short for readability within this module
_COHORTS_PROMOTED = MEMORY_COHORTS_PROMOTED_TOTAL
_COHORTS_QUARANTINED = MEMORY_COHORTS_QUARANTINED_TOTAL
_PROMOTION_SKIPPED_N_ELIGIBLE = MEMORY_PROMOTION_SKIPPED_N_ELIGIBLE
_LABELED_GAUGE = MEMORY_EPISODES_LABELED

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FEEDBACK_LOOP_P_THRESHOLD = 0.05  # C-04: quarantine when p < 0.05
_N_ELIGIBLE_NULL_FRACTION_LIMIT = 0.20  # F6: skip cohort if >20% have NULL n_eligible
_MIN_SAMPLE_N = 30  # C-03: hard gate (also enforced by DB CHECK)
_CONSECUTIVE_ALARM_THRESHOLD = 3  # auto-increment epoch trigger


def _bootstrap_block_length(sample_n: int) -> int:
    """Circular block bootstrap block length: max(5, round(N^(1/3))).

    Rationale: optimal block length for block bootstrap under temporal correlation
    grows as O(N^(1/3)) per Hall & Horowitz (1996). We use the ceiling of N^(1/3)
    but enforce a floor of 5 to avoid degenerate short blocks at small N.
    NOT standard i.i.d. bootstrap -- temporal correlation between adjacent episodes
    (same symbol, consecutive bars) requires overlapping blocks (D-15).
    """
    return max(5, int(round(sample_n ** (1.0 / 3.0))))


def _bh_fdr(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR correction. Returns corrected p-values in original order."""
    n = len(p_values)
    if n == 0:
        return []
    # Sort indices by raw p-value ascending
    order = sorted(range(n), key=lambda i: p_values[i])
    corrected = [0.0] * n
    running_min = 1.0
    for rank in range(n - 1, -1, -1):
        orig_idx = order[rank]
        # BH formula: p_corrected = p_raw * n / (rank+1), clamped to [0,1]
        bh = min(1.0, p_values[orig_idx] * n / (rank + 1))
        running_min = min(running_min, bh)
        corrected[orig_idx] = running_min
    return corrected


def _circular_block_bootstrap_ci(
    data: list[float],
    block_len: int,
    n_boot: int = 1000,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Circular block bootstrap: returns (mean, ci_lower, ci_upper).

    Circular variant wraps around the end of the time series so every
    observation appears in exactly the same number of blocks -- eliminates
    boundary effects that standard block bootstrap has at the edges.
    Temporal correlation between adjacent episodes (same symbol, regime)
    violates i.i.d. assumption required for standard bootstrap (D-15).
    """
    import random

    n = len(data)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean_obs = sum(data) / n
    if n < block_len:
        # Degenerate: not enough data for even one block -- return point estimate
        return mean_obs, mean_obs, mean_obs

    boot_means: list[float] = []
    # Number of blocks needed to cover n observations
    n_blocks = math.ceil(n / block_len)
    for _ in range(n_boot):
        sample: list[float] = []
        for _ in range(n_blocks):
            start = random.randint(0, n - 1)
            for j in range(block_len):
                sample.append(data[(start + j) % n])
        sample = sample[:n]  # trim to exact n
        boot_means.append(sum(sample) / n)

    boot_means.sort()
    lo_idx = int(math.floor((alpha / 2) * n_boot))
    hi_idx = int(math.ceil((1 - alpha / 2) * n_boot)) - 1
    ci_lower = boot_means[max(0, lo_idx)]
    ci_upper = boot_means[min(n_boot - 1, hi_idx)]
    return mean_obs, ci_lower, ci_upper


# ---------------------------------------------------------------------------
# Step 1: EpochJob
# ---------------------------------------------------------------------------


async def run_epoch_job(conn: asyncpg.Connection, dry_run: bool) -> None:
    """Check KS alarms; auto-increment epoch if same cohort alarmed 3+ consecutive runs."""
    _logger.info("memory_batch.epoch_job.start")

    # Find cohorts with at least _CONSECUTIVE_ALARM_THRESHOLD consecutive KS alarms
    # by reading the last N rows for each (agent_id, stat_name) cohort.
    # The SPC hypertable time column is `ts`.
    rows = await conn.fetch(
        """
        WITH recent AS (
            SELECT
                agent_id,
                stat_name,
                ks_alarm,
                ts,
                ROW_NUMBER() OVER (
                    PARTITION BY agent_id, stat_name
                    ORDER BY ts DESC
                ) AS rn
            FROM memory_calibration_spc
        ),
        last_n AS (
            SELECT agent_id, stat_name, ks_alarm
            FROM recent
            WHERE rn <= $1
        ),
        alarm_counts AS (
            SELECT
                agent_id,
                stat_name,
                COUNT(*) AS total_rows,
                SUM(CASE WHEN ks_alarm THEN 1 ELSE 0 END) AS alarm_rows
            FROM last_n
            GROUP BY agent_id, stat_name
        )
        SELECT agent_id, stat_name, total_rows, alarm_rows
        FROM alarm_counts
        WHERE total_rows >= $1 AND alarm_rows >= $1
        """,
        _CONSECUTIVE_ALARM_THRESHOLD,
    )

    if not rows:
        _logger.info("memory_batch.epoch_job.no_consecutive_alarms")
        JOB_COMPLETED_TOTAL.add(1, {"job": "memory-epoch", "status": "success"})
        return

    _logger.info(
        "memory_batch.epoch_job.consecutive_alarms_found",
        cohort_count=len(rows),
    )

    if dry_run:
        for row in rows:
            _logger.info(
                "memory_batch.epoch_job.dry_run_would_increment",
                agent_id=row["agent_id"],
                stat_name=row["stat_name"],
                consecutive_alarm_count=row["alarm_rows"],
            )
        JOB_COMPLETED_TOTAL.add(1, {"job": "memory-epoch", "status": "success"})
        return

    # Auto-increment epoch once for all triggering cohorts (epoch is global)
    state_row = await conn.fetchrow(
        "SELECT current_regime_epoch FROM memory_system_state WHERE id = 1"
    )
    old_epoch: int = state_row["current_regime_epoch"] if state_row else 1

    await conn.execute("""
        UPDATE memory_system_state
        SET current_regime_epoch = current_regime_epoch + 1,
            epoch_updated_at = NOW()
        WHERE id = 1
        """)

    new_epoch = old_epoch + 1
    for row in rows:
        _logger.warning(
            "memory_batch.epoch_job.epoch_incremented",
            agent_id=row["agent_id"],
            stat_name=row["stat_name"],
            consecutive_alarm_count=row["alarm_rows"],
            old_epoch=old_epoch,
            new_epoch=new_epoch,
        )

    JOB_COMPLETED_TOTAL.add(1, {"job": "memory-epoch", "status": "success"})


# HMM regime integer -> memory_regime_label ENUM string
# 0=ranging, 1=trending_up, 2=trending_down (canonical mapping from core/ml/features.py)
_HMM_REGIME_LABEL: dict[int, str] = {
    0: "ranging",
    1: "trending_up",
    2: "trending_down",
}


# ---------------------------------------------------------------------------
# Step 2: RegimeTransitionJob
# ---------------------------------------------------------------------------


async def run_regime_transition_job(conn: asyncpg.Connection, dry_run: bool) -> None:
    """Close open regime transition rows; open new rows for current regime per (symbol, timeframe).

    Reads signal_ledger view for HMM regime flips since last run. For each
    (symbol, timeframe) pair, the latest hmm_regime_at_fire is the current regime.
    Converts integer HMM regime to memory_regime_label ENUM string.
    """
    _logger.info("memory_batch.regime_job.start")

    # Get current epoch
    state_row = await conn.fetchrow(
        "SELECT current_regime_epoch FROM memory_system_state WHERE id = 1"
    )
    current_epoch: int = state_row["current_regime_epoch"] if state_row else 1

    # Query current regime per (symbol, feature_tf) from signal_ledger
    # Use the most recent signal's hmm_regime_at_fire (integer 0/1/2)
    current_regimes = await conn.fetch("""
        SELECT DISTINCT ON (symbol, feature_tf)
            symbol,
            feature_tf AS timeframe,
            hmm_regime_at_fire AS hmm_regime_int,
            timestamp AS bar_ts
        FROM signal_ledger
        WHERE hmm_regime_at_fire IS NOT NULL
        ORDER BY symbol, feature_tf, timestamp DESC
        """)

    if not current_regimes:
        _logger.info("memory_batch.regime_job.no_signal_data")
        JOB_COMPLETED_TOTAL.add(1, {"job": "memory-regime", "status": "success"})
        return

    closed = 0
    opened = 0

    for row in current_regimes:
        symbol = row["symbol"]
        timeframe = row["timeframe"]
        hmm_regime_int = row["hmm_regime_int"]
        bar_ts = row["bar_ts"]

        # Convert integer HMM regime to memory_regime_label ENUM string
        valid_regimes = {"ranging", "trending_up", "trending_down"}
        new_regime = _HMM_REGIME_LABEL.get(hmm_regime_int)
        if new_regime is None:
            _logger.debug(
                "memory_batch.regime_job.skip_unknown_regime",
                symbol=symbol,
                timeframe=timeframe,
                hmm_regime_int=hmm_regime_int,
            )
            continue

        # Get currently open row for this (symbol, timeframe)
        open_row = await conn.fetchrow(
            """
            SELECT id, to_regime, ts_start, signal_count, win_count, transition_n
            FROM memory_regime_transitions
            WHERE symbol = $1 AND timeframe = $2 AND ts_end IS NULL
            """,
            symbol,
            timeframe,
        )

        if open_row is not None and open_row["to_regime"] == new_regime:
            # Regime unchanged -- no transition needed
            continue

        if dry_run:
            _logger.info(
                "memory_batch.regime_job.dry_run",
                symbol=symbol,
                timeframe=timeframe,
                from_regime=open_row["to_regime"] if open_row else None,
                to_regime=new_regime,
            )
            continue

        now = datetime.now(UTC)

        if open_row is not None:
            # Close the open row
            ts_start = open_row["ts_start"]
            duration_seconds = (now - ts_start).total_seconds()
            signal_count = open_row["signal_count"] or 0
            win_count = open_row["win_count"] or 0
            transition_n = open_row["transition_n"] or 0
            win_rate = (win_count / signal_count) if signal_count >= _MIN_SAMPLE_N else None
            transition_probs = None  # NULL when transition_n < 30

            # Count historical transitions for Markov estimation
            if transition_n >= _MIN_SAMPLE_N:
                # Compute transition_probs from historical closed rows
                trans_rows = await conn.fetch(
                    """
                    SELECT to_regime, COUNT(*) AS cnt
                    FROM memory_regime_transitions
                    WHERE symbol = $1 AND timeframe = $2
                      AND from_regime = $3
                      AND ts_end IS NOT NULL
                    GROUP BY to_regime
                    """,
                    symbol,
                    timeframe,
                    open_row["to_regime"],
                )
                total = sum(r["cnt"] for r in trans_rows)
                if total > 0:
                    probs = {r["to_regime"]: r["cnt"] / total for r in trans_rows}
                    # Fill missing regimes with 0
                    for reg in valid_regimes:
                        probs.setdefault(reg, 0.0)
                    # Normalize to sum=1.0 (guard against rounding)
                    prob_sum = sum(probs.values())
                    if prob_sum > 0:
                        probs = {k: v / prob_sum for k, v in probs.items()}
                    # Validate chk_transition_probs_sum constraint
                    total_check = sum(probs.values())
                    if abs(total_check - 1.0) < 0.001:
                        transition_probs = probs

            await conn.execute(
                """
                UPDATE memory_regime_transitions
                SET ts_end = $1,
                    duration_seconds = $2,
                    win_rate = $3,
                    transition_probs = $4
                WHERE id = $5
                """,
                now,
                duration_seconds,
                win_rate,
                transition_probs,
                open_row["id"],
            )
            closed += 1

        # Open a new row for the current regime
        from_regime = open_row["to_regime"] if open_row else None
        await conn.execute(
            """
            INSERT INTO memory_regime_transitions
                (ts_start, symbol, timeframe, regime_epoch, from_regime, to_regime,
                 signal_count, win_count, transition_n)
            VALUES ($1, $2, $3, $4, $5::memory_regime_label, $6::memory_regime_label,
                    0, 0, 0)
            ON CONFLICT ON CONSTRAINT mem_reg_open DO NOTHING
            """,
            bar_ts,
            symbol,
            timeframe,
            current_epoch,
            from_regime,
            new_regime,
        )
        opened += 1

    _logger.info(
        "memory_batch.regime_job.complete",
        closed=closed,
        opened=opened,
        dry_run=dry_run,
    )
    JOB_COMPLETED_TOTAL.add(1, {"job": "memory-regime", "status": "success"})


# ---------------------------------------------------------------------------
# Step 3: BackfillJob
# ---------------------------------------------------------------------------


async def run_backfill_job(conn: asyncpg.Connection, dry_run: bool) -> None:
    """Copy resolved raw episodes into memory_episodes_labeled (idempotent, append-only).

    V2.11_ACTIVATED: JOIN signal_ledger on signal_id WHERE raw.outcome IS NULL AND raw.embedding IS NOT NULL
    AND sl.counterfactual_pnl_r IS NOT NULL. INSERT ON CONFLICT (id) DO NOTHING.

    Separately back-fills n_eligible on raw rows (C-02).
    """
    _logger.info("memory_batch.backfill_job.start")

    # Find episodes ready to label
    ready_rows = await conn.fetch("""
        SELECT
            r.id,
            r.ts,
            r.written_at,
            r.kind::text AS kind,
            r.signal_id,
            r.symbol,
            r.timeframe,
            r.agent_id,
            r.embedding,
            r.embedding_text,
            r.hmm_regime,
            r.vol_regime,
            r.entry_type,
            r.regime_epoch,
            r.n_eligible,
            r.memory_assisted,
            r.payload,
            (sl.counterfactual_pnl_r > 0) AS outcome,
            sl.counterfactual_pnl_r AS pnl_r,
            sl.mae,
            sl.mfe
        FROM memory_episodes_raw r
        JOIN signal_ledger sl ON sl.signal_id = r.signal_id
        WHERE r.outcome IS NULL
          AND r.signal_id IS NOT NULL
          AND r.embedding IS NOT NULL
          AND sl.counterfactual_pnl_r IS NOT NULL
        """)

    if not ready_rows:
        _logger.info("memory_batch.backfill_job.no_rows_ready")
    else:
        _logger.info("memory_batch.backfill_job.rows_ready", count=len(ready_rows))

        if not dry_run:
            inserted = 0
            for row in ready_rows:
                try:
                    async with conn.transaction():
                        result = await conn.fetchval(
                            """
                            INSERT INTO memory_episodes_labeled
                                (id, ts, written_at, labeled_at, kind, signal_id,
                                 symbol, timeframe, agent_id, embedding, embedding_text,
                                 hmm_regime, vol_regime, entry_type, regime_epoch,
                                 n_eligible, memory_assisted, outcome,
                                 pnl_r, mae, mfe, bars_in_trade, payload)
                            VALUES ($1, $2, $3, NOW(), $4::memory_episode_kind, $5,
                                    $6, $7, $8, $9, $10,
                                    $11, $12, $13, $14,
                                    $15, $16, $17,
                                    $18, $19, $20, NULL, $21)
                            ON CONFLICT (id, ts) DO NOTHING
                            RETURNING id
                            """,
                            row["id"],
                            row["ts"],
                            row["written_at"],
                            row["kind"],
                            row["signal_id"],
                            row["symbol"],
                            row["timeframe"],
                            row["agent_id"],
                            row["embedding"],
                            row["embedding_text"],
                            row["hmm_regime"],
                            row["vol_regime"],
                            row["entry_type"],
                            row["regime_epoch"],
                            row["n_eligible"],
                            row["memory_assisted"],
                            row["outcome"],
                            row["pnl_r"],
                            row["mae"],
                            row["mfe"],
                            row["payload"],
                        )
                        if result is not None:
                            inserted += 1
                            # Mark raw episode as resolved (atomic with the INSERT above)
                            await conn.execute(
                                "UPDATE memory_episodes_raw SET outcome = $1 WHERE id = $2 AND ts = $3",
                                row["outcome"],
                                row["id"],
                                row["ts"],
                            )
                except Exception as error:
                    _logger.warning(
                        "memory_batch.backfill_job.insert_error",
                        signal_id=str(row["signal_id"]),
                        error=str(error),
                    )

            _logger.info("memory_batch.backfill_job.inserted", count=inserted)

    # C-02: back-fill n_eligible on raw rows that have signal_id but NULL n_eligible
    # n_eligible = count of eligible bars from market_data_ohlcv that coincide with
    # an active signal window for the same (symbol, timeframe)
    if not dry_run:
        eligible_updated = await conn.execute("""
            UPDATE memory_episodes_raw r
            SET n_eligible = subq.n_eligible
            FROM (
                SELECT
                    r2.id,
                    r2.ts,
                    COUNT(m.timestamp) AS n_eligible
                FROM memory_episodes_raw r2
                JOIN signal_ledger sl ON sl.signal_id = r2.signal_id
                JOIN market_data_ohlcv m ON m.symbol = r2.symbol
                    AND m.timeframe = r2.timeframe
                    AND m.timestamp >= sl.timestamp
                    AND m.timestamp <= COALESCE(sl.exit_at, NOW())
                WHERE r2.n_eligible IS NULL AND r2.signal_id IS NOT NULL
                GROUP BY r2.id, r2.ts
            ) subq
            WHERE r.id = subq.id AND r.ts = subq.ts
            """)
        _logger.info("memory_batch.backfill_job.n_eligible_updated", result=eligible_updated)

    # Emit post-run labeled count gauge
    labeled_count = await conn.fetchval("SELECT COUNT(*) FROM memory_episodes_labeled")
    if labeled_count is not None:
        _LABELED_GAUGE.set(int(labeled_count), {})

    JOB_COMPLETED_TOTAL.add(1, {"job": "memory-backfill", "status": "success"})


# ---------------------------------------------------------------------------
# Step 4: PromotionJob
# ---------------------------------------------------------------------------


async def run_promotion_job(conn: asyncpg.Connection, dry_run: bool) -> None:
    """Compute calibration stats for cohorts with N>=30, apply BH-FDR + circular block bootstrap.

    Cohorts: GROUP BY (agent_id, symbol, hmm_regime, entry_type, regime_epoch).
    Skips cohorts with sample_n < 30 (C-03).
    F6 guard: skips cohorts with >20% NULL n_eligible.
    C-04: tests for feedback-loop amplification.
    Writes to memory_calibration_promoted (append-only) and memory_calibration_spc.
    """
    _logger.info("memory_batch.promotion_job.start")

    # Get current epoch
    state_row = await conn.fetchrow(
        "SELECT current_regime_epoch FROM memory_system_state WHERE id = 1"
    )
    current_epoch: int = state_row["current_regime_epoch"] if state_row else 1

    # Get all cohort groups with sufficient data
    cohort_rows = await conn.fetch(
        """
        SELECT
            agent_id,
            symbol,
            hmm_regime,
            entry_type,
            regime_epoch,
            COUNT(*) AS sample_n,
            MIN(ts) AS window_start,
            MAX(ts) AS window_end,
            -- pnl_r values for bootstrap
            AVG(pnl_r) AS mean_pnl_r,
            -- memory_assisted stats for C-04
            SUM(CASE WHEN memory_assisted THEN 1 ELSE 0 END) AS memory_assisted_n,
            -- n_eligible stats for F6 guard
            SUM(CASE WHEN n_eligible IS NULL THEN 1 ELSE 0 END) AS null_n_eligible_count,
            AVG(CASE WHEN n_eligible IS NOT NULL THEN n_eligible ELSE NULL END) AS avg_n_eligible
        FROM memory_episodes_labeled
        WHERE agent_id IS NOT NULL
        GROUP BY agent_id, symbol, hmm_regime, entry_type, regime_epoch
        HAVING COUNT(*) >= $1
        """,
        _MIN_SAMPLE_N,
    )

    if not cohort_rows:
        _logger.info("memory_batch.promotion_job.no_cohorts")
        JOB_COMPLETED_TOTAL.add(1, {"job": "memory-promote", "status": "success"})
        return

    _logger.info("memory_batch.promotion_job.cohorts_found", count=len(cohort_rows))

    # Collect p-values for BH-FDR across all surviving cohorts
    # We must compute all raw p-values first, then apply BH correction together
    cohort_data: list[dict] = []

    for row in cohort_rows:
        agent_id = row["agent_id"]
        sample_n = row["sample_n"]
        null_count = row["null_n_eligible_count"] or 0

        # F6 guard: skip if >20% have NULL n_eligible
        null_fraction = null_count / sample_n if sample_n > 0 else 0.0
        if null_fraction > _N_ELIGIBLE_NULL_FRACTION_LIMIT:
            _PROMOTION_SKIPPED_N_ELIGIBLE.add(1, {"agent_id": agent_id})
            _logger.info(
                "memory_batch.promotion_job.skip_null_n_eligible",
                agent_id=agent_id,
                symbol=row["symbol"],
                hmm_regime=row["hmm_regime"],
                entry_type=row["entry_type"],
                regime_epoch=row["regime_epoch"],
                null_fraction=round(null_fraction, 3),
                sample_n=sample_n,
            )
            continue

        # Fetch episode-level data for this cohort
        episodes = await conn.fetch(
            """
            SELECT pnl_r, outcome, memory_assisted, n_eligible
            FROM memory_episodes_labeled
            WHERE agent_id = $1
              AND (symbol = $2 OR ($2 IS NULL AND symbol IS NULL))
              AND (hmm_regime = $3 OR ($3 IS NULL AND hmm_regime IS NULL))
              AND (entry_type = $4 OR ($4 IS NULL AND entry_type IS NULL))
              AND regime_epoch = $5
            ORDER BY ts ASC
            """,
            row["agent_id"],
            row["symbol"],
            row["hmm_regime"],
            row["entry_type"],
            row["regime_epoch"],
        )

        if len(episodes) < _MIN_SAMPLE_N:
            continue

        pnl_values = [float(e["pnl_r"]) for e in episodes]
        outcomes = [e["outcome"] for e in episodes]
        memory_assisted_flags = [bool(e["memory_assisted"]) for e in episodes]

        # Outcome rate (using pnl_r > 0 as proxy for positive outcome)
        positive_count = sum(1 for p in pnl_values if p > 0)
        actual_rate = positive_count / len(pnl_values)
        base_rate = actual_rate  # For this cohort

        # Mean prediction (use mean pnl_r as prediction proxy)
        mean_prediction = sum(pnl_values) / len(pnl_values)

        # Brier decomposition (using binary outcome: pnl > 0)
        # brier_score  = mean squared error of scalar forecast vs binary outcomes
        # reliability  = squared deviation of mean forecast from observed win rate
        #                (calibration error; zero means forecast = actual rate)
        # resolution   = 0 for a single-bin forecast (no per-bin variation possible)
        # skill_score  = 1 - brier/brier_base (negative = worse than climatology)
        binary_outcomes = [1.0 if p > 0 else 0.0 for p in pnl_values]
        brier_score = sum((mean_prediction - o) ** 2 for o in binary_outcomes) / len(
            binary_outcomes
        )
        brier_base = base_rate * (1 - base_rate)  # Variance of climatology
        reliability_score = (mean_prediction - actual_rate) ** 2
        resolution_score = 0.0  # Single-bin forecast; no per-bin variation
        skill_score = 1.0 - (brier_score / brier_base) if brier_base > 0 else 0.0

        # Calibration error
        calibration_error = abs(mean_prediction - actual_rate)
        pred_variance = sum((p - mean_prediction) ** 2 for p in pnl_values) / len(pnl_values)
        calibration_error_variance = pred_variance

        # Information coefficient (rank correlation between pnl_r and position in sequence)
        # Simplified: correlation between predicted order and actual pnl order
        n = len(pnl_values)
        sorted_idx = sorted(range(n), key=lambda i: pnl_values[i])
        ranks = [0.0] * n
        for rank, idx in enumerate(sorted_idx):
            ranks[idx] = float(rank)
        # IC = Pearson correlation between normalized rank and outcome
        mean_rank = sum(ranks) / n
        mean_outcome = sum(binary_outcomes) / n
        cov = (
            sum((ranks[i] - mean_rank) * (binary_outcomes[i] - mean_outcome) for i in range(n)) / n
        )
        std_rank = math.sqrt(sum((r - mean_rank) ** 2 for r in ranks) / n) if n > 1 else 0.0
        std_outcome = (
            math.sqrt(sum((o - mean_outcome) ** 2 for o in binary_outcomes) / n) if n > 1 else 0.0
        )
        information_coefficient = (
            cov / (std_rank * std_outcome) if (std_rank > 0 and std_outcome > 0) else 0.0
        )
        ic_t_stat = (
            information_coefficient
            * math.sqrt(n - 2)
            / math.sqrt(max(1e-10, 1 - information_coefficient**2))
        )
        # Two-tailed p-value approximation using standard normal CDF
        ic_p_value = 2.0 * (1.0 - _normal_cdf(abs(ic_t_stat)))

        # Circular block bootstrap CI
        block_len = _bootstrap_block_length(n)
        _mean_pnl, ci_lower, ci_upper = _circular_block_bootstrap_ci(pnl_values, block_len)
        # p_value_raw: probability the mean pnl_r is non-positive
        # Approximate via bootstrap distribution
        p_value_raw = _bootstrap_p_value(pnl_values, block_len)

        # correction_factor: only write when stable across rolling sub-windows
        correction_factor, correction_factor_stable = _compute_correction_factor(pnl_values)

        # C-04: feedback loop test
        # H0: memory_assisted episodes have same outcome rate as non-assisted
        assisted_outcomes = [binary_outcomes[i] for i, f in enumerate(memory_assisted_flags) if f]
        non_assisted_outcomes = [
            binary_outcomes[i] for i, f in enumerate(memory_assisted_flags) if not f
        ]
        memory_assisted_n = sum(memory_assisted_flags)
        memory_assisted_fraction = memory_assisted_n / n

        feedback_loop_p: float | None = None
        feedback_loop_quarantine = False
        quarantine_review_at: datetime | None = None

        if len(assisted_outcomes) >= 10 and len(non_assisted_outcomes) >= 10:
            feedback_loop_p = _two_proportion_z_test(
                sum(assisted_outcomes),
                len(assisted_outcomes),
                sum(non_assisted_outcomes),
                len(non_assisted_outcomes),
            )
            if feedback_loop_p is not None and feedback_loop_p < _FEEDBACK_LOOP_P_THRESHOLD:
                feedback_loop_quarantine = True
                quarantine_review_at = datetime.now(UTC) + timedelta(days=7)
                _COHORTS_QUARANTINED.add(1, {"agent_id": agent_id})
                _logger.warning(
                    "memory_batch.promotion_job.feedback_loop_quarantine",
                    agent_id=agent_id,
                    symbol=row["symbol"],
                    hmm_regime=row["hmm_regime"],
                    feedback_loop_p=feedback_loop_p,
                )

        # n_eligible and p_signal (selection bias, C-02)
        avg_n_eligible = row["avg_n_eligible"]
        p_signal = (
            float(sample_n) / float(avg_n_eligible)
            if avg_n_eligible and avg_n_eligible > 0
            else None
        )

        cohort_data.append(
            {
                "agent_id": agent_id,
                "symbol": row["symbol"],
                "hmm_regime": row["hmm_regime"],
                "entry_type": row["entry_type"],
                "regime_epoch": row["regime_epoch"],
                "window_start": row["window_start"],
                "window_end": row["window_end"],
                "sample_n": sample_n,
                "mean_prediction": mean_prediction,
                "actual_rate": actual_rate,
                "calibration_error": calibration_error,
                "calibration_error_variance": calibration_error_variance,
                "correction_factor": correction_factor,
                "correction_factor_stable": correction_factor_stable,
                "brier_score": brier_score,
                "base_rate": base_rate,
                "reliability_score": reliability_score,
                "resolution_score": resolution_score,
                "skill_score": skill_score,
                "information_coefficient": information_coefficient,
                "ic_t_stat": ic_t_stat,
                "ic_p_value": ic_p_value,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "bootstrap_block_length": block_len,
                "p_value_raw": p_value_raw,
                "n_hypotheses_tested": 0,  # placeholder; filled below after BH-FDR
                "n_eligible": int(avg_n_eligible) if avg_n_eligible else None,
                "p_signal": p_signal,
                "memory_assisted_n": memory_assisted_n,
                "memory_assisted_fraction": memory_assisted_fraction,
                "feedback_loop_p": feedback_loop_p,
                "feedback_loop_quarantine": feedback_loop_quarantine,
                "quarantine_review_at": quarantine_review_at,
            }
        )

    if not cohort_data:
        _logger.info("memory_batch.promotion_job.all_cohorts_skipped")
        JOB_COMPLETED_TOTAL.add(1, {"job": "memory-promote", "status": "success"})
        return

    # Apply BH-FDR across all surviving cohorts
    n_hypotheses = len(cohort_data)
    raw_p_values = [c["p_value_raw"] for c in cohort_data]
    corrected_p_values = _bh_fdr(raw_p_values)

    for i, cohort in enumerate(cohort_data):
        cohort["p_value_corrected"] = corrected_p_values[i]
        cohort["n_hypotheses_tested"] = n_hypotheses

    _logger.info(
        "memory_batch.promotion_job.writing",
        cohort_count=len(cohort_data),
        dry_run=dry_run,
    )

    if dry_run:
        for cohort in cohort_data:
            _logger.info(
                "memory_batch.promotion_job.dry_run_cohort",
                agent_id=cohort["agent_id"],
                sample_n=cohort["sample_n"],
                skill_score=round(cohort["skill_score"], 4),
                quarantine=cohort["feedback_loop_quarantine"],
            )
        JOB_COMPLETED_TOTAL.add(1, {"job": "memory-promote", "status": "success"})
        return

    promoted_count = 0
    now = datetime.now(UTC)

    for cohort in cohort_data:
        try:
            await conn.execute(
                """
                INSERT INTO memory_calibration_promoted (
                    promoted_at, agent_id, symbol, hmm_regime, entry_type, regime_epoch,
                    window_start, window_end, sample_n,
                    mean_prediction, actual_rate, calibration_error, calibration_error_variance,
                    correction_factor, correction_factor_stable,
                    brier_score, base_rate, reliability_score, resolution_score, skill_score,
                    information_coefficient, ic_t_stat, ic_p_value,
                    ci_lower, ci_upper, bootstrap_block_length,
                    p_value_raw, p_value_corrected, n_hypotheses_tested,
                    n_eligible, p_signal,
                    memory_assisted_n, memory_assisted_fraction,
                    feedback_loop_p, feedback_loop_quarantine, quarantine_review_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9,
                    $10, $11, $12, $13,
                    $14, $15,
                    $16, $17, $18, $19, $20,
                    $21, $22, $23,
                    $24, $25, $26,
                    $27, $28, $29,
                    $30, $31,
                    $32, $33,
                    $34, $35, $36
                )
                """,
                now,
                cohort["agent_id"],
                cohort["symbol"],
                cohort["hmm_regime"],
                cohort["entry_type"],
                cohort["regime_epoch"],
                cohort["window_start"],
                cohort["window_end"],
                cohort["sample_n"],
                cohort["mean_prediction"],
                cohort["actual_rate"],
                cohort["calibration_error"],
                cohort["calibration_error_variance"],
                cohort["correction_factor"],
                cohort["correction_factor_stable"],
                cohort["brier_score"],
                cohort["base_rate"],
                cohort["reliability_score"],
                cohort["resolution_score"],
                cohort["skill_score"],
                cohort["information_coefficient"],
                cohort["ic_t_stat"],
                cohort["ic_p_value"],
                cohort["ci_lower"],
                cohort["ci_upper"],
                cohort["bootstrap_block_length"],
                cohort["p_value_raw"],
                cohort["p_value_corrected"],
                cohort["n_hypotheses_tested"],
                cohort["n_eligible"],
                cohort["p_signal"],
                cohort["memory_assisted_n"],
                cohort["memory_assisted_fraction"],
                cohort["feedback_loop_p"],
                cohort["feedback_loop_quarantine"],
                cohort["quarantine_review_at"],
            )
            promoted_count += 1
            _COHORTS_PROMOTED.add(1, {"agent_id": cohort["agent_id"]})

            # Write SPC row for each promoted cohort
            await _write_spc_row(conn, cohort, now)

        except Exception as error:
            _logger.warning(
                "memory_batch.promotion_job.insert_error",
                agent_id=cohort["agent_id"],
                error=str(error),
            )

    _logger.info("memory_batch.promotion_job.complete", promoted=promoted_count)
    JOB_COMPLETED_TOTAL.add(1, {"job": "memory-promote", "status": "success"})


async def _write_spc_row(conn: asyncpg.Connection, cohort: dict, now: datetime) -> None:
    """Write SPC tracking row to memory_calibration_spc for the promoted cohort."""
    # EWMA parameters
    ewma_lambda = 0.2
    sample_n = cohort["sample_n"]

    # Fetch previous EWMA value for this cohort if exists
    prev = await conn.fetchrow(
        """
        SELECT ewma_value, ewma_stddev, cusum_pos, cusum_neg
        FROM memory_calibration_spc
        WHERE agent_id = $1
          AND (symbol = $2 OR ($2 IS NULL AND symbol IS NULL))
          AND (hmm_regime = $3 OR ($3 IS NULL AND hmm_regime IS NULL))
          AND stat_name = 'skill_score'
        ORDER BY ts DESC
        LIMIT 1
        """,
        cohort["agent_id"],
        cohort["symbol"],
        cohort["hmm_regime"],
    )

    stat_value = cohort["skill_score"]
    if prev is not None:
        prev_ewma = float(prev["ewma_value"])
        prev_stddev = float(prev["ewma_stddev"])
        ewma_value = ewma_lambda * stat_value + (1 - ewma_lambda) * prev_ewma
        ewma_stddev = math.sqrt(
            ewma_lambda * (stat_value - ewma_value) ** 2 + (1 - ewma_lambda) * prev_stddev**2
        )
        cusum_pos = max(0.0, float(prev["cusum_pos"]) + stat_value - ewma_value - 0.5 * ewma_stddev)
        cusum_neg = min(0.0, float(prev["cusum_neg"]) + stat_value - ewma_value + 0.5 * ewma_stddev)
    else:
        ewma_value = stat_value
        ewma_stddev = abs(stat_value) * 0.1 or 0.01
        cusum_pos = 0.0
        cusum_neg = 0.0

    # Control limits: 3-sigma
    cusum_h_sigma = 5.0
    cusum_h_absolute = cusum_h_sigma * ewma_stddev
    ewma_ucl = ewma_value + 3 * ewma_stddev
    ewma_lcl = ewma_value - 3 * ewma_stddev
    ewma_alarm = stat_value > ewma_ucl or stat_value < ewma_lcl
    cusum_alarm = abs(cusum_pos) > cusum_h_absolute or abs(cusum_neg) > cusum_h_absolute

    # KS test: compare to historical distribution (simplified: use stddev threshold)
    ks_stat: float | None = None
    ks_p_value: float | None = None
    ks_alarm = False
    if prev is not None:
        deviation = abs(stat_value - ewma_value) / max(ewma_stddev, 1e-10)
        ks_stat = deviation
        ks_p_value = 2.0 * (1.0 - _normal_cdf(deviation))
        ks_alarm = ks_p_value < 0.05

    await conn.execute(
        """
        INSERT INTO memory_calibration_spc (
            ts, agent_id, symbol, hmm_regime, entry_type, regime_epoch,
            stat_name, window_bars, sample_n,
            ewma_lambda, ewma_value, ewma_stddev, ewma_ucl, ewma_lcl, ewma_alarm,
            cusum_pos, cusum_neg, cusum_h_sigma, cusum_h_absolute, cusum_alarm,
            ks_stat, ks_p_value, ks_alarm
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            'skill_score', $7, $8,
            $9, $10, $11, $12, $13, $14,
            $15, $16, $17, $18, $19,
            $20, $21, $22
        )
        ON CONFLICT (ts, agent_id, stat_name) DO NOTHING
        """,
        now,
        cohort["agent_id"],
        cohort["symbol"],
        cohort["hmm_regime"],
        cohort["entry_type"],
        cohort["regime_epoch"],
        sample_n,  # window_bars
        sample_n,
        ewma_lambda,
        ewma_value,
        ewma_stddev,
        ewma_ucl,
        ewma_lcl,
        ewma_alarm,
        cusum_pos,
        cusum_neg,
        cusum_h_sigma,
        cusum_h_absolute,
        cusum_alarm,
        ks_stat,
        ks_p_value,
        ks_alarm,
    )


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _bootstrap_p_value(data: list[float], block_len: int, n_boot: int = 500) -> float:
    """Bootstrap p-value: P(mean <= 0) using circular block bootstrap."""
    import random

    n = len(data)
    if n == 0:
        return 1.0
    observed_mean = sum(data) / n
    # Shift data to H0: mean = 0
    shifted = [x - observed_mean for x in data]
    n_blocks = math.ceil(n / block_len)
    count_ge = 0
    for _ in range(n_boot):
        sample: list[float] = []
        for _ in range(n_blocks):
            start = random.randint(0, n - 1)
            for j in range(block_len):
                sample.append(shifted[(start + j) % n])
        sample = sample[:n]
        if sum(sample) / n >= observed_mean:
            count_ge += 1
    return count_ge / n_boot


def _two_proportion_z_test(x1: int, n1: int, x2: int, n2: int) -> float | None:
    """Two-proportion Z-test p-value. Returns None if not computable."""
    if n1 == 0 or n2 == 0:
        return None
    p1 = x1 / n1
    p2 = x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = abs(p1 - p2) / se
    return 2.0 * (1.0 - _normal_cdf(z))


def _compute_correction_factor(pnl_values: list[float]) -> tuple[float | None, bool]:
    """Compute calibration correction factor; only stable when consistent across 3 sub-windows.

    Correction factor = actual_win_rate / mean_prediction, where mean_prediction is
    the mean pnl_r (used as the scalar forecast proxy). A factor > 1 means the agent
    under-predicts win rate; < 1 means over-predicts. An agent should multiply its
    confidence by this factor to match the observed win rate.

    Returns (correction_factor, correction_factor_stable).
    correction_factor is None when not computable or not stable.
    """
    n = len(pnl_values)
    if n < _MIN_SAMPLE_N:
        return None, False

    mean_prediction = sum(pnl_values) / n
    if abs(mean_prediction) < 1e-6:
        return None, False

    actual_rate = sum(1.0 for p in pnl_values if p > 0) / n
    correction_factor_value = actual_rate / mean_prediction

    # Check stability across 3 rolling sub-windows
    third = n // 3
    windows = [
        pnl_values[:third],
        pnl_values[third : 2 * third],
        pnl_values[2 * third :],
    ]
    sub_factors: list[float] = []
    for w in windows:
        if not w:
            return None, False
        w_mean = sum(w) / len(w)
        if abs(w_mean) < 1e-6:
            return None, False
        w_rate = sum(1.0 for p in w if p > 0) / len(w)
        sub_factors.append(w_rate / w_mean)

    mean_sub = sum(sub_factors) / len(sub_factors)
    if abs(mean_sub) < 1e-6:
        return None, False
    max_deviation = max(abs(f - mean_sub) / abs(mean_sub) for f in sub_factors)
    is_stable = max_deviation < 0.20

    return (correction_factor_value, is_stable) if is_stable else (None, False)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def run(dry_run: bool = False) -> int:
    """Run all 4 steps in strict order. Returns 0 on full success, 1 if any step failed."""
    settings = Settings()
    _logger.info("memory_batch.run", dry_run=dry_run)

    pool = await create_db_pool(settings.database_url, min_size=1, max_size=2)
    exit_code = 0

    try:
        async with pool.acquire() as conn:
            # Step 1: EpochJob
            try:
                await run_epoch_job(conn, dry_run)
            except Exception as error:
                _logger.error("memory_batch.epoch_job.failed", error=str(error))
                JOB_COMPLETED_TOTAL.add(1, {"job": "memory-epoch", "status": "failure"})
                exit_code = 1
                return exit_code

            # Step 2: RegimeTransitionJob
            try:
                await run_regime_transition_job(conn, dry_run)
            except Exception as error:
                _logger.error("memory_batch.regime_job.failed", error=str(error))
                JOB_COMPLETED_TOTAL.add(1, {"job": "memory-regime", "status": "failure"})
                exit_code = 1
                return exit_code

            # Step 3: BackfillJob
            try:
                await run_backfill_job(conn, dry_run)
            except Exception as error:
                _logger.error("memory_batch.backfill_job.failed", error=str(error))
                JOB_COMPLETED_TOTAL.add(1, {"job": "memory-backfill", "status": "failure"})
                exit_code = 1
                return exit_code

            # Step 4: PromotionJob
            try:
                await run_promotion_job(conn, dry_run)
            except Exception as error:
                _logger.error("memory_batch.promotion_job.failed", error=str(error))
                JOB_COMPLETED_TOTAL.add(1, {"job": "memory-promote", "status": "failure"})
                exit_code = 1
                return exit_code

    finally:
        await pool.close()

    _logger.info("memory_batch.complete", exit_code=exit_code)
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nightly agent memory backfill and calibration promotion batch"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log decisions, skip DB writes",
    )
    args = parser.parse_args()
    exit_code = 1
    try:
        exit_code = asyncio.run(run(dry_run=args.dry_run))
    finally:
        flush_and_shutdown_metrics()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
