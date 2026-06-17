"""
KS Distribution Drift Monitor — QUAL-09

Detects feature distribution drift using the two-sample Kolmogorov-Smirnov test.
When key I1/I4 feature distributions shift from baseline, writes a penalty severity
to the drift_state DB table so signal_generator can automatically reduce confidence.

Design decisions:
- Reference window: KS_REFERENCE_WINDOW_DAYS (37d) for stable baseline
- Current window:   KS_CURRENT_WINDOW_DAYS (7d) for recent drift detection
- Severity logic:   critical if p < 0.01, warning if p < 0.05
- Recovery:         2 consecutive clean cycles → set severity='none' in drift_state
                    1 clean cycle after warning → leave existing severity (partial recovery)
- Run interval:     every 4 hours via run_forever()

Phase 30: Redis dependency removed. drift_state table replaces Redis keys.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from opentelemetry import metrics as _otel_metrics
from scipy import stats

# drift_ks Redis key function removed in Phase 30 — replaced by drift_state DB table

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRIFT_PENALTIES: dict[str, float] = {
    "none": 1.0,
    "warning": 0.85,
    "critical": 0.70,
}

KS_FEATURES: list[str] = [
    "rsi_14",
    "macd_histogram_12_26_9",
    "rel_volume",
    "hurst_exponent",
    "entropy_quality",
    "garch_sigma",
    "trend_regime",
    "hmm_regime_0",
]

KS_REFERENCE_WINDOW_DAYS: int = 37
KS_CURRENT_WINDOW_DAYS: int = 7

# Minimum rows required before running KS test (warming up below this)
_KS_MIN_REFERENCE_ROWS: int = 30

# Consecutive clean cycles required to fully restore drift key
_CLEAN_CYCLES_FOR_RESTORE: int = 2

# DB upsert interval — no TTL needed (drift_state rows persist until explicitly updated)

# ---------------------------------------------------------------------------
# OTel metrics
# ---------------------------------------------------------------------------

_ks_meter = _otel_metrics.get_meter("indicagent")

KS_CHECKS_TOTAL = _ks_meter.create_counter(
    "drift_ks_checks_total",
    description="KS checks run",
)
KS_ALERTS_TOTAL = _ks_meter.create_counter(
    "drift_ks_alerts_total",
    description="KS alerts fired",
)
KS_CHECK_DURATION = _ks_meter.create_histogram(
    "drift_ks_check_duration_seconds",
    description="KS check duration",
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DriftCheckResult:
    """Result of a single KS drift check for one symbol/TF."""

    severity: str  # "none", "warning", or "critical"
    ks_statistic: float | None = None
    ks_pvalue: float | None = None
    feature_name: str | None = None  # worst-case feature that triggered alert
    reference_n: int = 0
    current_n: int = 0
    checked_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


# ---------------------------------------------------------------------------
# KSDriftMonitor
# ---------------------------------------------------------------------------


class KSDriftMonitor:
    """Two-sample KS drift monitor for I1/I4 feature distributions.

    Reads feature vectors from intelligence_features hypertable, computes
    KS statistics, and writes severity flags to the drift_state DB table.
    The signal_generator reads these flags (via _refresh_drift_penalties_from_db())
    to automatically apply confidence penalties.

    Args:
        db_pool: asyncpg connection pool (from DatabaseManager.pool).
        env_prefix: Environment prefix for logging context.
        timeframes: List of timeframes to monitor. Defaults to ["1m", "5m", "15m", "1h"].
        symbols: List of symbols to monitor. Populated at run_forever() call time
                 if not provided here.
    """

    def __init__(
        self,
        db_pool: Any,
        env_prefix: str,
        timeframes: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> None:
        self.db_pool = db_pool
        self.env_prefix = env_prefix
        self.timeframes = timeframes or ["1m", "5m", "15m", "1h"]
        self.symbols = symbols or []
        self.logger = structlog.get_logger(__name__)

        # Recovery tracking: (symbol, tf) → consecutive clean cycle count
        self._clean_cycles: dict[tuple[str, str], int] = {}

    # ------------------------------------------------------------------
    # Core KS check
    # ------------------------------------------------------------------

    async def check_symbol_tf(self, symbol: str, tf: str) -> DriftCheckResult:
        """Run KS drift check for a single symbol/TF pair.

        Fetches reference (37d) and current (7d) windows from
        intelligence_features, runs ks_2samp on each KS_FEATURES field,
        and writes the worst-case severity to Redis.

        Returns DriftCheckResult with severity="none" when:
        - Reference window has < 30 rows (warming up)
        - All features pass p >= 0.05 (no drift detected)
        """
        import time as _time

        t0 = _time.monotonic()

        try:
            reference_rows, current_rows = await self._fetch_windows(symbol, tf)
        except Exception as error:
            self.logger.warning(
                "KS fetch failed",
                symbol=symbol,
                timeframe=tf,
                error=str(error),
            )
            return DriftCheckResult(severity="none", reference_n=0, current_n=0)

        KS_CHECKS_TOTAL.add(1, {"symbol": symbol, "timeframe": tf})

        ref_n = len(reference_rows)
        cur_n = len(current_rows)

        # Not enough data — warming up
        if ref_n < _KS_MIN_REFERENCE_ROWS:
            self.logger.debug(
                "KS skip: insufficient reference data",
                symbol=symbol,
                timeframe=tf,
                reference_n=ref_n,
            )
            KS_CHECK_DURATION.record(_time.monotonic() - t0)
            return DriftCheckResult(severity="none", reference_n=ref_n, current_n=cur_n)

        if cur_n == 0:
            KS_CHECK_DURATION.record(_time.monotonic() - t0)
            return DriftCheckResult(severity="none", reference_n=ref_n, current_n=cur_n)

        # Run KS test on each feature — find worst-case p-value
        worst_severity = "none"
        worst_stat: float | None = None
        worst_p: float | None = None
        worst_feature: str | None = None

        for feature in KS_FEATURES:
            ref_vals = [row[feature] for row in reference_rows if row.get(feature) is not None]
            cur_vals = [row[feature] for row in current_rows if row.get(feature) is not None]
            if len(ref_vals) < 10 or len(cur_vals) < 5:
                continue
            ks_stat, p_value = stats.ks_2samp(ref_vals, cur_vals)
            severity = _classify_ks_severity(p_value)
            if _severity_rank(severity) > _severity_rank(worst_severity):
                worst_severity = severity
                worst_stat = float(ks_stat)
                worst_p = float(p_value)
                worst_feature = feature

        KS_CHECK_DURATION.record(_time.monotonic() - t0)

        result = DriftCheckResult(
            severity=worst_severity,
            ks_statistic=worst_stat,
            ks_pvalue=worst_p,
            feature_name=worst_feature,
            reference_n=ref_n,
            current_n=cur_n,
        )

        # Write Redis key + handle recovery
        await self._write_drift_key(symbol, tf, result)

        if worst_severity != "none":
            KS_ALERTS_TOTAL.add(1, {"symbol": symbol, "timeframe": tf, "severity": worst_severity})
            self.logger.info(
                "KS drift detected",
                symbol=symbol,
                timeframe=tf,
                severity=worst_severity,
                feature=worst_feature,
                ks_stat=round(worst_stat or 0, 4),
                p_value=round(worst_p or 0, 6),
            )

        return result

    # ------------------------------------------------------------------
    # DB fetch
    # ------------------------------------------------------------------

    async def _fetch_windows(self, symbol: str, tf: str) -> tuple[list[dict], list[dict]]:
        """Fetch reference and current windows from intelligence_features."""
        now = datetime.now(tz=UTC)
        ref_cutoff = now - timedelta(days=KS_REFERENCE_WINDOW_DAYS)
        cur_cutoff = now - timedelta(days=KS_CURRENT_WINDOW_DAYS)

        feature_cols = ", ".join(KS_FEATURES)
        query = f"""
            SELECT {feature_cols}
            FROM intelligence_features
            WHERE symbol = $1
              AND tf = $2
              AND ts >= $3
              AND ts < $4
            ORDER BY ts DESC
            LIMIT 5000
        """  # noqa: S608

        async with self.db_pool.acquire() as conn:
            reference_rows = await conn.fetch(query, symbol, tf, ref_cutoff, cur_cutoff)
            current_rows = await conn.fetch(query, symbol, tf, cur_cutoff, now)

        return list(reference_rows), list(current_rows)

    # ------------------------------------------------------------------
    # Redis key management + recovery
    # ------------------------------------------------------------------

    async def _write_drift_key(self, symbol: str, tf: str, result: DriftCheckResult) -> None:
        """Write severity to drift_state DB table. Manage recovery mechanic.

        Phase 30: Writes to drift_state DB table instead of Redis.

        Recovery mechanic:
        - Clean cycle (severity="none"): increment clean counter.
          After _CLEAN_CYCLES_FOR_RESTORE consecutive clean cycles → upsert 'none' to DB.
        - Drift detected: reset clean counter, upsert new severity to DB.
        """
        pair = (symbol, tf)

        if result.severity == "none":
            # Increment clean cycle counter
            self._clean_cycles[pair] = self._clean_cycles.get(pair, 0) + 1
            if self._clean_cycles[pair] >= _CLEAN_CYCLES_FOR_RESTORE:
                # Fully recovered — write 'none' to DB
                await self._upsert_drift_state(symbol, tf, "none")
                self._clean_cycles.pop(pair, None)
                self.logger.info("KS drift recovered", symbol=symbol, timeframe=tf)
            # else: leave existing row in place (partial recovery — not yet clean enough)
        else:
            # Drift detected — reset clean counter, upsert new severity
            self._clean_cycles[pair] = 0
            await self._upsert_drift_state(symbol, tf, result.severity)

    async def _upsert_drift_state(self, symbol: str, tf: str, ks_severity: str) -> None:
        """Upsert ks_severity into drift_state table for (symbol, tf)."""
        query = """
            INSERT INTO drift_state (symbol, tf, ks_severity, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (symbol, tf)
            DO UPDATE SET ks_severity = EXCLUDED.ks_severity,
                          updated_at = NOW()
        """  # noqa: S608
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(query, symbol, tf, ks_severity)
        except Exception as error:
            self.logger.warning(
                "drift_state upsert failed",
                symbol=symbol,
                tf=tf,
                ks_severity=ks_severity,
                error=str(error),
            )

    # ------------------------------------------------------------------
    # run_forever
    # ------------------------------------------------------------------

    async def run_forever(
        self, symbols: list[str] | None = None, interval_seconds: int = 4 * 3600
    ) -> None:
        """Run KS checks for all symbol/TF pairs every interval_seconds.

        Args:
            symbols: Override self.symbols if provided.
            interval_seconds: Check interval in seconds (default: 4h).
        """
        active_symbols = symbols or self.symbols
        self.logger.info(
            "KS drift monitor starting",
            symbols=active_symbols,
            timeframes=self.timeframes,
            interval_hours=interval_seconds // 3600,
        )

        while True:
            cycle_start = asyncio.get_event_loop().time()
            for symbol in active_symbols:
                for tf in self.timeframes:
                    try:
                        await self.check_symbol_tf(symbol, tf)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        self.logger.warning(
                            "KS check error",
                            symbol=symbol,
                            timeframe=tf,
                            error=str(error),
                        )
            elapsed = asyncio.get_event_loop().time() - cycle_start
            sleep_secs = max(0, interval_seconds - elapsed)
            try:
                await asyncio.sleep(sleep_secs)
            except asyncio.CancelledError:
                break


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_ks_severity(p_value: float) -> str:
    """Map KS p-value to drift severity string."""
    if p_value < 0.01:
        return "critical"
    if p_value < 0.05:
        return "warning"
    return "none"


def _severity_rank(severity: str) -> int:
    """Numeric rank for severity comparison (higher = worse)."""
    return {"none": 0, "warning": 1, "critical": 2}.get(severity, 0)
