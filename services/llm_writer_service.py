#!/usr/bin/env python3
"""LLM Writer Agent — persists LLM call audit data and outcome back-fills to TimescaleDB.

Consumes three Kafka topics via consumer group 'llm_writer':
  - {env}.llm.calls        — one message per LLM call; batch-INSERTs to llm_calls hypertable
  - {env}.llm.outcomes     — one message per signal exit; UPDATEs outcome columns WHERE signal_id
  - {env}.intelligence.i8  — i8 JSONB column updates for intelligence_features

Also recomputes llm_model_scores every 15 minutes.

Inherits BaseWriterAgent for buffer/flush/offset-commit/DLQ/metrics/lifecycle.
Custom _run() handles the dual-consumer pattern (multiple topic subscriptions).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog
from scipy.stats import binomtest

from src.core.agent.base_writer import BaseWriterAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import parse_iso_ts as _parse_ts
from src.core.stream_keys import (
    topic_intelligence_i8,
    topic_llm_calls,
    topic_llm_outcomes,
    topic_llm_writer_dlq,
)
from src.observability.metrics import (
    DLQ_DEPTH,
    DLQ_MESSAGES_TOTAL,
    PERSISTENCE_BATCH_LATENCY,
    counter,
    gauge,
)

# ── Module-level constants ────────────────────────────────────────────────────

BATCH_SIZE: int = 50
FLUSH_INTERVAL_SECS: float = 5.0
CONSUMER_GROUP: str = "llm_writer"
CONSUMER_NAME: str = "llm_writer_1"
SCORE_RECOMPUTE_INTERVAL_SECS: float = 900.0  # 15 minutes
SCORE_MIN_N_OUTCOMES: int = 30
SCORE_P_THRESHOLD: float = 0.05

# ── Module-level SQL ──────────────────────────────────────────────────────────

_INSERT_LLM_CALL_SQL = """
INSERT INTO llm_calls (
    call_id, called_at, call_type, signal_id, group_name,
    symbol, timeframe, model, provider, prompt, response,
    latency_ms, tokens_est, succeeded,
    regime, session, entry_price, stop_loss, target_price,
    confidence, cis_score, entry_zone_low, entry_zone_high, setup_type
) VALUES (
    $1, $2::timestamptz, $3, $4::uuid, $5,
    $6, $7, $8, $9, $10, $11,
    $12, $13, $14,
    $15, $16, $17, $18, $19,
    $20, $21, $22, $23, $24
) ON CONFLICT (call_id) DO NOTHING
"""

_UPDATE_OUTCOME_SQL = """
UPDATE llm_calls
SET outcome = $2,
    pnl_r = $3,
    mae = $4,
    mfe = $5,
    bars_in_trade = $6,
    win = CASE WHEN $3::double precision IS NOT NULL THEN $3 > 0 ELSE NULL END,
    outcome_at = $7::timestamptz
WHERE signal_id = $1::uuid
  AND outcome IS NULL
