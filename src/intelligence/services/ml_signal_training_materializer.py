"""MLSignalTrainingMaterializer — nightly materialization of ML training data (Phase 104).

Systemd Type=oneshot service invoked by indicagent-ml-signal-training-materialize.timer
(nightly 02:00 UTC, runs before ML training at 03:00).

Responsibilities:
  1. Phase A: INSERT new rows for previous trading day from intelligence_features + signal_ledger
     - Unnest trading_signals JSONB via LATERAL jsonb_array_elements()
     - LEFT JOIN signal_ledger for outcomes (pnl_r, outcome, win_label)
     - Flatten all JSONB values into typed columns (no JSONB at destination)
     - ON CONFLICT (ts, signal_id) DO NOTHING for initial insert only

  2. Phase B: UPDATE backfill for unresolved rows (outcome backfill strategy)
     - Run UPSERT over 30-day lookback to catch late-resolving outcomes
     - ON CONFLICT DO UPDATE SET pnl_r, win_label, outcome, materialized_at
     - WHERE win_label IS NULL AND EXCLUDED.pnl_r IS NOT NULL (idempotent)

  3. Phase C: Emit OTel metrics for inserts vs updates (track resolution rate)

Error handling: any top-level exception is caught, logged, and swallowed — exits 0 so
systemd timer fires again the next night (oneshot success semantics).
"""

from __future__ import annotations

import time as _time

import asyncpg
import structlog
from opentelemetry import metrics as _otel_metrics

from src.config.settings import Settings
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool

logger = structlog.get_logger(__name__)


