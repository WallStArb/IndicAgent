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
- event_id = BaseBatch.content_key(symbol, tf, bar_ts_ns, ensemble_version, weight_version).

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

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr
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
from src.observability.spans import observed_span

_logger = structlog.get_logger(__name__)

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

    def __init__(
        self,
        db_dsn: str,
        skip_kafka: bool = False,
        weight_version_override: str | None = None,
    ) -> None:
        super().__init__(db_dsn)
        self.skip_kafka = skip_kafka
        self._weight_version_override = weight_version_override

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
        return _cfg(cfg, f"alpha.quant.threshold.{tf}", defaults.get(tf, 1.0))

    def _cost_hurdle_for_tf(self, tf: str, cfg: dict[str, Any]) -> float:
        """Return the APR-loaded cost hurdle for the CI directional gate.

        The gate requires ci_lower > cost_hurdle (long) or ci_upper < -cost_hurdle
        (short). A value of 0.0 reproduces the legacy ci > 0 behavior. Raise via
        APR once corpus data establishes the break-even alpha_score at each TF.
        """
        return _cfg(cfg, f"alpha.quant.cost_hurdle.{tf}", 0.0)

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        """Read ensemble_alpha, enforce gates, write alpha_events, publish to Kafka."""
        manifest = CorpusManifest("alpha_publisher", CorpusManifest.DEFAULT_MANIFEST_DIR)
        # todo 156: alpha_publisher is the sole alpha_events writer -- the terminal stage
        # of the whole v3.0 DAG -- and previously had zero spans, making a slow or
        # silently-degraded run invisible in any trace view.
        async with observed_span(
            "alpha_publisher.execute",
            weight_version_override=self._weight_version_override or "",
        ):
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
            top_features, emitted_at, cost_hurdle, is_shadow
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18
        )
        ON CONFLICT (event_id, bar_ts) DO NOTHING
    """

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        settings = Settings()
        topic = topic_alpha_events(settings.env_name)

        async with pool.acquire() as conn:
            # --- Load APR config ---
            cfg = await _load_apr(conn)
            effective_n_gate = _cfg(cfg, "alpha.ensemble.effective_n_gate", 3.0)
            # Per-run weight epoch: CLI --weight-version overrides the static APR default so
            # the publisher reads and emits from the same epoch ensemble_trainer wrote.
            weight_version = self._weight_version_override or _cfg(
                cfg, "alpha.ensemble.weight_version", "v1"
            )
            top_features_count = _cfg(cfg, "alpha.ensemble.top_features_count", 10)
            # todo 011: one-way live-promotion switch. True until an operator flips it
            # at Phase 144 after the shadow record passes all promotion-gate criteria.
            is_shadow = _cfg(cfg, "alpha.publisher.is_shadow", True)

            self.logger.info(
                "alpha_publisher.config_loaded",
                effective_n_gate=effective_n_gate,
                weight_version=weight_version,
                top_features_count=top_features_count,
                topic=topic,
                skip_kafka=self.skip_kafka,
                is_shadow=is_shadow,
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

            # A nonzero row count above does not mean the run that wrote those rows
            # finished. ensemble_trainer.py's "full replace" delete-then-repopulate can
            # be interrupted mid-run, leaving nonzero-but-incomplete rows for a
            # weight_version -- AlphaPublisher is the sole writer of alpha_events, so
            # publishing from partial rows here is a silent wrong answer feeding
            # whatever reads alpha_events downstream, not just a measurement artifact
            # (2026-07-08 altitude review finding: this exact gap was fixed in
            # ensemble_ic_engine.py first but missed here, the more consequential
            # consumer).
            CorpusManifest.ensure_success_for(
                CorpusManifest.DEFAULT_MANIFEST_DIR,
                "ensemble_trainer",
                scope_suffix=weight_version,
                weight_version=weight_version,
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

            # Pre-compute per-TF thresholds and cost hurdles from APR
            _known_tfs = ["5m", "15m", "1h", "1d"]
            tf_thresholds = {tf: self._threshold_for_tf(tf, cfg) for tf in _known_tfs}
            tf_cost_hurdles = {tf: self._cost_hurdle_for_tf(tf, cfg) for tf in _known_tfs}
            fallback_threshold = min(tf_thresholds.values())

            # --- Stream ensemble_alpha through SQL gates; flush to DB in chunks ---
            # SQL pre-filters: effective_n, per-TF alpha threshold, CI directional + cost.
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
                # --- Full replace, scoped to this weight_version ---
                # ensemble_alpha is a full-batch rescan/rewrite per ensemble_trainer run
                # (not incremental), so this cursor below always processes the CURRENT
                # complete snapshot for weight_version. ON CONFLICT DO NOTHING alone
                # cannot remove rows for bars that no longer qualify (e.g. a stratum a
                # newer ensemble_trainer run stopped writing because a gate tightened) --
                # it only adds or no-ops, never deletes. Delete lives inside this same
                # transaction as the insert loop below so a mid-run failure rolls back
                # the delete too -- atomic replace, never a partially-empty table visible
                # to readers. Found 2026-07-08: 2346 stale 1h/high_bear alpha_events rows
                # survived a re-run because of exactly this gap.
                deleted = await conn.execute(
                    "DELETE FROM alpha_events WHERE weight_version = $1", weight_version
                )
                self.logger.info(
                    "alpha_publisher.prior_weight_version_cleared",
                    weight_version=weight_version,
                    deleted=deleted,
                )

                async for row in conn.cursor(
                    """
                    WITH g AS (
                        SELECT symbol, tf, bar_ts, weight_version,
                               alpha_score, alpha_ci_lower, alpha_ci_upper,
                               effective_n, n_features_active, regime,
                               CASE tf
                                   WHEN '5m'  THEN $3::double precision
                                   WHEN '15m' THEN $4::double precision
                                   WHEN '1h'  THEN $5::double precision
                                   WHEN '1d'  THEN $6::double precision
                                   ELSE $7::double precision
                               END AS threshold_val,
                               CASE tf
                                   WHEN '5m'  THEN $8::double precision
                                   WHEN '15m' THEN $9::double precision
                                   WHEN '1h'  THEN $10::double precision
                                   WHEN '1d'  THEN $11::double precision
                                   ELSE $12::double precision
                               END AS hurdle_val
                        FROM ensemble_alpha
                        WHERE weight_version = $1
                    )
                    SELECT symbol, tf, bar_ts, weight_version,
                           alpha_score, alpha_ci_lower, alpha_ci_upper,
                           effective_n, n_features_active, regime
                    FROM g
                    WHERE effective_n >= $2::double precision
                      AND ABS(alpha_score) > threshold_val
                      AND (
                            (alpha_score > 0 AND alpha_ci_lower > hurdle_val)
                         OR (alpha_score < 0 AND alpha_ci_upper < -hurdle_val)
                          )
                    ORDER BY symbol, tf, bar_ts
                    """,
                    weight_version,
                    effective_n_gate,
                    tf_thresholds["5m"],
                    tf_thresholds["15m"],
                    tf_thresholds["1h"],
                    tf_thresholds["1d"],
                    fallback_threshold,
                    tf_cost_hurdles["5m"],
                    tf_cost_hurdles["15m"],
                    tf_cost_hurdles["1h"],
                    tf_cost_hurdles["1d"],
                    0.0,
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
                    threshold = tf_thresholds.get(tf, fallback_threshold)
                    cost_hurdle = tf_cost_hurdles.get(tf, 0.0)

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
                    # weight_version in the event_id: a new weight epoch must produce a
                    # distinct event_id, else ON CONFLICT (event_id, bar_ts) DO NOTHING
                    # silently swallows every new-epoch row (bottom-up audit / cross-AI
                    # review — the emission-path twin of the DO NOTHING trap Plan 04
                    # fixes in the trainer).
                    event_id = BaseBatch.content_key(symbol, tf, bar_ts_ns, self.ensemble_version, weight_version)  # fmt: skip

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
                                cost_hurdle,
                                is_shadow,
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
                                "cost_hurdle": cost_hurdle,
                                "is_shadow": is_shadow,
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
                                    e["cost_hurdle"],
                                    e["is_shadow"],
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
                        "is_shadow": e["is_shadow"],
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
    parser.add_argument(
        "--weight-version",
        default=None,
        help=(
            "Per-run weight epoch to publish; must match the epoch ensemble_trainer wrote. "
            "Overrides alpha.ensemble.weight_version."
        ),
    )
    args = parser.parse_args()

    try:
        init_otel_providers("indicagent-alpha-publisher")
    except OTelInitError as error:
        _logger.warning("alpha_publisher.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(
        AlphaPublisher(
            db_dsn=db_dsn,
            skip_kafka=args.skip_kafka,
            weight_version_override=args.weight_version,
        ).run()
    )
