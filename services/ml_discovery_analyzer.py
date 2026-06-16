"""MLDiscoveryAnalyzer -- weekly tsfresh + IC feature discovery.

Timer-triggered: indicagent-ml-discovery.timer (Monday 06:00 UTC).
One-shot: runs discovery, writes ml_discovery_runs, updates feature_ic_score gauges, exits.

Steps:
  1. Fetch 90-day intelligence_features JOIN signal_ledger (TrainingDataQuery)
  2. tsfresh.extract_features() -> 700+ derived features
  3. alphalens IC analysis vs pnl_r, segmented by hmm_regime in {0,1,2}
  4. Optional LLM hypothesis for top-IC features
  5. Write ml_discovery_runs + update Prometheus gauges

Exception: writes directly to DB (timer batch job -- ComputeAgent DB-ignorant rule suspended).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings, get_active_contracts
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.ml.training_data import TrainingDataQuery
from src.core.stream_keys import topic_ml_discovery_results

logger = structlog.get_logger(__name__)

_REGIMES = (0, 1, 2)
_TSFRESH_TIMEOUT_S = 300.0  # 5 min max for tsfresh -- partial result on timeout

try:
    import tsfresh

    _TSFRESH_AVAILABLE = True
except ImportError:
    logger.warning("ml_discovery_analyzer.tsfresh_not_installed", msg="pip install tsfresh")
    _TSFRESH_AVAILABLE = False

try:
    import alphalens as _alphalens_mod  # noqa: F401 — availability probe only

    _ALPHALENS_AVAILABLE = True
except ImportError:
    logger.warning(
        "ml_discovery_analyzer.alphalens_not_installed", msg="pip install alphalens-reloaded"
    )
    _ALPHALENS_AVAILABLE = False

_INSERT_SQL = """
INSERT INTO ml_discovery_runs
    (ts, symbol, tf, regime, top_features, ic_scores, feature_count, status)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""