class MLSignalTrainingMaterializer(BaseDaemon):
    """Nightly ML training data materialization service.

    Runs as a systemd Type=oneshot service, materializing flat typed rows from
    intelligence_features.trading_signals + signal_ledger into ml_signal_training
    hypertable. Handles initial inserts and outcome backfill via UPSERT.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._pool: asyncpg.Pool | None = None
        self._meter = _otel_metrics.get_meter("indicagent")

        # OTel metrics
        self._cycles = self._meter.create_counter(
            "ml_signal_training_cycles_total",
            description="Total materialization cycles executed",
        )
        self._errors = self._meter.create_counter(
            "ml_signal_training_errors_total",
            description="Total materialization errors",
        )
        self._duration = self._meter.create_histogram(
            "ml_signal_training_duration_seconds",
            description="Materialization duration in seconds",
            unit="s",
        )
        self._rows = self._meter.create_up_down_counter(
            "ml_signal_training_rows_materialized",
            description="Number of rows materialized (inserted or updated)",
        )

    async def _setup(self) -> None:
        self._pool = await create_db_pool(self.settings.database_url, min_size=1, max_size=4)
        logger.info("ml_signal_training.setup_complete")

    async def _teardown(self) -> None:
        if self._pool:
            await self._pool.close()

    async def _run(self) -> None:
        """One-shot materialization entry point.

        Catches all exceptions at the top level so systemd Type=oneshot exits 0,
        ensuring the timer fires again the following night regardless of failures.
        """
        t0 = _time.perf_counter()
        inserted = 0
        updated = 0

        try:
            # Phase A: INSERT new rows for previous trading day
            inserted = await self._phase_a_insert()

            # Phase B: UPDATE backfill for unresolved rows (30-day lookback)
            updated = await self._phase_b_backfill()

            # Phase C: Emit metrics
            self._cycles.add(1)
            self._rows.add(inserted, {"phase": "insert"})
            self._rows.add(updated, {"phase": "update"})
            self._duration.record(_time.perf_counter() - t0)

            logger.info(
                "ml_signal_training.complete",
                inserted=inserted,
                updated=updated,
                duration_seconds=_time.perf_counter() - t0,
            )

        except Exception as e:
            self._errors.add(1)
            logger.error("ml_signal_training.failed", error=str(e))
            # Swallow exception — systemd oneshot must exit 0

    async def _phase_a_insert(self) -> int:
        """Phase A: INSERT new rows for previous trading day.

        Returns:
            Number of rows inserted.
        """
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        async with self._pool.acquire() as conn:
            # Extract and flatten from trading_signals JSONB, LEFT JOIN signal_ledger for outcomes
            sql = """
            INSERT INTO ml_signal_training (
                ts, signal_id, symbol, timeframe, setup_plugin,
                pnl_r, win_label, outcome,
                existing_confidence, ctf_score, ctf_trend_alignment, ctf_structure_alignment,
                ctf_regime_agreement, ctf_fvg_alignment, ctf_ob_alignment,
                vix_level, vix_z, eq_spread_z, eq_pairs_confirming,
                ctf_momentum_divergence, ctf_sr_confluence, ctf_hmm_regime_agreement,
                ctf_volatility_divergence, ctf_orderflow_alignment, exhaustion_score,
                profile, hmm_regime, session_type,
                atr_pct, volume_z_score, tod_multiplier
            )
            SELECT
                f.ts,
                (tf_sig.value->>'signal_id')::uuid,
                f.symbol,
                f.tf,
                (tf_sig.value->>'plugin')::text,
                sl.counterfactual_pnl_r AS pnl_r,
                (sl.counterfactual_pnl_r > 0),
                (CASE WHEN sl.counterfactual_pnl_r IS NULL THEN NULL WHEN sl.counterfactual_pnl_r > 0 THEN 'win' ELSE 'loss' END) AS outcome,
                (tf_sig.value->>'calibrated_confidence')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_score')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_trend_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_structure_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_regime_agreement')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_fvg_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_ob_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'vix_level')::float8,
                (tf_sig.value->'features_snapshot'->>'vix_z')::float8,
                (tf_sig.value->'features_snapshot'->>'eq_spread_z')::float8,
                (tf_sig.value->'features_snapshot'->>'eq_pairs_confirming')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_momentum_divergence')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_sr_confluence')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_hmm_regime_agreement')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_volatility_divergence')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_orderflow_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'exhaustion_score')::float8,
                (tf_sig.value->'features_snapshot'->>'profile')::text,
                (f.regime_features->>'hmm_regime')::int,
                f.session_type,
                (f.technical_indicators->>'atr_pct')::float8,
                (f.technical_indicators->>'volume_z_score')::float8,
                COALESCE((tf_sig.value->>'tod_multiplier')::float8, 1.0)
            FROM intelligence_features f
            CROSS JOIN LATERAL jsonb_array_elements(f.trading_signals) AS tf_sig(value)
            LEFT JOIN signal_ledger sl
                ON sl.signal_id::text = tf_sig.value->>'signal_id'
            WHERE f.ts >= (date_trunc('day', NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day')
                AND f.ts < date_trunc('day', NOW() AT TIME ZONE 'UTC')
                AND f.feature_schema_version >= 2
            ON CONFLICT (ts, signal_id) DO NOTHING
            """

            result = await conn.execute(sql)
            # result format: "INSERT 0 N" or "UPDATE N"
            if result.startswith("INSERT"):
                parts = result.split()
                if len(parts) >= 3:
                    return int(parts[2])
            return 0

    async def _phase_b_backfill(self) -> int:
        """Phase B: UPDATE backfill for unresolved rows (outcome backfill strategy).

        Uses UPSERT pattern over 30-day lookback to catch late-resolving outcomes.
        Only updates rows where win_label IS NULL and outcome is now available.

        Returns:
            Number of rows updated.
        """
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        async with self._pool.acquire() as conn:
            # Same SELECT as Phase A, but over wider window and with DO UPDATE
            sql = """
            INSERT INTO ml_signal_training (
                ts, signal_id, symbol, timeframe, setup_plugin,
                pnl_r, win_label, outcome,
                existing_confidence, ctf_score, ctf_trend_alignment, ctf_structure_alignment,
                ctf_regime_agreement, ctf_fvg_alignment, ctf_ob_alignment,
                vix_level, vix_z, eq_spread_z, eq_pairs_confirming,
                ctf_momentum_divergence, ctf_sr_confluence, ctf_hmm_regime_agreement,
                ctf_volatility_divergence, ctf_orderflow_alignment, exhaustion_score,
                profile, hmm_regime, session_type,
                atr_pct, volume_z_score, tod_multiplier
            )
            SELECT
                f.ts,
                (tf_sig.value->>'signal_id')::uuid,
                f.symbol,
                f.tf,
                (tf_sig.value->>'plugin')::text,
                sl.counterfactual_pnl_r AS pnl_r,
                (sl.counterfactual_pnl_r > 0),
                (CASE WHEN sl.counterfactual_pnl_r IS NULL THEN NULL WHEN sl.counterfactual_pnl_r > 0 THEN 'win' ELSE 'loss' END) AS outcome,
                (tf_sig.value->>'calibrated_confidence')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_score')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_trend_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_structure_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_regime_agreement')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_fvg_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_ob_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'vix_level')::float8,
                (tf_sig.value->'features_snapshot'->>'vix_z')::float8,
                (tf_sig.value->'features_snapshot'->>'eq_spread_z')::float8,
                (tf_sig.value->'features_snapshot'->>'eq_pairs_confirming')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_momentum_divergence')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_sr_confluence')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_hmm_regime_agreement')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_volatility_divergence')::float8,
                (tf_sig.value->'features_snapshot'->>'ctf_orderflow_alignment')::float8,
                (tf_sig.value->'features_snapshot'->>'exhaustion_score')::float8,
                (tf_sig.value->'features_snapshot'->>'profile')::text,
                (f.regime_features->>'hmm_regime')::int,
                f.session_type,
                (f.technical_indicators->>'atr_pct')::float8,
                (f.technical_indicators->>'volume_z_score')::float8,
                COALESCE((tf_sig.value->>'tod_multiplier')::float8, 1.0)
            FROM intelligence_features f
            CROSS JOIN LATERAL jsonb_array_elements(f.trading_signals) AS tf_sig(value)
            LEFT JOIN signal_ledger sl
                ON sl.signal_id::text = tf_sig.value->>'signal_id'
            WHERE f.ts >= (NOW() AT TIME ZONE 'UTC' - INTERVAL '30 days')
                AND f.ts < date_trunc('day', NOW() AT TIME ZONE 'UTC')
                AND f.feature_schema_version >= 2
            ON CONFLICT (ts, signal_id) DO UPDATE SET
                pnl_r = EXCLUDED.pnl_r,
                win_label = (EXCLUDED.pnl_r > 0),
                outcome = EXCLUDED.outcome,
                materialized_at = NOW()
            WHERE ml_signal_training.signal_id = EXCLUDED.signal_id
                AND ml_signal_training.win_label IS NULL
                AND EXCLUDED.pnl_r IS NOT NULL
            """

            result = await conn.execute(sql)
            # result format: "INSERT 0 N" or "UPDATE N"
            if result.startswith("UPDATE"):
                parts = result.split()
                if len(parts) >= 2:
                    return int(parts[1])
            return 0

    async def start(self) -> None:
        """Entry point for systemd oneshot service.

        Catches all exceptions and logs them — systemd timer must exit 0
        to fire again the next night.
        """
        try:
            await self._setup()
            await self._run()
        except Exception as e:
            logger.error("ml_signal_training.top_level_error", error=str(e))
            self._errors.add(1)
        finally:
            await self._teardown()
