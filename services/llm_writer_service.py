#!/usr/bin/env python3
"""LLM Writer Service — persists LLM call audit data and outcome back-fills to TimescaleDB.

Consumes two Redis streams via consumer group 'llm_writer':
  - llm_calls:stream  — one message per LLM call; batch-INSERTs to llm_calls hypertable
  - llm_outcomes:stream — one message per signal exit; UPDATEs outcome columns WHERE signal_id

Also recomputes llm_model_scores every 15 minutes and caches results in Redis.

Mirrors the feature_writer_service.py pattern exactly: batch buffering, consumer groups with
ensure_consumer_group_with_reset, graceful SIGINT/SIGTERM shutdown.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
import structlog
from scipy.stats import binomtest

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import llm_calls_stream, llm_outcomes_stream, llm_scores_cache
from src.core.stream_utils import ensure_consumer_group_with_reset
from src.observability.metrics import counter, gauge, start_metrics_server

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
    model, regime, setup_type, call_type,
    n_calls, n_outcomes, win_rate, avg_pnl_r, avg_latency_ms,
    p_value, is_significant, score_updated_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
ON CONFLICT (model, regime, setup_type, call_type)
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

_SELECT_OUTCOME_ROWS_SQL = """
SELECT model, regime, setup_type, call_type,
       COUNT(*) AS n_calls,
       COUNT(outcome) AS n_outcomes,
       AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) AS win_rate,
       AVG(pnl_r) AS avg_pnl_r,
       AVG(latency_ms) AS avg_latency_ms
