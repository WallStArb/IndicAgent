"""FeatureValidationAnalyzer — daily IC/p-value decision agent (Phase 82 D-05).

Systemd Type=oneshot service invoked by indicagent-feature-validation.timer (daily 02:00 ET).

Responsibilities:
  1. Query shadow_registry for all registered plugins.
  2. For each (plugin_name, timeframe, regime_type) slice, fetch joined
     intelligence_features + signal_ledger outcome data (excluding backfill rows
     and unresolved outcomes).
  3. Skip slices with n < 30 (insufficient data gate).
  4. Call validate_backtest_results() from tools.validate_i6_backtest for IC/p-value.
  5. Insert one row into validation_results per slice (asyncpg parameter binding).
  6. Update shadow_registry.promotion_evidence with the latest decision evidence.
  7. Increment FEATURE_VALIDATION_DECISIONS_TOTAL counter per decision written.
  8. Individual slice failures are caught and logged — do NOT crash the full run.

Computation/governance separation:
  This agent produces *evidence* (VALIDATED/TWEAK/KILL decisions) written to
  validation_results and shadow_registry.promotion_evidence. Phase 75's
  ShadowAuditorAgent reads this evidence and *acts* on it (promotion/demotion).
  This agent never promotes or demotes plugins directly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pandas as pd
import structlog

from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.core.service_utils import setup_service_logging
from src.observability.metrics import FEATURE_VALIDATION_DECISIONS_TOTAL
from tools.validate_i6_backtest import validate_backtest_results

logger = structlog.get_logger(__name__)

# Minimum sample size — slices below this are skipped entirely
_MIN_N = 30

# Plugin-bearing component_types registered in shadow_registry
_PLUGIN_BEARING_TYPES = frozenset({"i7_plugin"})

# Timeframes to validate per plugin
_TIMEFRAMES = ["1m", "5m", "15m", "1h"]

# Cap concurrent plugin validations — each acquires a DB connection per slice
_MAX_CONCURRENT_PLUGINS = 8

# Regime type values to validate (plus None = global slice)
_REGIME_TYPES: list[str | None] = [None, "trending", "ranging", "volatile"]

# Field name used for IC correlation — intelligence_features.i6 JSONB sub-key
# Falls back to the plugin_name for non-I6 plugins (e.g., I7 shadow scores).
_DEFAULT_FIELD_SUFFIX = "score"

# Canonical decision values — match validation_results CHECK constraint
_DECISION_VALIDATED = "VALIDATED"
_DECISION_TWEAK = "TWEAK"
_DECISION_KILL = "KILL"


class FeatureValidationAnalyzer:
    """Daily IC/p-value compute agent.

    Instantiated by the oneshot entrypoint with a Settings object.
    Manages its own asyncpg pool lifecycle.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        self._pool = await create_db_pool(self._settings.database_url)
        logger.info("feature_validation.setup_complete")

    async def _teardown(self) -> None:
        if self._pool:
            await self._pool.close()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Orchestrate setup → run → teardown. Swallows top-level exceptions
        so systemd oneshot exits 0 and the timer fires again the next day."""
        setup_service_logging("logs/feature_validation_analyzer.log")
        await self._setup()
        try:
            results = await self.run()
            # Summarise by decision
            counts: dict[str, int] = {}
            for row in results:
                d = row.get("decision", "UNKNOWN")
                counts[d] = counts.get(d, 0) + 1
            logger.info(
                "feature_validation.run_complete",
                total=len(results),
                by_decision=counts,
            )
        except Exception:
            logger.exception("feature_validation.error_top_level")
        finally:
            await self._teardown()

    async def run(self) -> list[dict[str, Any]]:
        """Run validation for all registered plugins across (tf, regime_type) slices.

        Returns:
            List of decision dicts written to validation_results.
        """
        assert self._pool is not None, "Call _setup() before run()"

        plugins = await self._query_plugins()
        logger.info("feature_validation.plugins_found", count=len(plugins))

        sem = asyncio.Semaphore(_MAX_CONCURRENT_PLUGINS)

        async def _bounded(p: str) -> list[dict[str, Any]]:
            async with sem:
                return await self._validate_all_slices(p)

        results = await asyncio.gather(*[_bounded(p) for p in plugins], return_exceptions=True)
        return [d for r in results if isinstance(r, list) for d in r]

    async def _validate_all_slices(self, plugin_name: str) -> list[dict[str, Any]]:
        """Validate all (tf, regime_type) slices for one plugin."""
        decisions: list[dict[str, Any]] = []
        for timeframe in _TIMEFRAMES:
            for regime_type in _REGIME_TYPES:
                try:
                    decision = await self._validate_slice(
                        plugin_name=plugin_name,
                        timeframe=timeframe,
                        regime_type=regime_type,
                    )
                    if decision is not None:
                        decisions.append(decision)
                except Exception:
                    logger.exception(
                        "feature_validation.slice_error",
                        plugin_name=plugin_name,
                        timeframe=timeframe,
                        regime_type=regime_type,
                    )
        return decisions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _query_plugins(self) -> list[str]:
        """Return distinct plugin names from shadow_registry with plugin-bearing types."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT component_name
                FROM shadow_registry
                WHERE component_type = ANY($1::text[])
                ORDER BY component_name
                """,
                list(_PLUGIN_BEARING_TYPES),
            )
        return [row["component_name"] for row in rows]

    async def _fetch_slice_df(
        self,
        plugin_name: str,
        timeframe: str,
        regime_type: str | None,
    ) -> pd.DataFrame:
        """Fetch joined dataset for one (plugin, tf, regime_type) slice.

        Joins intelligence_features (i7 shadow scores) with signal_ledger outcomes.
        Excludes backfill rows and rows without resolved outcomes.

        V2.11_ACTIVATED: IC metric is raw_confidence (per-plugin shadow score).
        Previously: features_snapshot JSONB field under plugin_name key (dropped in 3-table migration).
        """
        if regime_type is not None:
            query = """
                SELECT
                    sl.raw_confidence AS feature_value,
                    sl.counterfactual_pnl_r AS pnl_r,
                    sl.hmm_regime_at_fire AS hmm_regime
                FROM signal_ledger sl
                WHERE sl.setup_plugin = $1
                  AND sl.tf = $2
                  AND sl.counterfactual_pnl_r IS NOT NULL
                  AND sl.is_backfill = false
                  AND sl.raw_confidence IS NOT NULL
                  AND sl.hmm_regime_at_fire = $3
                LIMIT 50000
            """
            params = [plugin_name, timeframe, regime_type]
        else:
            query = """
                SELECT
                    sl.raw_confidence AS feature_value,
                    sl.counterfactual_pnl_r AS pnl_r,
                    sl.hmm_regime_at_fire AS hmm_regime
                FROM signal_ledger sl
                WHERE sl.setup_plugin = $1
                  AND sl.tf = $2
                  AND sl.counterfactual_pnl_r IS NOT NULL
                  AND sl.is_backfill = false
                  AND sl.raw_confidence IS NOT NULL
                LIMIT 50000
            """
            params = [plugin_name, timeframe]

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        if not rows:
            return pd.DataFrame(columns=["feature_value", "pnl_r", "hmm_regime"])

        df = pd.DataFrame(
            [dict(row) for row in rows],
            columns=["feature_value", "pnl_r", "hmm_regime"],
        )
        # feature_value comes from JSONB as str — cast to float, drop non-numeric
        df["feature_value"] = pd.to_numeric(df["feature_value"], errors="coerce")
        df = df.dropna(subset=["feature_value", "pnl_r"])
        # Rename so validate_backtest_results receives field_name as column name
        df = df.rename(columns={"feature_value": plugin_name})
        return df

    async def _validate_slice(
        self,
        plugin_name: str,
        timeframe: str,
        regime_type: str | None,
    ) -> dict[str, Any] | None:
        """Validate one slice. Returns decision dict or None if skipped (n < 30)."""
        df = await self._fetch_slice_df(plugin_name, timeframe, regime_type)

        if len(df) < _MIN_N:
            logger.debug(
                "feature_validation.slice_skipped",
                plugin_name=plugin_name,
                timeframe=timeframe,
                regime_type=regime_type,
                n=len(df),
                reason="below_min_n",
            )
            return None

        result = validate_backtest_results(
            df=df,
            field_name=plugin_name,
            min_ic=0.05,
            alpha=0.01,
            min_n=_MIN_N,
        )

        # Normalise decision: validate_backtest_results may return extended strings
        # like "KILL (field missing from backtest output)". Normalise to the three
        # canonical CHECK constraint values.
        raw_decision = result.decision
        if raw_decision.startswith(_DECISION_VALIDATED):
            decision = _DECISION_VALIDATED
        elif raw_decision.startswith(_DECISION_TWEAK):
            decision = _DECISION_TWEAK
        else:
            decision = _DECISION_KILL

        computed_at = datetime.now(UTC)

        # Increment Prometheus counter per decision
        FEATURE_VALIDATION_DECISIONS_TOTAL.add(1, {"decision": decision})

        # Build evidence dict for shadow_registry.promotion_evidence (passed as
        # dict — NOT json.dumps per CLAUDE.md asyncpg rule)
        evidence = {
            "decision": decision,
            "ic": result.ic,
            "p_value": result.p_value,
            "n": result.n,
            "timeframe": timeframe,
            "regime_type": regime_type,
            "computed_at": computed_at.isoformat(),
        }

        async with self._pool.acquire() as conn:
            # Insert validation result row
            await conn.execute(
                """
                INSERT INTO validation_results
                    (plugin_name, timeframe, regime_type, ic, p_value, n,
                     decision, bonferroni_corrected, computed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                plugin_name,
                timeframe,
                regime_type,
                result.ic,
                result.p_value,
                result.n,
                decision,
                True,  # bonferroni_corrected — alpha=0.01 is Bonferroni-corrected
                computed_at,
            )

            # Update shadow_registry.promotion_evidence for this component
            # Pass evidence dict directly — asyncpg serialises JSONB from Python dict
            await conn.execute(
                """
                UPDATE shadow_registry
                SET promotion_evidence = $2
                WHERE component_name = $1
                """,
                plugin_name,
                evidence,
            )

        logger.info(
            "feature_validation.slice_written",
            plugin_name=plugin_name,
            timeframe=timeframe,
            regime_type=regime_type,
            decision=decision,
            ic=round(result.ic, 4),
            p_value=round(result.p_value, 4),
            n=result.n,
        )

        return {
            "plugin_name": plugin_name,
            "timeframe": timeframe,
            "regime_type": regime_type,
            "decision": decision,
            "ic": result.ic,
            "p_value": result.p_value,
            "n": result.n,
            "computed_at": computed_at.isoformat(),
        }