"""

_UPSERT_SCORE_SQL = """
INSERT INTO llm_model_scores (
    model, regime, setup_type, call_type, symbol,
    n_calls, n_outcomes, win_rate, avg_pnl_r, avg_latency_ms,
    p_value, is_significant, score_updated_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
ON CONFLICT (model, regime, setup_type, call_type, symbol)
DO UPDATE SET
    n_calls = EXCLUDED.n_calls,
    n_outcomes = EXCLUDED.n_outcomes,
    win_rate = EXCLUDED.win_rate,
    avg_pnl_r = EXCLUDED.avg_pnl_r,
    avg_latency_ms = EXCLUDED.avg_latency_ms,
    p_value = EXCLUDED.p_value,
    is_significant = EXCLUDED.is_significant,
    score_updated_at = NOW()
"""

_UPDATE_I8_SQL = """
UPDATE intelligence_features
SET i8 = $4::jsonb
WHERE ts = $1::timestamptz AND symbol = $2 AND tf = $3
"""

_SELECT_OUTCOME_ROWS_SQL = """
SELECT model, regime, setup_type, call_type, symbol,
       COUNT(*) AS n_calls,
       COUNT(outcome) AS n_outcomes,
       COUNT(outcome) AS n_outcomes,
       AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS win_rate,
       AVG(pnl_r) AS avg_pnl_r,
       AVG(latency_ms) AS avg_latency_ms
FROM llm_calls
WHERE outcome IS NOT NULL
GROUP BY model, regime, setup_type, call_type, symbol
"""

logger = structlog.get_logger(__name__)


# ── Module-level pure functions (testable without class instantiation) ────────


def _parse_llm_call_fields(fields: dict) -> dict | None:
    """Parse llm.calls topic message fields into a flat column dict.

    Supports both Kafka JSON payload (string keys, string values) and legacy
    Redis stream format (bytes keys/values — used by existing unit tests).

    Required fields: call_id, called_at, symbol.
    All three must be present and non-empty — returns None if any is missing.
    All remaining fields have safe None defaults.
    """

    def _str(key: str) -> str:
        # Try string key first (Kafka), then bytes key (tests)
        val = fields.get(key) or fields.get(key.encode(), b"")
        if isinstance(val, bytes):
            val = val.decode()
        return val or ""

    call_id = _str("call_id")
    called_at = _str("called_at")
    symbol = _str("symbol")

    if not call_id or not called_at or not symbol:
        return None

    def _dec(key: str) -> str | None:
        val = _str(key)
        return val if val else None

    def _float(key: str) -> float | None:
        raw = _str(key)
        try:
            return float(raw) if raw else None
        except (ValueError, TypeError):
            return None

    def _int(key: str) -> int | None:
        raw = _str(key)
        try:
            return int(raw) if raw else None
        except (ValueError, TypeError):
            return None

    def _bool(key: str) -> bool | None:
        raw = _str(key).lower()
        if raw in ("true", "1", "yes"):
            return True
        if raw in ("false", "0", "no"):
            return False
        return None

    return {
        "call_id": call_id,
        "called_at": called_at,
        "call_type": _dec("call_type"),
        "signal_id": _dec("signal_id"),
        "group_name": _dec("group_name"),
        "symbol": symbol,
        "timeframe": _dec("timeframe"),
        "model": _dec("model"),
        "provider": _dec("provider"),
        "prompt": _dec("prompt"),
        "response": _dec("response"),
        "latency_ms": _int("latency_ms"),
        "tokens_est": _int("tokens_est"),
        "succeeded": _bool("succeeded"),
        "regime": _dec("regime"),
        "session": _dec("session"),
        "entry_price": _float("entry_price"),
        "stop_loss": _float("stop_loss"),
        "target_price": _float("target_price"),
        "confidence": _float("confidence"),
        "cis_score": _float("cis_score"),
        "entry_zone_low": _float("entry_zone_low"),
        "entry_zone_high": _float("entry_zone_high"),
        "setup_type": _dec("setup_type"),
    }


def _parse_outcome_fields(fields: dict) -> dict | None:
    """Parse llm.outcomes topic message fields into an outcome update dict.

    Supports both Kafka JSON (string keys) and legacy Redis format (bytes keys).
    Required field: signal_id — returns None if missing.
    All other outcome fields are optional (None default).
    """

    def _str(key: str) -> str:
        val = fields.get(key) or fields.get(key.encode(), b"")
        if isinstance(val, bytes):
            val = val.decode()
        return val or ""

    signal_id = _str("signal_id")
    if not signal_id:
        return None

    def _float(key: str) -> float | None:
        raw = _str(key)
        try:
            return float(raw) if raw else None
        except (ValueError, TypeError):
            return None

    def _int(key: str) -> int | None:
        raw = _str(key)
        try:
            return int(raw) if raw else None
        except (ValueError, TypeError):
            return None

    def _opt_str(key: str) -> str | None:
        val = _str(key)
        return val if val else None

    return {
        "signal_id": signal_id,
        "outcome": _opt_str("outcome"),
        "pnl_r": _float("pnl_r"),
        "mae": _float("mae"),
        "mfe": _float("mfe"),
        "bars_in_trade": _int("bars_in_trade"),
        "outcome_at": _opt_str("outcome_at"),
    }


def _build_score_insert_params(
    model: str,
    regime: str,
    setup_type: str,
    call_type: str,
    rows: list[dict],
) -> dict | None:
    """Compute score statistics for a (model, regime, setup_type, call_type) group.

    Uses scipy.stats.binomtest to check whether win_rate > 0.50 is statistically
    significant (p < SCORE_P_THRESHOLD).

    is_significant requires BOTH:
    - p_value < SCORE_P_THRESHOLD (0.05)
    - n_outcomes >= SCORE_MIN_N_OUTCOMES (30)

    Returns a dict matching the _UPSERT_SCORE_SQL parameter columns, or None if rows is empty.
    """
    if not rows:
        return None

    n_outcomes = len(rows)
    pnl_values = [r.get("pnl_r") for r in rows if r.get("pnl_r") is not None]
    win_values = [r.get("win") for r in rows if r.get("win") is not None]
    wins = sum(1 for w in win_values if w)
    n_wins_counted = len(win_values)
    win_rate = wins / n_wins_counted if n_wins_counted > 0 else 0.0
    avg_pnl_r = sum(pnl_values) / len(pnl_values) if pnl_values else None

    if n_outcomes > 0 and n_wins_counted > 0:
        result = binomtest(wins, n_wins_counted, 0.50, alternative="greater")
        p_value = float(result.pvalue)
    else:
        p_value = 1.0

    is_significant = (p_value < SCORE_P_THRESHOLD) and (n_outcomes >= SCORE_MIN_N_OUTCOMES)

    return {
        "model": model,
        "regime": regime,
        "setup_type": setup_type,
        "call_type": call_type,
        "n_calls": n_outcomes,
        "n_outcomes": n_outcomes,
        "win_rate": win_rate,
        "avg_pnl_r": avg_pnl_r,
        "avg_latency_ms": None,  # not available from rows list; populated by DB query path
        "p_value": p_value,
        "is_significant": is_significant,
    }


# ── Agent class ───────────────────────────────────────────────────────────────


class LLMWriterAgent(BaseWriterAgent):
    """Async Kafka consumer agent: llm.calls + llm.outcomes + intelligence.i8 -> TimescaleDB.

    Inherits BaseWriterAgent for buffer/flush/offset-commit/DLQ/metrics/lifecycle.
    Implements dual-consumer pattern (multiple topic subscriptions) via custom _run().
    15-min score recomputation runs as a background task alongside the consume loop.
    """

    BATCH_SIZE = 50
    FLUSH_INTERVAL_SECS = 5.0
    MAX_BUFFER_SIZE = 10_000

    def __init__(self, config_file: str | None = None):
        self.start_time = datetime.now(tz=UTC)

        # Load config before super().__init__() to extract metrics_port
        self.config = self._load_config(config_file)
        metrics_port = self.config.get("service", {}).get("metrics_port", 9117)

        super().__init__(
            name="llm_writer_agent",
            metrics_port=metrics_port,
            max_idle_seconds=300,
        )

        self._env_name: str = self.settings.env_name or ""
        self._kafka_bootstrap: str = self.settings.kafka_bootstrap_servers

        # Second buffer for i8 column updates (separate from BaseWriterAgent._buffer)
        self._i8_buffer: list[tuple] = []
        self._last_score_recompute: float = time.monotonic()

        # Connections (assigned in _run before consumption starts)
        self.db_manager: DatabaseManager | None = None
        self._dlq_producer: KafkaProducerClient | None = None

        # Prometheus metrics (preserve existing names for dashboard/alerting compatibility)
        self.calls_consumed_total = counter(
            "llm_writer_calls_consumed_total",
            "Total LLM call messages consumed from llm.calls topic",
        )
        self.outcomes_processed_total = counter(
            "llm_writer_outcomes_processed_total",
            "Total outcome messages processed from llm.outcomes topic",
        )
        self.batch_writes_total = counter(
            "llm_writer_batch_writes_total",
            "Total batch writes to llm_calls hypertable",
        )
        self.score_recomputes_total = counter(
            "llm_writer_score_recomputes_total",
            "Total llm_model_scores recompute cycles completed",
        )
        self.error_count_total = counter(
            "llm_writer_errors_total",
            "Total errors encountered by LLM writer agent",
        )
        self.buffer_size_gauge = gauge(
            "llm_writer_buffer_size",
            "Current number of LLM call events in write buffer",
        )
        self.service_uptime_seconds = gauge(
            "llm_writer_service_uptime_seconds",
            "LLM writer agent uptime in seconds",
        )
        self.i8_writes_total = counter(
            "llm_writer_i8_writes_total",
            "Total i8 UPSERTs to intelligence_features",
        )
        self.i8_update_miss_total = counter(
            "llm_writer_i8_update_miss_total",
            "i8 UPDATEs that found 0 rows (timing window)",
        )
        self._batch_latency = PERSISTENCE_BATCH_LATENCY.labels(agent_id="llm_writer")
        # _consumer_lag_gauge is inherited from BaseAgent.__init__

        self._total_calls = 0
        self._total_outcomes = 0
        self._total_batches = 0
        self._error_count = 0

    # ── BaseWriterAgent abstract method implementations ───────────────────────

    def _topic_name(self) -> str:
        """Primary Kafka topic — used by BaseWriterAgent for consumer setup."""
        return topic_llm_calls(self._env_name)

    @property
    def _consumer_group(self) -> str:
        """Kafka consumer group ID."""
        return CONSUMER_GROUP

    def _parse_payload(self, payload: dict) -> list | None:
        """Parse llm.calls topic message into INSERT param tuple.

        Returns None to route to DLQ on parse failure.
        Only used when BaseWriterAgent's generic consume path is active;
        LLMWriterAgent uses a custom _run() with direct message routing.
        """
        parsed = _parse_llm_call_fields(payload)
        if parsed is None:
            return None
        return [self._parsed_to_insert_tuple(parsed)]

    async def _flush_batch(self, batch: list) -> None:
        """Write batch of llm_calls rows to TimescaleDB.

        Called by BaseWriterAgent._do_flush(). Must NOT clear self._buffer — caller handles that.
        """
        if not self.db_manager:
            raise RuntimeError("No database connection — cannot flush llm_calls batch")
        await self.db_manager.execute_batch(_INSERT_LLM_CALL_SQL, batch)
        self.batch_writes_total.inc()
        self._total_batches += 1

    def _dlq_topic(self) -> str | None:
        """DLQ topic for unparseable messages."""
        return topic_llm_writer_dlq(self._env_name)

    # ── Setup helpers ─────────────────────────────────────────────────────────

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        default_config: dict[str, Any] = {
            "database": {"dsn": "postgresql://postgres:postgres@localhost:5432/indicagent"},
            "service": {
                "processing_interval": 0.01,
                "metrics_port": 9117,
                "health_check_interval": 30,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/llm_writer_service.log",
                "max_size": "10MB",
                "backup_count": 5,
            },
        }

        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for key, value in user_config.items():
                if isinstance(value, dict) and key in default_config:
                    default_config[key].update(value)
                else:
                    default_config[key] = value

        return default_config

    async def _connect_database(self) -> None:
        dsn = self.config["database"].get("dsn") or self.config["database"].get("url")
        try:
            self.db_manager = DatabaseManager(dsn)
            await self.db_manager.initialize()
            self.logger.info("Connected to database")
        except Exception as e:
            self.logger.warning("Database unavailable, persistence disabled", error=str(e))
            self.db_manager = None

    async def _setup_kafka_clients(self) -> None:
        """Create Kafka consumer subscribed to llm.calls, llm.outcomes, and intelligence.i8.

        Assigns self._consumer (BaseWriterAgent attribute) for offset commits.
        Also starts a DLQ producer for routing unparseable messages.
        """
        calls_topic = topic_llm_calls(self._env_name)
        outcomes_topic = topic_llm_outcomes(self._env_name)
        i8_topic = topic_intelligence_i8(self._env_name)

        kafka_consumer = KafkaConsumerClient(
            calls_topic,
            outcomes_topic,
            i8_topic,
            bootstrap_servers=self._kafka_bootstrap,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="latest",
        )
        await kafka_consumer.start()
        self._consumer = kafka_consumer  # BaseWriterAgent uses self._consumer for offset commits
        self.logger.info(
            "Kafka consumer started",
            topics=[calls_topic, outcomes_topic, i8_topic],
            group=CONSUMER_GROUP,
        )

        self._dlq_producer = KafkaProducerClient(bootstrap_servers=self._kafka_bootstrap)
        await self._dlq_producer.start()
        self.logger.info("DLQ producer started", dlq_topic=topic_llm_writer_dlq(self._env_name))

    # ── Main lifecycle ────────────────────────────────────────────────────────

    async def _run(self) -> None:
        """Main loop: connect, then run dual-consumer + score recompute tasks.

        BaseAgent.start() calls this after signal handler registration and metrics server start.
        BaseWriterAgent._teardown() handles final flush on exit.
        """
        self.logger.info("LLM Writer Agent starting")
        await self._connect_database()
        await self._setup_kafka_clients()

        tasks = [
            asyncio.create_task(self._process_loop()),
            asyncio.create_task(self._score_recompute_loop()),
            asyncio.create_task(self._health_monitor_loop()),
            asyncio.create_task(self._stall_watchdog()),
        ]
        self.logger.info("LLM Writer Agent started")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for task, result in zip(tasks, results):
            if isinstance(result, Exception):
                self.logger.error(
                    "background_task_failed",
                    task=task.get_name(),
                    error=str(result),
                )

    async def _teardown(self) -> None:
        """Flush buffer and close all connections. Override of BaseWriterAgent._teardown()."""
        try:
            await super()._teardown()
        except Exception:
            self.logger.exception("error_in_base_teardown")

        try:
            if self.db_manager:
                await self._flush_i8()
        except Exception:
            self.logger.exception("error_flushing_i8")

        try:
            if self._consumer:
                await self._consumer.stop()
        except Exception:
            self.logger.exception("error_stopping_consumer")

        try:
            if self._dlq_producer:
                await self._dlq_producer.stop()
        except Exception:
            self.logger.exception("error_stopping_dlq_producer")

        try:
            if self.db_manager:
                await self.db_manager.close()
        except Exception:
            self.logger.exception("error_closing_db_manager")

        self.logger.info(
            "LLM Writer Agent stopped",
            total_calls=self._total_calls,
            total_outcomes=self._total_outcomes,
            total_batches=self._total_batches,
        )

    # ── Message processing ────────────────────────────────────────────────────

    def _parsed_to_insert_tuple(self, parsed: dict) -> tuple:
        """Map parsed llm_call dict to a positional tuple for _INSERT_LLM_CALL_SQL."""
        try:
            called_at = _parse_ts(parsed["called_at"])
        except (ValueError, TypeError) as e:
            self.logger.warning(
                "Failed to parse called_at timestamp", error=str(e), value=parsed["called_at"]
            )
            called_at = datetime.now(tz=UTC)

        return (
            parsed["call_id"],  # $1  call_id
            called_at,  # $2  called_at
            parsed["call_type"],  # $3  call_type
            parsed["signal_id"],  # $4  signal_id (uuid)
            parsed["group_name"],  # $5  group_name
            parsed["symbol"],  # $6  symbol
            parsed["timeframe"],  # $7  timeframe
            parsed["model"],  # $8  model
            parsed["provider"],  # $9  provider
            parsed["prompt"],  # $10 prompt
            parsed["response"],  # $11 response
            parsed["latency_ms"],  # $12 latency_ms
            parsed["tokens_est"],  # $13 tokens_est
            parsed["succeeded"],  # $14 succeeded
            parsed["regime"],  # $15 regime
            parsed["session"],  # $16 session
            parsed["entry_price"],  # $17 entry_price
            parsed["stop_loss"],  # $18 stop_loss
            parsed["target_price"],  # $19 target_price
            parsed["confidence"],  # $20 confidence
            parsed["cis_score"],  # $21 cis_score
            parsed["entry_zone_low"],  # $22 entry_zone_low
            parsed["entry_zone_high"],  # $23 entry_zone_high
            parsed["setup_type"],  # $24 setup_type
        )

    async def _process_calls_message(self, payload: dict, source_topic: str = "") -> bool:
        """Parse one llm.calls topic message, buffer INSERT params.

        Routes unparseable messages to DLQ instead of silently dropping or crashing.
        """
        try:
            parsed = _parse_llm_call_fields(payload)
            if parsed is None:
                self.logger.warning("Malformed llm_call message — routing to DLQ")
                self.error_count_total.inc()
                await self._send_to_dlq(payload, source_topic, "parse_failure")
                return True

            params = self._parsed_to_insert_tuple(parsed)
            self._buffer_rows([params])  # Updates _buffer_depth_gauge via BaseWriterAgent
            self.calls_consumed_total.inc()
            self._total_calls += 1
            self.buffer_size_gauge.set(len(self._buffer))

            if len(self._buffer) >= self.BATCH_SIZE:
                await self._do_flush()

            return True

        except Exception as e:
            self.logger.error("Error processing llm_call message", error=str(e))
            self.error_count_total.inc()
            self._error_count += 1
            await self._send_to_dlq(payload, source_topic, type(e).__name__)
            return False

    async def _process_outcome_message(self, payload: dict, source_topic: str = "") -> bool:
        """Parse one llm.outcomes topic message and execute immediate UPDATE.

        Outcomes are low-volume (one per signal exit) — no buffering needed.
        Routes unparseable messages to DLQ instead of silently dropping or crashing.
        """
        try:
            parsed = _parse_outcome_fields(payload)
            if parsed is None:
                self.logger.warning("Malformed outcome message — routing to DLQ")
                self.error_count_total.inc()
                await self._send_to_dlq(payload, source_topic, "parse_failure")
                return True

            if self.db_manager:
                try:
                    outcome_at = _parse_ts(parsed["outcome_at"]) if parsed["outcome_at"] else None
                except (ValueError, TypeError) as e:
                    self.logger.warning(
                        "Failed to parse outcome_at timestamp",
                        error=str(e),
                        value=parsed["outcome_at"],
                    )
                    outcome_at = None
                params = (
                    parsed["signal_id"],  # $1
                    parsed["outcome"],  # $2
                    parsed["pnl_r"],  # $3
                    parsed["mae"],  # $4
                    parsed["mfe"],  # $5
                    parsed["bars_in_trade"],  # $6
                    outcome_at,  # $7
                )
                await self.db_manager.execute_batch(_UPDATE_OUTCOME_SQL, [params])

            self.outcomes_processed_total.inc()
            self._total_outcomes += 1
            return True

        except Exception as e:
            self.logger.error("Error processing outcome message", error=str(e))
            self.error_count_total.inc()
            self._error_count += 1
            await self._send_to_dlq(payload, source_topic, type(e).__name__)
            return False

    async def _process_i8_message(self, payload: dict) -> None:
        """Buffer i8 column from intelligence.i8 topic message for batch UPDATE flush.

        Silently skips messages with no ts field.
        """
        ts_raw = payload.get("ts") or payload.get(b"ts", b"")
        if not ts_raw:
            return
        ts_dt = _parse_ts(ts_raw)
        symbol_raw = payload.get("symbol") or payload.get(b"symbol", b"")
        tf_raw = payload.get("tf") or payload.get(b"tf", b"")
        symbol = symbol_raw.decode() if isinstance(symbol_raw, bytes) else str(symbol_raw)
        tf = tf_raw.decode() if isinstance(tf_raw, bytes) else str(tf_raw)

        def _field(key: str) -> str:
            val = payload.get(key) or payload.get(key.encode(), b"")
            return val.decode() if isinstance(val, bytes) else str(val) if val else ""

        i8_dict = {
            "model": _field("model") or "unknown",
            "confidence": _field("confidence") or "0.0",
            "summary": _field("summary"),
            "generated_at": _field("generated_at"),
        }
        self._i8_buffer.append((ts_dt, symbol, tf, json.dumps(i8_dict)))

    async def _flush_i8(self) -> None:
        """Flush _i8_buffer via UPDATE intelligence_features SET i8.

        Plain UPDATE (no INSERT ON CONFLICT) to avoid phantom rows if
        FeatureWriterAgent hasn't yet written the base row for this (ts, symbol, tf).
        A 0-row UPDATE is safe — it is counted via i8_update_miss_total for observability.
        """
        if not self._i8_buffer:
            return
        if not self.db_manager:
            self._i8_buffer.clear()
            return
        batch = self._i8_buffer[:]
        try:
            await self.db_manager.execute_batch(_UPDATE_I8_SQL, batch)
            self.i8_writes_total.inc(len(batch))
            self._i8_buffer.clear()
        except Exception as e:
            self.logger.error("i8_flush_failed", error=str(e), buffer_size=len(batch))
            # Leave buffer intact for retry — same pattern as _buffer

    async def _recompute_scores(self) -> None:
        """Query llm_calls for all rows with outcomes, compute model scores, upsert.

        Groups by (model, regime, setup_type, call_type) and additionally computes '__all__'
        aggregate rows across regimes and setup_types.
        """
        if not self.db_manager:
            return

        try:
            rows = await self.db_manager.fetch_all(_SELECT_OUTCOME_ROWS_SQL, [])
            if not rows:
                return

            score_params: list[tuple] = []
            # Process each group
            for row in rows:
                model = row["model"]
                regime = row["regime"] or "__all__"
                setup_type = row["setup_type"] or "__all__"
                call_type = row["call_type"] or "__all__"
                symbol = row.get("symbol") or "*"
                n_calls = int(row["n_calls"])
                n_outcomes = int(row["n_outcomes"])
                win_rate = float(row["win_rate"]) if row["win_rate"] is not None else 0.0
                avg_pnl_r = float(row["avg_pnl_r"]) if row["avg_pnl_r"] is not None else None
                avg_latency_ms = (
                    float(row["avg_latency_ms"]) if row["avg_latency_ms"] is not None else None
                )

                if n_outcomes > 0:
                    wins = int(round(win_rate * n_outcomes))
                    result = binomtest(wins, n_outcomes, 0.50, alternative="greater")
                    p_value = float(result.pvalue)
                else:
                    p_value = 1.0

                is_significant = (p_value < SCORE_P_THRESHOLD) and (
                    n_outcomes >= SCORE_MIN_N_OUTCOMES
                )

                score_params.append(
                    (
                        model,
                        regime,
                        setup_type,
                        call_type,
                        symbol,
                        n_calls,
                        n_outcomes,
                        win_rate,
                        avg_pnl_r,
                        avg_latency_ms,
                        p_value,
                        is_significant,
                    )
                )

            if score_params:
                await self.db_manager.execute_batch(_UPSERT_SCORE_SQL, score_params)
                self.score_recomputes_total.inc()
                self.logger.info("Score recompute complete", groups=len(score_params))

        except Exception as e:
            self.logger.error("Score recompute failed", error=str(e))
            self.error_count_total.inc()
            self._error_count += 1

    async def _send_to_dlq(self, payload: dict, source_topic: str, error_type: str) -> None:
        """Route an unparseable message to the LLM writer DLQ topic.

        Increments DLQ_MESSAGES_TOTAL and DLQ_DEPTH metrics. Logs a warning.
        Continues processing (never raises) — bad messages must not crash the agent.
        """
        dlq_topic = topic_llm_writer_dlq(self._env_name)
        try:
            if self._dlq_producer:
                await self._dlq_producer.publish(
                    dlq_topic,
                    {
                        "original_topic": source_topic,
                        "error_type": error_type,
                        "payload": payload,
                        "failed_at": datetime.now(tz=UTC).isoformat(),
                    },
                )
            DLQ_MESSAGES_TOTAL.labels(
                agent="llm_writer_agent",
                topic=dlq_topic,
                error_type=error_type,
            ).inc()
            DLQ_DEPTH.labels(agent="llm_writer_agent", topic=dlq_topic).inc()
            self.logger.warning(
                "Message routed to DLQ",
                dlq_topic=dlq_topic,
                source_topic=source_topic,
                error_type=error_type,
            )
        except Exception as e:
            self.logger.error("Failed to publish to DLQ", error=str(e), dlq_topic=dlq_topic)

    async def _stall_watchdog(self) -> None:
        """Warn if no messages have been consumed for max_idle_seconds.

        Checks every 60 seconds. Startup grace: does not warn until the first
        message has been received. Only logs a warning — does not kill the process.
        """
        check_interval = 60
        while not self._stop_event.is_set():
            await asyncio.sleep(check_interval)
            if self._last_msg_ts is None:
                continue  # startup grace — no messages received yet
            idle_secs = time.monotonic() - self._last_msg_ts
            if idle_secs >= self.max_idle_seconds:
                self.logger.warning(
                    "LLMWriterAgent stall detected — no messages consumed",
                    idle_seconds=int(idle_secs),
                    max_idle_seconds=self.max_idle_seconds,
                )

    async def _process_loop(self) -> None:
        """Kafka consumer loop for llm.calls + llm.outcomes + intelligence.i8 — routes by topic."""
        if not self._consumer:
            return

        calls_topic = topic_llm_calls(self._env_name)
        outcomes_topic = topic_llm_outcomes(self._env_name)
        i8_topic = topic_intelligence_i8(self._env_name)

        async for kafka_topic, _key, payload in self._consumer.messages():
            if self._stop_event.is_set():
                break
            try:
                if kafka_topic == calls_topic:
                    await self._process_calls_message(payload, calls_topic)
                    await self.maybe_flush()
                elif kafka_topic == outcomes_topic:
                    await self._process_outcome_message(payload, outcomes_topic)
                elif kafka_topic == i8_topic:
                    await self._process_i8_message(payload)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in process loop", error=str(e))
                self.error_count_total.inc()
                self._error_count += 1

    async def _score_recompute_loop(self) -> None:
        """Periodic loop: recomputes llm_model_scores every SCORE_RECOMPUTE_INTERVAL_SECS."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(SCORE_RECOMPUTE_INTERVAL_SECS)
                if not self._stop_event.is_set():
                    await self._recompute_scores()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in score recompute loop", error=str(e))
                await asyncio.sleep(60)

    async def _health_monitor_loop(self) -> None:
        """Periodic health check: logs uptime and key counters."""
        while not self._stop_event.is_set():
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                interval = self.config["service"].get("health_check_interval", 30)
                self.logger.info(
                    "Health check",
                    uptime=uptime,
                    calls_consumed=self._total_calls,
                    outcomes_processed=self._total_outcomes,
                    batches_written=self._total_batches,
                    buffer_size=len(self._buffer),
                    errors=self._error_count,
                )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)


# Backward-compatibility alias — existing tests import LLMWriterService
LLMWriterService = LLMWriterAgent


# ── Entrypoint ────────────────────────────────────────────────────────────────


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="LLM Writer Agent")
    parser.add_argument("--config", help="Configuration file path")
    args = parser.parse_args()

    agent = LLMWriterAgent(args.config)
    try:
        await agent.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
