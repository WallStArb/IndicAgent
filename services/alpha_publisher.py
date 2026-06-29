#!/usr/bin/env python3
"""Alpha Publisher — oneshot that reads ensemble_alpha and publishes qualifying alpha events.

Reads ensemble_alpha rows for the current weight_version, applies direction-aware CI gates
and effective_N gate, writes qualifying rows to alpha_events (DB), and publishes to the
Kafka topic alpha.events. Shadow mode: no execution, no trade framing.

CORRECTNESS INVARIANTS:
- Preloads all ensemble_weights at execute() start into weights_cache (one query, not N+1).
- Direction-aware gate: long signals require alpha_ci_lower > 0; short require alpha_ci_upper < 0.
- Zero-weight stratum guard: rows where effective_n == 0 are skipped before CI math.
- Kafka publish: await self._producer.publish(topic_alpha_events(env), msg=payload).
  Topic is the first positional argument; msg= is the keyword argument.
- alpha_events insert uses ON CONFLICT (event_id, bar_ts) DO NOTHING (composite PK).
- top_features MUST be non-empty before insert (architecture traceability invariant).
- All numeric parameters loaded from APR via asyncpg-fetched config dict.
- event_id = BaseBatch.content_key(symbol, tf, bar_ts_ns, ensemble_version).

DAG invariant: compute (EnsembleTrainer) ≠ transport (AlphaPublisher). This service reads
DB and publishes to Kafka — it does not compute weights or score bars.

Usage:
    python services/alpha_publisher.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import format_iso_ts
from src.core.stream_keys import topic_alpha_events
from src.observability.corpus_manifest import CorpusManifest
from src.observability.metrics import (
    ALPHA_PUBLISHER_BARS_SCORED_TOTAL,
    ALPHA_PUBLISHER_EMISSIONS_TOTAL,
)
from src.observability.otel import OTelInitError, init_otel_providers

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# APR config query — asyncpg
# ---------------------------------------------------------------------------

_APR_QUERY = "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.%'"


async def _load_apr(conn: asyncpg.Connection) -> dict[str, Any]:
    """Load all alpha.* APR keys from config_state via asyncpg."""
    rows = await conn.fetch(_APR_QUERY)
    return {r["config_key"]: r["config_value"] for r in rows}


def _cfg_float(cfg: dict[str, Any], key: str, default: float) -> float:
    val = cfg.get(key)
    return float(val) if val is not None else default


def _cfg_int(cfg: dict[str, Any], key: str, default: int) -> int:
    val = cfg.get(key)
    return int(val) if val is not None else default


def _cfg_str(cfg: dict[str, Any], key: str, default: str) -> str:
    val = cfg.get(key)
    return str(val) if val is not None else default


# ---------------------------------------------------------------------------
# AlphaPublisher
# ---------------------------------------------------------------------------


class AlphaPublisher(BaseBatch):
    """Batch compute service: ensemble_alpha → alpha_events (DB) + Kafka alpha.events topic.

    Shadow mode: alpha events are written and published for external consumption only.
    No execution engine, no trade framing, no position sizing in this service.
    """

    job_name = "alpha-publisher"
    compute_version = "1.0.0"
    ensemble_version = "v1.0.0"
    _CHUNK_SIZE = 50_000

    def __init__(self, db_dsn: str, skip_kafka: bool = False) -> None:
        super().__init__(db_dsn)
        self.skip_kafka = skip_kafka

    def _threshold_for_tf(self, tf: str, cfg: dict[str, Any]) -> float:
        """Return the APR-loaded emission threshold for the given timeframe.

        Reads alpha.quant.threshold.{tf} from the pre-loaded config dict.
        Falls through to the APR-documented defaults only when the key is absent.
        """
        defaults: dict[str, float] = {
            "5m": 1.5,
            "15m": 1.2,
            "1h": 1.0,
            "1d": 0.8,
        }
        return _cfg_float(cfg, f"alpha.quant.threshold.{tf}", defaults.get(tf, 1.0))

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        """Read ensemble_alpha, enforce gates, write alpha_events, publish to Kafka."""
        manifest = CorpusManifest("alpha_publisher", Path(".planning/corpus_manifests"))
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise

    _INSERT_SQL = """
        INSERT INTO alpha_events (
            event_id, symbol, tf, bar_ts,
            ensemble_version, weight_version,
            regime, alpha_score, alpha_ci_lower, alpha_ci_upper,
            effective_n, n_features_active,
            emission_threshold, direction,
            top_features, emitted_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16
        )
        ON CONFLICT (event_id, bar_ts) DO NOTHING
    """

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        settings = Settings()
        topic = topic_alpha_events(settings.env_name)

        async with pool.acquire() as conn:
            # --- Load APR config ---
            cfg = await _load_apr(conn)
            effective_n_gate = _cfg_float(cfg, "alpha.ensemble.effective_n_gate", 3.0)
            weight_version = _cfg_str(cfg, "alpha.ensemble.weight_version", "v1")
            top_features_count = _cfg_int(cfg, "alpha.ensemble.top_features_count", 10)

            self.logger.info(
                "alpha_publisher.config_loaded",
                effective_n_gate=effective_n_gate,
                weight_version=weight_version,
                top_features_count=top_features_count,
                topic=topic,
                skip_kafka=self.skip_kafka,
            )
            manifest.set_inputs(
                ensemble_version=self.ensemble_version,
                weight_version=weight_version,
            )

            # --- Startup crash-loud gate ---
            n_alpha = await conn.fetchval(
                "SELECT count(*) FROM ensemble_alpha WHERE weight_version = $1",
                weight_version,
            )
            if not n_alpha:
                raise RuntimeError(
                    f"AlphaPublisher startup gate FAILED: ensemble_alpha is empty for "
                    f"weight_version={weight_version!r}. Run ensemble_trainer.py first."
                )

            # --- Preload weights_cache (one query, not N+1) ---
            weight_rows = await conn.fetch(
                "SELECT symbol, tf, regime, feature_name, weight FROM ensemble_weights WHERE weight_version = $1",
                weight_version,
            )
            weights_cache: dict[tuple[str, str], list[dict]] = {}
            for r in weight_rows:
                key = (r["tf"], r["regime"])
                weights_cache.setdefault(key, []).append(
                    {"feature_name": r["feature_name"], "weight": float(r["weight"])}
                )
            for key in weights_cache:
                weights_cache[key].sort(key=lambda x: abs(x["weight"]), reverse=True)

            self.logger.info(
                "alpha_publisher.weights_cache_loaded",
                n_strata=len(weights_cache),
                n_weight_rows=len(weight_rows),
            )

            # Pre-compute per-TF thresholds for SQL pre-filter (exact values from APR)
            _known_tfs = ["5m", "15m", "1h", "1d"]
            tf_thresholds = {tf: self._threshold_for_tf(tf, cfg) for tf in _known_tfs}
            fallback_threshold = min(tf_thresholds.values())

            # --- Stream ensemble_alpha through SQL gates; flush to DB in chunks ---
            # SQL pre-filters: effective_n, per-TF alpha threshold, CI directional.
            # The only remaining in-Python gate is the top_features weights-cache check.
            total_bars = 0
            reject_count = 0
            emit_count = 0
            rows_by_tf: dict[str, int] = {}
            now = datetime.now(UTC)

            # skip_kafka: accumulate DB tuples, flush every _CHUNK_SIZE rows (O(chunk) memory)
            # !skip_kafka: accumulate event dicts for Kafka publish after cursor loop
            _chunk: list[tuple] = []
            pending_events: list[dict] = []

            async with conn.transaction():
                async for row in conn.cursor(
                    """
                    SELECT symbol, tf, bar_ts, weight_version,
                           alpha_score, alpha_ci_lower, alpha_ci_upper,
                           effective_n, n_features_active, regime
                    FROM ensemble_alpha
                    WHERE weight_version = $1
                      AND effective_n >= $2::double precision
                      AND ABS(alpha_score) > CASE tf
                            WHEN '5m'  THEN $3::double precision
                            WHEN '15m' THEN $4::double precision
                            WHEN '1h'  THEN $5::double precision
                            WHEN '1d'  THEN $6::double precision
                            ELSE $7::double precision
                          END
                      AND (
                            (alpha_score > 0 AND alpha_ci_lower > 0)
                         OR (alpha_score < 0 AND alpha_ci_upper < 0)
                          )
                    ORDER BY symbol, tf, bar_ts
                    """,
                    weight_version,
                    effective_n_gate,
                    tf_thresholds.get("5m", 1.5),
                    tf_thresholds.get("15m", 1.2),
                    tf_thresholds.get("1h", 1.0),
                    tf_thresholds.get("1d", 0.8),
                    fallback_threshold,
                    prefetch=10000,
                ):
                    total_bars += 1
                    symbol = row["symbol"]
                    tf = row["tf"]
                    bar_ts = row["bar_ts"]
                    alpha_score = float(row["alpha_score"])
                    alpha_ci_lower = float(row["alpha_ci_lower"])
                    alpha_ci_upper = float(row["alpha_ci_upper"])
                    eff_n = float(row["effective_n"])
                    n_features_active = int(row["n_features_active"])
                    regime = row["regime"] or "_pooled"
                    threshold = self._threshold_for_tf(tf, cfg)

                    ALPHA_PUBLISHER_BARS_SCORED_TOTAL.add(1, {"symbol": symbol, "tf": tf})

                    cached_weights = weights_cache.get((tf, regime), [])
                    top_features: dict[str, float] = {
                        r["feature_name"]: r["weight"] for r in cached_weights[:top_features_count]
                    }
                    if not top_features:
                        self.logger.warning(
                            "alpha_publisher.top_features_empty",
                            symbol=symbol,
                            tf=tf,
                            regime=regime,
                            reason="no_weights_in_cache_for_stratum",
                        )
                        reject_count += 1
                        continue

                    direction = "long" if alpha_score > 0 else "short"
                    bar_ts_ns = str(int(bar_ts.timestamp() * 1e9))
                    event_id = BaseBatch.content_key(symbol, tf, bar_ts_ns, self.ensemble_version)

                    rows_by_tf[tf] = rows_by_tf.get(tf, 0) + 1
                    ALPHA_PUBLISHER_EMISSIONS_TOTAL.add(
                        1, {"symbol": symbol, "tf": tf, "direction": direction, "regime": regime}
                    )
                    emit_count += 1

                    if self.skip_kafka:
                        _chunk.append(
                            (
                                event_id,
                                symbol,
                                tf,
                                bar_ts,
                                self.ensemble_version,
                                weight_version,
                                regime,
                                alpha_score,
                                alpha_ci_lower,
                                alpha_ci_upper,
                                eff_n,
                                n_features_active,
                                threshold,
                                direction,
                                top_features,
                                now,
                            )
                        )
                        if len(_chunk) >= self._CHUNK_SIZE:
                            async with pool.acquire() as wconn:
                                await wconn.executemany(self._INSERT_SQL, _chunk)
                            _chunk.clear()
                            self.logger.info(
                                "alpha_publisher.chunk_flushed",
                                emit_count=emit_count,
                            )
                    else:
                        pending_events.append(
                            {
                                "event_id": event_id,
                                "symbol": symbol,
                                "tf": tf,
                                "bar_ts": bar_ts,
                                "weight_version": weight_version,
                                "regime": regime,
                                "alpha_score": alpha_score,
                                "alpha_ci_lower": alpha_ci_lower,
                                "alpha_ci_upper": alpha_ci_upper,
                                "eff_n": eff_n,
                                "n_features_active": n_features_active,
                                "threshold": threshold,
                                "direction": direction,
                                "top_features": top_features,
                            }
                        )

        # --- Flush remaining chunk (skip_kafka path) ---
        if self.skip_kafka:
            if _chunk:
                async with pool.acquire() as wconn:
                    await wconn.executemany(self._INSERT_SQL, _chunk)
                _chunk.clear()

        # --- Non-skip-kafka: bulk insert + Kafka publish ---
        if not self.skip_kafka:
            self._producer = KafkaProducerClient(bootstrap_servers=settings.kafka_bootstrap_servers)
            try:
                await self._producer.start()
            except Exception as error:
                self.logger.error("alpha_publisher.kafka_start_failed", error=str(error))
                raise
            try:
                if pending_events:
                    async with pool.acquire() as wconn:
                        await wconn.executemany(
                            self._INSERT_SQL,
                            [
                                (
                                    e["event_id"],
                                    e["symbol"],
                                    e["tf"],
                                    e["bar_ts"],
                                    self.ensemble_version,
                                    e["weight_version"],
                                    e["regime"],
                                    e["alpha_score"],
                                    e["alpha_ci_lower"],
                                    e["alpha_ci_upper"],
                                    e["eff_n"],
                                    e["n_features_active"],
                                    e["threshold"],
                                    e["direction"],
                                    e["top_features"],
                                    now,
                                )
                                for e in pending_events
                            ],
                        )
                for e in pending_events:
                    payload = {
                        "event_id": e["event_id"],
                        "symbol": e["symbol"],
                        "tf": e["tf"],
                        "bar_ts": format_iso_ts(e["bar_ts"]),
                        "ensemble_version": self.ensemble_version,
                        "weight_version": e["weight_version"],
                        "alpha_score": e["alpha_score"],
                        "alpha_ci_lower": e["alpha_ci_lower"],
                        "alpha_ci_upper": e["alpha_ci_upper"],
                        "effective_n": e["eff_n"],
                        "regime": e["regime"],
                        "n_features_active": e["n_features_active"],
                        "top_features": e["top_features"],
                        "direction": e["direction"],
                        "emitted_at": format_iso_ts(now),
                    }
                    await self._producer.publish(topic, msg=payload)
            finally:
                await self._producer.stop()

        self.logger.info(
            "alpha_publisher.complete",
            emitted=emit_count,
            rejected=reject_count,
            total_bars=total_bars,
            skip_kafka=self.skip_kafka,
        )

        manifest.add_output(
            table_name="alpha_events",
            rows_total=emit_count,
            rows_by_tf=rows_by_tf,
        )
        manifest.mark_success()
        manifest_path = manifest.write()
        self.logger.info("alpha_publisher.manifest_written", path=str(manifest_path))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Alpha Publisher — ensemble_alpha → alpha_events + Kafka"
    )
    parser.add_argument(
        "--skip-kafka",
        action="store_true",
        help="Skip Kafka publishing (corpus batch mode — DB only, O(chunk) memory)",
    )
    args = parser.parse_args()

    try:
        init_otel_providers("indicagent-alpha-publisher")
    except OTelInitError as error:
        _logger.warning("alpha_publisher.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(AlphaPublisher(db_dsn=db_dsn, skip_kafka=args.skip_kafka).run())
