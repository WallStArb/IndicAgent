"""LineageRecorder — unified signal lineage recording.

Replaces ShadowRecorder + TransformRecorder with a single Kafka-first recorder.
Hot path publishes to topic_signal_lineage() Kafka topic (D-46).
LineageWriterAgent consumes and persists to signal_lineage hypertable.
"""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from src.core.stream_keys import topic_signal_lineage

logger = structlog.get_logger(__name__)


class LineageRecorder:
    """Unified signal lineage recorder (Kafka-first, DAG-correct).

    Replaces ShadowRecorder (alpha_multiplier_shadow) and
    TransformRecorder (signal_transform_log) with a single recorder
    publishing to topic_signal_lineage() Kafka topic.

    D-48: All records start is_shadow=True by default.
    """

    def __init__(self, producer: Any, env_name: str, batch_size: int = 50, flush_interval_s: float = 2.0) -> None:
        self._producer = producer
        self._env_name = env_name
        self._batch: list[dict] = []
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._last_flush = time.monotonic()
        self._flush_task: asyncio.Task | None = None

    def record(
        self,
        *,
        signal_id: UUID,
        event_type: str,  # 'transform' | 'agent_prediction' | 'lifecycle'
        source: str,       # transform_id or agent_id
        dag_order: int | None = None,
        multiplier: float | None = None,
        metadata: dict[str, Any] | None = None,  # D-07: event-specific JSONB
        is_shadow: bool = True,  # D-48: default True
        symbol: str = "",
        tf: str = "",
    ) -> None:
        """Record a lineage event to the batch buffer."""
        row = {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "signal_id": str(signal_id),
            "event_type": event_type,
            "source": source,
            "dag_order": dag_order,
            "multiplier": multiplier,
            "metadata": metadata or {},  # D-07
            "is_shadow": is_shadow,
            "symbol": symbol,
            "tf": tf,
        }
        self._batch.append(row)
        if len(self._batch) >= self._batch_size:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self.flush())
                task.add_done_callback(
                    lambda t: logger.exception("lineage_recorder.flush_failed")
                    if t.exception()
                    else None
                )
            except RuntimeError:
                pass  # no running loop; flush() will be called on next periodic flush

    async def flush(self) -> None:
        """Flush buffered records to Kafka topic_signal_lineage()."""
        if not self._batch:
            return
        batch = self._batch[:]
        self._batch = []
        topic = topic_signal_lineage(self._env_name)
        failed: list[dict] = []
        for row in batch:
            try:
                await self._producer.publish(topic, value=row)
            except Exception:
                logger.exception("lineage_recorder.publish_failed", source=row.get("source"))
                failed.append(row)
        if failed:
            self._batch = failed + self._batch
        self._last_flush = time.monotonic()
