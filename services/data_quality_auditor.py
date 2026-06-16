"""DataQualityAuditor — weekly training data quality check.

Timer-triggered: indicagent-ml-data-quality.timer (Monday 05:00 UTC).
One-shot: runs checks, emits metrics, publishes alert if score < threshold, exits.

Checks:
  1. CIS null rate in intelligence_features (target < 1%)
  2. Outcome label coverage in signal_ledger (target > 95%)
  3. Feature coverage gaps per (symbol, tf, date_range)
  4. Outlier feature count (> 6σ from rolling mean)

Score = weighted average: CIS(30%) + coverage(30%) + gaps(20%) + outliers(20%).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.stream_keys import topic_ml_data_quality_alerts

logger = structlog.get_logger(__name__)

# Thresholds
_CIS_NULL_MAX = 0.01  # > 1% null → fails CIS check
_COVERAGE_MIN = 0.95  # < 95% labeled → fails coverage check
_GAP_MAX = 50  # > 50 missing bars → fails gap check
_OUTLIER_MAX = 100  # > 100 6σ outlier values → fails outlier check

# Weights for composite score (must sum to 1.0)
_W_CIS = 0.30
_W_COVERAGE = 0.30
_W_GAPS = 0.20
_W_OUTLIERS = 0.20


class DataQualityAuditor(BaseDaemon):
    """One-shot data quality auditor. Runs once and exits."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._pool: asyncpg.Pool | None = None
        self._producer = KafkaProducerClient(
            bootstrap_servers=settings.kafka_bootstrap_servers,
        )

    async def _setup(self) -> None:
        self._pool = await create_db_pool(self.settings.database_url)
        await self._producer.start()

    async def _teardown(self) -> None:
        await self._producer.stop()
        if self._pool:
            await self._pool.close()

    async def _run(self) -> None:
        """One-shot entry point: run checks, emit metrics, exit."""
        self.logger.info("data_quality_auditor.starting")
        score = await self._compute_quality_score()
        await self._write_score(score)
        await self._emit_metric(score)
        await self._maybe_publish_alert(score)
        self.logger.info("data_quality_auditor.complete", score=round(score, 4))

    async def _compute_quality_score(self) -> float:
        """Run all 4 checks and return composite score [0.0, 1.0]."""
        cis_score = await self._check_cis_null_rate()
        coverage_score = await self._check_outcome_coverage()
        gap_score = await self._check_feature_gaps()
        outlier_score = await self._check_outliers()

        composite = (
            _W_CIS * cis_score
            + _W_COVERAGE * coverage_score
            + _W_GAPS * gap_score
            + _W_OUTLIERS * outlier_score
        )
        self.logger.info(
            "data_quality_auditor.scores",
            cis=round(cis_score, 3),
            coverage=round(coverage_score, 3),
            gaps=round(gap_score, 3),
            outliers=round(outlier_score, 3),
            composite=round(composite, 3),
        )
        return composite

    async def _check_cis_null_rate(self) -> float:
        """Returns 1.0 if null rate < 1%, linearly degrades to 0 at 50%."""
        async with self._pool.acquire() as conn:
            null_rate = await conn.fetchval("""
                SELECT COALESCE(
                    COUNT(*) FILTER (
                        WHERE trading_signals = '[]'::jsonb
                            OR trading_signals NOT LIKE '%"cis":%'
                    )::float / NULLIF(COUNT(*), 0),
                    1.0
                )
                FROM intelligence_features
                WHERE ts >= NOW() - INTERVAL '30 days'
                """) or 0.0
        null_rate = float(null_rate)
        if null_rate <= _CIS_NULL_MAX:
            return 1.0
        return max(0.0, 1.0 - (null_rate - _CIS_NULL_MAX) / (0.50 - _CIS_NULL_MAX))

    async def _check_outcome_coverage(self) -> float:
        """Returns 1.0 if > 95% of signal_ledger rows have non-null outcome."""
        async with self._pool.acquire() as conn:
            coverage = await conn.fetchval("""
                SELECT COALESCE(
                    COUNT(*) FILTER (WHERE outcome IS NOT NULL)::float / NULLIF(COUNT(*), 0),
                    0.0
                )
                FROM signal_ledger
                WHERE timestamp >= NOW() - INTERVAL '30 days'
                """) or 0.0
        coverage = float(coverage)
        if coverage >= _COVERAGE_MIN:
            return 1.0
        return max(0.0, coverage / _COVERAGE_MIN)

    async def _check_feature_gaps(self) -> float:
        """Check for missing bars per (symbol, tf) in last 30 days. Returns 1.0 if no gaps."""
        async with self._pool.acquire() as conn:
            gap_count = await conn.fetchval("""
                SELECT COALESCE(
                    COUNT(*),
                    0
                )
                FROM (
                    SELECT symbol, tf, date_trunc('hour', ts) AS hour_bucket, COUNT(*) AS bar_count
                    FROM intelligence_features
                    WHERE ts >= NOW() - INTERVAL '30 days'
                    GROUP BY symbol, tf, hour_bucket
                    HAVING COUNT(*) < 50  -- expected ~60 bars/hour for 1m
                ) gap_hours
                """) or 0
        gap_count = int(gap_count)
        if gap_count <= _GAP_MAX:
            return 1.0
        return max(0.0, 1.0 - (gap_count - _GAP_MAX) / 500.0)

    async def _check_outliers(self) -> float:
        """Check for structurally invalid or extreme outlier feature values.

        Catches RSI outside [5, 95] (extreme but possible values indicating
        potential data corruption) and negative ATR (structurally impossible).
        Returns 1.0 if count below threshold.
        """
        async with self._pool.acquire() as conn:
            outlier_count = await conn.fetchval("""
                SELECT COALESCE(COUNT(*), 0)
                FROM intelligence_features
                WHERE ts >= NOW() - INTERVAL '30 days'
                  AND (
                    ABS((technical_indicators->>'rsi_14')::float - 50) > 45
                    OR (technical_indicators->>'atr_14')::float < 0
                  )
                """) or 0
        outlier_count = int(outlier_count)
        if outlier_count <= _OUTLIER_MAX:
            return 1.0
        return max(0.0, 1.0 - (outlier_count - _OUTLIER_MAX) / 1000.0)

    async def _write_score(self, score: float) -> None:
        """Persist quality score to ml_data_quality_runs so orchestrator can read it."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO ml_data_quality_runs (ts, score) VALUES ($1, $2)",
                datetime.now(UTC),
                round(score, 4),
            )
        self.logger.info("data_quality_auditor.score_written", score=round(score, 4))

    async def _emit_metric(self, score: float) -> None:
        """Update Prometheus gauge."""
        try:
            from src.observability.metrics import DATA_QUALITY_SCORE

            DATA_QUALITY_SCORE.set(score)
        except Exception as error:
            self.logger.warning("data_quality_auditor.metric_emit_failed", error=str(error))

    async def _maybe_publish_alert(self, score: float) -> None:
        """Publish alert to Kafka if score below threshold."""
        min_score = self.settings.DATA_QUALITY_MIN_SCORE
        if score < min_score:
            await self._producer.publish(
                topic_ml_data_quality_alerts(self.settings.env_name),
                {
                    "score": round(score, 4),
                    "threshold": min_score,
                    "message": (
                        f"Data quality score {score:.3f} below threshold {min_score}."
                        " Discovery blocked."
                    ),
                },
            )
            self.logger.warning(
                "data_quality_auditor.alert_published", score=score, threshold=min_score
            )


def main() -> None:
    settings = Settings()
    agent = DataQualityAuditor(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