FROM llm_calls
WHERE outcome IS NOT NULL
GROUP BY model, regime, setup_type, call_type
"""

logger = structlog.get_logger(__name__)


# ── Module-level pure functions (testable without class instantiation) ────────


def _parse_llm_call_fields(fields: dict[bytes, bytes]) -> dict | None:
    """Parse llm_calls:stream message fields into a flat column dict.

    Required fields: call_id, called_at, symbol.
    All three must be present and non-empty — returns None if any is missing.
    All remaining fields have safe None defaults.
    """
    call_id = fields.get(b"call_id", b"").decode()
    called_at = fields.get(b"called_at", b"").decode()
    symbol = fields.get(b"symbol", b"").decode()

    if not call_id or not called_at or not symbol:
        return None

    def _dec(key: bytes, default: str = "") -> str | None:
        val = fields.get(key, b"").decode()
        return val if val else None

    def _float(key: bytes) -> float | None:
        raw = fields.get(key, b"").decode()
        try:
            return float(raw) if raw else None
        except (ValueError, TypeError):
            return None

    def _int(key: bytes) -> int | None:
        raw = fields.get(key, b"").decode()
        try:
            return int(raw) if raw else None
        except (ValueError, TypeError):
            return None

    def _bool(key: bytes) -> bool | None:
        raw = fields.get(key, b"").decode().lower()
        if raw in ("true", "1", "yes"):
            return True
        if raw in ("false", "0", "no"):
            return False
        return None

    return {
        "call_id": call_id,
        "called_at": called_at,
        "call_type": _dec(b"call_type"),
        "signal_id": _dec(b"signal_id"),
        "group_name": _dec(b"group_name"),
        "symbol": symbol,
        "timeframe": _dec(b"timeframe"),
        "model": _dec(b"model"),
        "provider": _dec(b"provider"),
        "prompt": _dec(b"prompt"),
        "response": _dec(b"response"),
        "latency_ms": _int(b"latency_ms"),
        "tokens_est": _int(b"tokens_est"),
        "succeeded": _bool(b"succeeded"),
        "regime": _dec(b"regime"),
        "session": _dec(b"session"),
        "entry_price": _float(b"entry_price"),
        "stop_loss": _float(b"stop_loss"),
        "target_price": _float(b"target_price"),
        "confidence": _float(b"confidence"),
        "cis_score": _float(b"cis_score"),
        "entry_zone_low": _float(b"entry_zone_low"),
        "entry_zone_high": _float(b"entry_zone_high"),
        "setup_type": _dec(b"setup_type"),
    }


def _parse_outcome_fields(fields: dict[bytes, bytes]) -> dict | None:
    """Parse llm_outcomes:stream message fields into an outcome update dict.

    Required field: signal_id — returns None if missing.
    All other outcome fields are optional (None default).
    """
    signal_id = fields.get(b"signal_id", b"").decode()
    if not signal_id:
        return None

    def _float(key: bytes) -> float | None:
        raw = fields.get(key, b"").decode()
        try:
            return float(raw) if raw else None
        except (ValueError, TypeError):
            return None

    def _int(key: bytes) -> int | None:
        raw = fields.get(key, b"").decode()
        try:
            return int(raw) if raw else None
        except (ValueError, TypeError):
            return None

    def _str(key: bytes) -> str | None:
        val = fields.get(key, b"").decode()
        return val if val else None

    return {
        "signal_id": signal_id,
        "outcome": _str(b"outcome"),
        "pnl_r": _float(b"pnl_r"),
        "mae": _float(b"mae"),
        "mfe": _float(b"mfe"),
        "bars_in_trade": _int(b"bars_in_trade"),
        "outcome_at": _str(b"outcome_at"),
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


# ── Service class ──────────────────────────────────────────────────────────────


class LLMWriterService:
    """Async consumer group service: reads LLM streams and writes to TimescaleDB.

    Two consumer loops:
    - _calls_process_loop: batches llm_calls:stream INSERTs (buffered)
    - _outcomes_process_loop: immediate UPDATE on llm_outcomes:stream (low volume)

    Score recompute loop runs every SCORE_RECOMPUTE_INTERVAL_SECS and upserts
    llm_model_scores table + updates Redis score cache.
    """

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)

        self.config = self._load_config(config_file)
        self._setup_logging()

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None

        self._calls_buffer: list[tuple] = []
        self._last_flush: float = time.monotonic()
        self._last_score_recompute: float = time.monotonic()

        try:
            _s = Settings()
            self._env_prefix: str = f"{_s.env_name}:" if _s.env_name else ""
        except Exception:
            self._env_prefix = ""

        # Prometheus metrics
        self.calls_consumed_total = counter(
            "llm_writer_calls_consumed_total",
            "Total LLM call messages consumed from llm_calls:stream",
        )
        self.outcomes_processed_total = counter(
            "llm_writer_outcomes_processed_total",
            "Total outcome messages processed from llm_outcomes:stream",
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
            "Total errors encountered by LLM writer service",
        )
        self.buffer_size_gauge = gauge(
            "llm_writer_buffer_size",
            "Current number of LLM call events in write buffer",
        )
        self.service_uptime_seconds = gauge(
            "llm_writer_service_uptime_seconds",
            "LLM writer service uptime in seconds",
        )

        self._total_calls = 0
        self._total_outcomes = 0
        self._total_batches = 0
        self._error_count = 0

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)
        metrics_port = self.config.get("service", {}).get("metrics_port", 9117)
        start_metrics_server(port=metrics_port)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        default_config: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "database": {
                "dsn": "postgresql://postgres:postgres@localhost:5432/indicagent"
            },
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

    def _setup_logging(self) -> None:
        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
            backup_count=self.config["logging"].get("backup_count", 5),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def _connect_redis(self) -> None:
        self.redis_client = redis.Redis(
            host=self.config["redis"]["host"],
            port=self.config["redis"]["port"],
            db=self.config["redis"].get("db", 0),
            decode_responses=False,
            max_connections=20,
        )
        await self.redis_client.ping()
        self.logger.info("Connected to Redis")

    async def _connect_database(self) -> None:
        dsn = self.config["database"].get("dsn") or self.config["database"].get("url")
        try:
            self.db_manager = DatabaseManager(dsn)
            await self.db_manager.initialize()
            self.logger.info("Connected to database")
        except Exception as e:
            self.logger.warning("Database unavailable, persistence disabled", error=str(e))
            self.db_manager = None

    async def _setup_consumer_groups(self) -> None:
        """Create consumer groups on both LLM streams."""
        calls_stream = llm_calls_stream(self._env_prefix)
        outcomes_stream = llm_outcomes_stream(self._env_prefix)

        await ensure_consumer_group_with_reset(
            self.redis_client, calls_stream, CONSUMER_GROUP
        )
        await ensure_consumer_group_with_reset(
            self.redis_client, outcomes_stream, CONSUMER_GROUP
        )
        self.logger.info(
            "Consumer groups ready",
            calls_stream=calls_stream,
            outcomes_stream=outcomes_stream,
            group=CONSUMER_GROUP,
        )

    async def _maybe_flush(self, force: bool = False) -> None:
        """Flush buffered llm_calls INSERTs to TimescaleDB.

        Flushes when force=True or FLUSH_INTERVAL_SECS has elapsed.
        Drops buffer with warning if db_manager is unavailable (prevents unbounded growth).
        """
        if not self._calls_buffer:
            return

        should_flush = force or (time.monotonic() - self._last_flush >= FLUSH_INTERVAL_SECS)
        if not should_flush:
            return

        if not self.db_manager:
            self.logger.warning(
                "No database connection — dropping buffered LLM calls",
                count=len(self._calls_buffer),
            )
            self._calls_buffer.clear()
            self._last_flush = time.monotonic()
            return

        params = list(self._calls_buffer)
        try:
            await self.db_manager.execute_batch(_INSERT_LLM_CALL_SQL, params)
            self._calls_buffer.clear()
            self._last_flush = time.monotonic()
            self.batch_writes_total.inc()
            self._total_batches += 1
            self.buffer_size_gauge.set(0)
            self.logger.debug("Flushed llm_calls batch", rows=len(params))
        except Exception as e:
            self.logger.error("Batch write failed", error=str(e), rows=len(params))
            self.error_count_total.inc()
            self._error_count += 1
            self.buffer_size_gauge.set(len(self._calls_buffer))

    def _parsed_to_insert_tuple(self, parsed: dict) -> tuple:
        """Map parsed llm_call dict to a positional tuple for _INSERT_LLM_CALL_SQL."""
        return (
            parsed["call_id"],       # $1  call_id
            parsed["called_at"],     # $2  called_at
            parsed["call_type"],     # $3  call_type
            parsed["signal_id"],     # $4  signal_id (uuid)
            parsed["group_name"],    # $5  group_name
            parsed["symbol"],        # $6  symbol
            parsed["timeframe"],     # $7  timeframe
            parsed["model"],         # $8  model
            parsed["provider"],      # $9  provider
            parsed["prompt"],        # $10 prompt
            parsed["response"],      # $11 response
            parsed["latency_ms"],    # $12 latency_ms
            parsed["tokens_est"],    # $13 tokens_est
            parsed["succeeded"],     # $14 succeeded
            parsed["regime"],        # $15 regime
            parsed["session"],       # $16 session
            parsed["entry_price"],   # $17 entry_price
            parsed["stop_loss"],     # $18 stop_loss
            parsed["target_price"],  # $19 target_price
            parsed["confidence"],    # $20 confidence
            parsed["cis_score"],     # $21 cis_score
            parsed["entry_zone_low"],  # $22 entry_zone_low
            parsed["entry_zone_high"], # $23 entry_zone_high
            parsed["setup_type"],    # $24 setup_type
        )

    async def _process_calls_message(
        self,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> bool:
        """Parse one llm_calls stream message, buffer INSERT params."""
        try:
            parsed = _parse_llm_call_fields(fields)
            if parsed is None:
                self.logger.warning(
                    "Malformed llm_call message — acked and skipped",
                    stream=stream_name,
                    message_id=message_id,
                )
                self.error_count_total.inc()
                return True

            params = self._parsed_to_insert_tuple(parsed)
            self._calls_buffer.append(params)
            self.calls_consumed_total.inc()
            self._total_calls += 1
            self.buffer_size_gauge.set(len(self._calls_buffer))

            if len(self._calls_buffer) >= BATCH_SIZE:
                await self._maybe_flush(force=True)

            return True

        except Exception as e:
            self.logger.error("Error processing llm_call message", error=str(e))
            self.error_count_total.inc()
            self._error_count += 1
            return False

    async def _process_outcome_message(
        self,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> bool:
        """Parse one llm_outcomes stream message and execute immediate UPDATE.

        Outcomes are low-volume (one per signal exit) — no buffering needed.
        """
        try:
            parsed = _parse_outcome_fields(fields)
            if parsed is None:
                self.logger.warning(
                    "Malformed outcome message — acked and skipped",
                    stream=stream_name,
                    message_id=message_id,
                )
                self.error_count_total.inc()
                return True

            if self.db_manager:
                params = (
                    parsed["signal_id"],      # $1
                    parsed["outcome"],        # $2
                    parsed["pnl_r"],          # $3
                    parsed["mae"],            # $4
                    parsed["mfe"],            # $5
                    parsed["bars_in_trade"],  # $6
                    parsed["outcome_at"],     # $7
                )
                await self.db_manager.execute_batch(_UPDATE_OUTCOME_SQL, [params])

            self.outcomes_processed_total.inc()
            self._total_outcomes += 1
            return True

        except Exception as e:
            self.logger.error("Error processing outcome message", error=str(e))
            self.error_count_total.inc()
            self._error_count += 1
            return False

    async def _recompute_scores(self) -> None:
        """Query llm_calls for all rows with outcomes, compute model scores, upsert + cache.

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

                is_significant = (
                    (p_value < SCORE_P_THRESHOLD) and (n_outcomes >= SCORE_MIN_N_OUTCOMES)
                )

                score_params.append((
                    model, regime, setup_type, call_type,
                    n_calls, n_outcomes, win_rate, avg_pnl_r, avg_latency_ms,
                    p_value, is_significant,
                ))

            if score_params:
                await self.db_manager.execute_batch(_UPSERT_SCORE_SQL, score_params)
                self.score_recomputes_total.inc()
                self.logger.info("Score recompute complete", groups=len(score_params))

                # Update Redis score cache: hset per (call_type, regime) with model as field
                for params in score_params:
                    model, regime, setup_type, call_type = (
                        params[0], params[1], params[2], params[3]
                    )
                    score_blob = json.dumps({
                        "model": model,
                        "regime": regime,
                        "setup_type": setup_type,
                        "n_outcomes": params[5],
                        "win_rate": params[6],
                        "avg_pnl_r": params[7],
                        "p_value": params[9],
                        "is_significant": params[10],
                    })
                    cache_key = llm_scores_cache(self._env_prefix, call_type, regime)
                    await self.redis_client.hset(cache_key, model, score_blob)

        except Exception as e:
            self.logger.error("Score recompute failed", error=str(e))
            self.error_count_total.inc()
            self._error_count += 1

    async def _calls_process_loop(self) -> None:
        """Consumer loop for llm_calls:stream — buffered batch INSERT."""
        calls_stream = llm_calls_stream(self._env_prefix)
        all_streams = {calls_stream: ">"}

        while self.running and not self.shutdown_requested:
            try:
                messages = await self.redis_client.xreadgroup(
                    CONSUMER_GROUP, CONSUMER_NAME,
                    all_streams, count=10, block=1000,
                )
                for stream_bytes, msgs in messages:
                    stream_name = (
                        stream_bytes.decode()
                        if isinstance(stream_bytes, bytes)
                        else stream_bytes
                    )
                    to_ack: list[bytes] = []
                    for message_id, fields in msgs:
                        ok = await self._process_calls_message(
                            fields, stream_name, message_id
                        )
                        if ok:
                            to_ack.append(message_id)
                    if to_ack:
                        await self.redis_client.xack(stream_name, CONSUMER_GROUP, *to_ack)

                await self._maybe_flush(force=False)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in calls process loop", error=str(e))
                self.error_count_total.inc()
                self._error_count += 1
                await asyncio.sleep(1)

    async def _outcomes_process_loop(self) -> None:
        """Consumer loop for llm_outcomes:stream — immediate UPDATE (no buffering)."""
        outcomes_stream = llm_outcomes_stream(self._env_prefix)
        all_streams = {outcomes_stream: ">"}

        while self.running and not self.shutdown_requested:
            try:
                messages = await self.redis_client.xreadgroup(
                    CONSUMER_GROUP, CONSUMER_NAME,
                    all_streams, count=10, block=1000,
                )
                for stream_bytes, msgs in messages:
                    stream_name = (
                        stream_bytes.decode()
                        if isinstance(stream_bytes, bytes)
                        else stream_bytes
                    )
                    to_ack: list[bytes] = []
                    for message_id, fields in msgs:
                        ok = await self._process_outcome_message(
                            fields, stream_name, message_id
                        )
                        if ok:
                            to_ack.append(message_id)
                    if to_ack:
                        await self.redis_client.xack(stream_name, CONSUMER_GROUP, *to_ack)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in outcomes process loop", error=str(e))
                self.error_count_total.inc()
                self._error_count += 1
                await asyncio.sleep(1)

    async def _score_recompute_loop(self) -> None:
        """Periodic loop: recomputes llm_model_scores every SCORE_RECOMPUTE_INTERVAL_SECS."""
        while self.running and not self.shutdown_requested:
            try:
                await asyncio.sleep(SCORE_RECOMPUTE_INTERVAL_SECS)
                if self.running and not self.shutdown_requested:
                    await self._recompute_scores()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in score recompute loop", error=str(e))
                await asyncio.sleep(60)

    async def _health_monitor_loop(self) -> None:
        """Periodic health check: logs uptime and key counters."""
        while self.running and not self.shutdown_requested:
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
                    buffer_size=len(self._calls_buffer),
                    errors=self._error_count,
                )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)

    async def _shutdown(self) -> None:
        """Graceful shutdown: flush buffer, close connections."""
        self.logger.info("Shutting down LLM Writer Service")
        self.shutdown_requested = True
        self.running = False

        # Flush remaining buffered calls before closing
        await self._maybe_flush(force=True)

        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()

        self.logger.info(
            "LLM Writer Service stopped",
            total_calls=getattr(self, "_total_calls", 0),
            total_outcomes=getattr(self, "_total_outcomes", 0),
            total_batches=getattr(self, "_total_batches", 0),
        )

    async def start(self) -> None:
        """Start all async loops and run until shutdown."""
        self.logger.info("Starting LLM Writer Service", config=self.config["service"])
        try:
            await self._connect_redis()
            await self._connect_database()
            await self._setup_consumer_groups()
            self.running = True
            tasks = [
                asyncio.create_task(self._calls_process_loop()),
                asyncio.create_task(self._outcomes_process_loop()),
                asyncio.create_task(self._score_recompute_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("LLM Writer Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start LLM writer", error=str(e))
            raise
        finally:
            await self._shutdown()


# ── Entrypoint ────────────────────────────────────────────────────────────────


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="LLM Writer Service")
    parser.add_argument("--config", help="Configuration file path")
    args = parser.parse_args()

    svc = LLMWriterService(args.config)
    try:
        await svc.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