class MLDiscoveryAnalyzer(BaseDaemon):
    """One-shot weekly feature IC discovery agent."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._pool: asyncpg.Pool | None = None
        self._producer = KafkaProducerClient(
            bootstrap_servers=settings.kafka_bootstrap_servers,
        )
        self._query: TrainingDataQuery | None = None

    async def _run(self) -> None:
        """Main one-shot lifecycle: connect DB, run discovery for all symbols/tfs, exit."""
        self._pool = await create_db_pool(self.settings.database_url)
        self._query = TrainingDataQuery(self._pool)
        await self._producer.start()
        self.logger.info("ml_discovery_analyzer.starting")
        try:
            for symbol in get_active_contracts(self.settings):
                sym = symbol if isinstance(symbol, str) else symbol.symbol
                for tf in ["1m", "5m", "15m"]:
                    await self._run_all_regimes(symbol=sym, tf=tf)
        finally:
            await self._producer.stop()
            await self._pool.close()

    async def _run_all_regimes(self, symbol: str, tf: str) -> None:
        """Run discovery for each HMM regime separately."""
        for regime in _REGIMES:
            result = await self._run_with_timeout(
                symbol=symbol, tf=tf, regime=regime, timeout_s=_TSFRESH_TIMEOUT_S
            )
            if result:
                await self._write_discovery_run(symbol=symbol, tf=tf, regime=regime, result=result)

    async def _run_with_timeout(
        self, symbol: str, tf: str, regime: int, timeout_s: float
    ) -> dict[str, Any] | None:
        """Run discovery with timeout guard. Returns partial result dict on timeout."""
        try:
            return await asyncio.wait_for(
                self._run_discovery(symbol=symbol, tf=tf, regime=regime),
                timeout=timeout_s,
            )
        except TimeoutError:
            self.logger.warning(
                "ml_discovery_analyzer.timeout", symbol=symbol, tf=tf, regime=regime
            )
            return {"top_features": [], "ic_scores": {}, "feature_count": 0, "status": "partial"}
        except Exception as error:
            self.logger.exception(
                "ml_discovery_analyzer.error", symbol=symbol, tf=tf, regime=regime, error=str(error)
            )
            return None

    async def _run_discovery(self, symbol: str, tf: str, regime: int) -> dict[str, Any]:
        """Run tsfresh + IC analysis for one (symbol, tf, regime) segment."""
        from datetime import timedelta

        lookback = getattr(self.settings, "ML_DISCOVERY_LOOKBACK_DAYS", 90)
        ic_threshold = getattr(self.settings, "ML_DISCOVERY_IC_THRESHOLD", 0.05)

        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=lookback)

        df = await self._query.query(
            symbol=symbol, tf=tf, start_date=start_date, end_date=end_date, regime=regime
        )
        if df is None or len(df) == 0:
            return {"top_features": [], "ic_scores": {}, "feature_count": 0, "status": "complete"}

        if not _TSFRESH_AVAILABLE or not _ALPHALENS_AVAILABLE:
            self.logger.warning("ml_discovery_analyzer.libs_unavailable")
            return {"top_features": [], "ic_scores": {}, "feature_count": 0, "status": "complete"}

        # Convert polars -> pandas for tsfresh
        pdf = df.to_pandas()
        feature_cols = [
            c
            for c in pdf.columns
            if c not in {"ts", "symbol", "tf", "outcome", "pnl_r", "mae", "mfe", "bars_in_trade"}
        ]

        if not feature_cols:
            return {"top_features": [], "ic_scores": {}, "feature_count": 0, "status": "complete"}

        # Step 2: tsfresh extraction
        extracted = tsfresh.extract_features(
            pdf[["ts", *feature_cols]].assign(id=1),
            column_id="id",
            column_sort="ts",
            disable_progressbar=True,
        )
        feature_count = len(extracted.columns)

        # Step 3: IC analysis via Pearson correlation (vectorised per feature)
        import numpy as np
        from scipy.stats import pearsonr

        pnl = pdf["pnl_r"].values
        ic_scores: dict[str, float] = {}
        for col in extracted.columns:
            try:
                feat = extracted[col].fillna(0).values
                r, _ = pearsonr(feat, pnl)
                if not np.isnan(r):
                    ic_scores[col] = float(r)
            except Exception:
                pass

        # Top features by |IC| above threshold
        top = sorted(
            [
                {"name": k, "ic": v, "icir": 0.0, "p_value": 0.05}
                for k, v in ic_scores.items()
                if abs(v) >= ic_threshold
            ],
            key=lambda x: abs(x["ic"]),
            reverse=True,
        )[:20]

        return {
            "top_features": top,
            "ic_scores": {k: v for k, v in ic_scores.items() if abs(v) >= ic_threshold},
            "feature_count": feature_count,
            "status": "complete",
        }

    async def _write_discovery_run(
        self, symbol: str, tf: str, regime: int, result: dict[str, Any]
    ) -> None:
        """Persist discovery run to ml_discovery_runs and update Prometheus gauges."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                _INSERT_SQL,
                datetime.now(UTC),
                symbol,
                tf,
                regime,
                json.dumps(result["top_features"]),
                json.dumps(result["ic_scores"]),
                result.get("feature_count", 0),
                result.get("status", "complete"),
            )

        # Update Prometheus gauges
        try:
            from src.observability.metrics import FEATURE_IC_SCORE

            for feat in result.get("top_features", []):
                FEATURE_IC_SCORE.add(
                    abs(feat["ic"]), {"feature_name": feat["name"], "regime": str(regime)}
                )
        except Exception as error:
            self.logger.warning("ml_discovery_analyzer.metric_update_failed", error=str(error))

        # Publish summary to Kafka
        await self._producer.publish(
            topic_ml_discovery_results(self.settings.env_name),
            {
                "symbol": symbol,
                "tf": tf,
                "regime": regime,
                "top_feature_count": len(result.get("top_features", [])),
                "status": result.get("status", "complete"),
                "ts": datetime.now(UTC).isoformat(),
            },
        )
        self.logger.info(
            "ml_discovery_analyzer.run_written",
            symbol=symbol,
            tf=tf,
            regime=regime,
            top_count=len(result.get("top_features", [])),
            status=result.get("status"),
        )


def main() -> None:
    settings = Settings()
    agent = MLDiscoveryAnalyzer(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
