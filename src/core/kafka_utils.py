"""
Kafka producer/consumer helpers for IndicAgent services.

Version: 2.0.0
Last Updated: 2026-08-03
Status: Current ✅

Provides KafkaProducerClient and KafkaConsumerClient — thin async wrappers around
confluent_kafka's librdkafka-backed Producer/Consumer that match the service
lifecycle patterns established by the existing Redis client usage.

Migrated 2026-08-03 from aiokafka (pure-Python asyncio implementation) to
confluent-kafka (C bindings around librdkafka) for the hot real-time publish path's
throughput/latency ceiling — Redpanda specifically benefits from librdkafka clients.
confluent_kafka.aio.AIOProducer was considered but rejected: its batched async path
drops per-message headers, which would silently break OTel trace propagation on
every published message. Both clients here are hand-rolled asyncio wrappers around
the synchronous librdkafka API instead, preserving full header support.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time as _time
from collections.abc import AsyncGenerator, Callable

import orjson
import structlog
from confluent_kafka import (
    OFFSET_BEGINNING,
    OFFSET_END,
    Consumer,
    KafkaException,
    Producer,
    TopicPartition,
)
from opentelemetry import context as otel_context
from opentelemetry.propagate import extract, inject

from src.observability.metrics import KAFKA_PUBLISH_SECONDS

logger = structlog.get_logger(__name__)

# Matches the bounded queue size in KafkaConsumerClient.messages() -- caps how many
# messages cross the consume-thread/event-loop boundary in one run_coroutine_threadsafe
# round trip.
_CONSUME_BATCH_SIZE = 500


async def _put_batch(queue: asyncio.Queue, batch: list) -> None:
    """Awaits queue.put() for each message in one coroutine, so a single
    run_coroutine_threadsafe(...).result() call from the consume thread enqueues the
    whole batch instead of paying one cross-thread round trip per message."""
    for msg in batch:
        await queue.put(msg)


def _run_blocking_loop(
    fn: Callable[[threading.Event], None],
) -> tuple[asyncio.Task, threading.Event]:
    """Launch fn in one dedicated background thread for its whole lifetime (a single
    asyncio.to_thread submission, not one per iteration/poll) -- submitting a fresh
    executor task every tick would flood the shared default thread pool's queue under
    fast polling (confirmed: an unthrottled per-iteration version pathologically grew
    to double-digit GB RSS in testing). fn must loop `while not event.is_set(): ...`.
    Shared by KafkaProducerClient's poll loop and KafkaConsumerClient's consume loop.
    """
    stop_event = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(fn, stop_event))
    return task, stop_event


async def _stop_blocking_loop(task: asyncio.Task, stop_event: threading.Event) -> None:
    """Signal a _run_blocking_loop task to exit and wait for it to actually stop."""
    stop_event.set()
    await task


class _KafkaHeadersCarrier:
    """W3C traceparent carrier adapter for librdkafka headers.

    OTel propagators require a carrier with get/set/keys methods.
    confluent_kafka uses list[tuple[str, bytes]] for headers, same as aiokafka —
    this adapter bridges that format to what OTel's propagate API expects.
    """

    def __init__(self) -> None:
        self._headers: dict[str, str] = {}

    def get(self, key: str, default: list[str] | None = None) -> list[str] | None:
        val = self._headers.get(key)
        return [val] if val is not None else default

    def set(self, key: str, value: str) -> None:
        self[key] = value

    def __setitem__(self, key: str, value: str) -> None:
        self._headers[key] = value

    def keys(self) -> list[str]:
        return list(self._headers.keys())

    def to_confluent_headers(self) -> list[tuple[str, bytes]]:
        return [(k, v.encode()) for k, v in self._headers.items()]


class KafkaProducerClient:
    """Thin wrapper around confluent_kafka.Producer (librdkafka) matching current
    service startup/shutdown patterns.

    librdkafka's Producer needs regular poll() calls to service its internal queue
    and trigger delivery-report callbacks — it has no native asyncio support. This
    wrapper calls poll(0) inline after every produce() for low-latency delivery
    confirmation, plus runs a background poll loop to drain callbacks during idle
    gaps between publishes. The loop runs its full lifetime in ONE dedicated thread
    (a single asyncio.to_thread submission, not one per iteration) — submitting a
    fresh executor task every ~100ms-or-faster tick would flood the shared default
    thread pool's queue under high publish throughput (confirmed: an unthrottled
    per-iteration version pathologically grew to double-digit GB RSS under a fast
    poll() in testing). Producer methods are documented thread-safe for this
    concurrent-poll pattern.
    """

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap = bootstrap_servers
        self._producer: Producer | None = None
        self._poll_task: asyncio.Task | None = None
        self._stop_event: threading.Event | None = None

    async def start(self) -> None:
        """Create the underlying confluent_kafka.Producer and start the poll loop.

        Durability configuration:
          acks='all'                    wait for replica acks, not just leader
          enable.idempotence=True       exactly-once-per-partition producer semantics
          compression.type='lz4'        ~60% bytes saved on JSON, negligible CPU
        """
        logger.info("KafkaProducerClient starting", bootstrap_servers=self._bootstrap)
        self._producer = Producer(
            {
                "bootstrap.servers": self._bootstrap,
                "acks": "all",
                "enable.idempotence": True,
                "compression.type": "lz4",
            }
        )
        self._poll_task, self._stop_event = _run_blocking_loop(self._poll_loop_blocking)
        logger.info("KafkaProducerClient started successfully")

    def _poll_loop_blocking(self, stop_event: threading.Event) -> None:
        """Runs entirely inside the single background thread _run_blocking_loop starts.
        publish() already calls poll(0) inline for low-latency confirmation on the
        common path; this loop exists so callbacks still get serviced (and librdkafka's
        internal queue stays healthy) when nothing is being published.
        """
        producer = self._producer
        assert producer is not None
        while not stop_event.is_set():
            producer.poll(0.1)

    async def stop(self) -> None:
        """Stop the poll loop and flush pending sends."""
        if self._producer is None:
            return
        if self._poll_task is not None and self._stop_event is not None:
            await _stop_blocking_loop(self._poll_task, self._stop_event)
            self._poll_task = None
        await asyncio.to_thread(self._producer.flush, 10.0)

    async def publish(self, topic: str, msg: dict, key: str | None = None) -> None:
        """Publish a dict message to a Kafka topic with an optional routing key.

        Args:
            topic: Kafka topic name (e.g. "dev.indicators").
            msg: Message dict — serialized to JSON bytes internally via orjson.
            key: Optional partition routing key (e.g. "ES:1m") — encoded to bytes.
        """
        if self._producer is None:
            logger.error("KafkaProducerClient.publish called but producer is None!", topic=topic)
            raise RuntimeError("Kafka producer not started")

        # Inject current trace context into Kafka headers (no-op if no TracerProvider)
        carrier = _KafkaHeadersCarrier()
        inject(carrier)
        headers = carrier.to_confluent_headers()

        loop = asyncio.get_running_loop()
        delivery_future: asyncio.Future[None] = loop.create_future()

        def _on_delivery(err: Exception | None, _msg: object) -> None:
            if delivery_future.done():
                return
            if err is not None:
                loop.call_soon_threadsafe(delivery_future.set_exception, KafkaException(err))
            else:
                loop.call_soon_threadsafe(delivery_future.set_result, None)

        try:
            t0 = _time.monotonic()
            # orjson silently serializes NaN/Infinity/-Infinity to `null` (verified
            # empirically 2026-08-03) rather than emitting the non-standard `NaN`
            # literal stdlib json did -- produces spec-compliant JSON that downstream
            # non-Python consumers can actually parse, at the cost of losing the
            # "this was NaN" signal on the wire (becomes indistinguishable from a
            # genuinely missing field). Not a raise-on-serialize case to handle here.
            value = orjson.dumps(msg)
            key_bytes = key.encode() if key else None
            self._producer.produce(
                topic, value=value, key=key_bytes, headers=headers, on_delivery=_on_delivery
            )
            # Non-blocking: drain any already-ready delivery callback immediately
            # rather than waiting for the next _poll_loop tick (up to 100ms away).
            self._producer.poll(0)
            await delivery_future
            KAFKA_PUBLISH_SECONDS.record(_time.monotonic() - t0, {"topic": topic})
        except Exception as e:
            logger.error("Kafka publish failed", topic=topic, key=key, error=str(e))
            raise


class KafkaConsumerClient:
    """Thin wrapper around confluent_kafka.Consumer (librdkafka) matching current
    service consumption patterns. Every blocking librdkafka call runs via
    asyncio.to_thread to avoid stalling the event loop.
    """

    def __init__(
        self,
        *topics: str,
        bootstrap_servers: str,
        group_id: str,
        auto_offset_reset: str = "latest",
        enable_auto_commit: bool = True,
    ) -> None:
        self._topics = list(topics)
        self._consumer = Consumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": auto_offset_reset,
                "enable.auto.commit": enable_auto_commit,
            }
        )

    async def start(self) -> None:
        """Subscribe to topics. Partition assignment happens lazily on first poll()."""
        await asyncio.to_thread(self._consumer.subscribe, self._topics)

    async def stop(self) -> None:
        """Commit pending offsets (if auto-commit), leave consumer group, and close."""
        await asyncio.to_thread(self._consumer.close)

    async def commit(self) -> None:
        """Manually commit offsets for all assigned partitions.

        Only relevant when enable_auto_commit=False.
        """
        await asyncio.to_thread(self._consumer.commit)

    async def seek_to_beginning(self) -> None:
        """Seek all assigned partitions to the earliest offset.

        Call after start() to replay all topic history regardless of any previously
        committed offsets. For a subscribed consumer the seek is applied once
        partitions are assigned by the group coordinator.
        """
        partitions = await asyncio.to_thread(self._consumer.assignment)
        for tp in partitions:
            tp.offset = OFFSET_BEGINNING
            await asyncio.to_thread(self._consumer.seek, tp)

    async def seek_to_end(self) -> None:
        """Seek all assigned partitions to the latest offset.

        Call after start() to skip all historical messages and consume only new
        messages, regardless of any previously committed offsets.
        """
        partitions = await asyncio.to_thread(self._consumer.assignment)
        for tp in partitions:
            tp.offset = OFFSET_END
            await asyncio.to_thread(self._consumer.seek, tp)

    async def skip_lag_if_needed(self, max_lag: int) -> int:
        """Seek to end if total committed lag exceeds max_lag.

        Call after start(). Triggers a short poll to force partition assignment,
        then checks end_offset - position for each partition. If total lag
        exceeds max_lag, seeks all partitions to end and logs the skip.

        Returns the lag found (0 if already caught up or assignment failed).
        Why: live pipeline services seed state from DB at startup; old Kafka
        messages are redundant and cause hours-long reprocessing after restarts.
        """
        partitions = await asyncio.to_thread(self._consumer.assignment)
        if not partitions:
            await asyncio.to_thread(self._consumer.poll, 2.0)
            partitions = await asyncio.to_thread(self._consumer.assignment)
        if not partitions:
            return 0

        total_lag = await self._calculate_lag(partitions)

        if total_lag > max_lag:
            # commit() with no explicit offsets commits the consumer's last-polled
            # position, NOT wherever seek() last pointed it -- seek() alone doesn't
            # update that position until another poll() actually fetches from it
            # (confirmed empirically: a bare commit() after seek(OFFSET_END) silently
            # committed the pre-seek position instead). Resolve OFFSET_END to its real
            # numeric high-watermark and commit that explicitly per partition.
            offsets_to_commit = []
            for tp in partitions:
                _low, high = await asyncio.to_thread(
                    self._consumer.get_watermark_offsets, tp, timeout=10.0
                )
                tp.offset = OFFSET_END
                await asyncio.to_thread(self._consumer.seek, tp)
                offsets_to_commit.append(TopicPartition(tp.topic, tp.partition, high))
            await asyncio.to_thread(self._consumer.commit, offsets=offsets_to_commit)

            # Verify the seek actually persisted by re-checking lag
            post_seek_lag = await self._calculate_lag(partitions)

            if post_seek_lag > max_lag:
                logger.critical(
                    "kafka_consumer.lag_skip_failed",
                    pre_seek_lag=total_lag,
                    post_seek_lag=post_seek_lag,
                    max_lag=max_lag,
                    error="seek_to_end+commit did not persist — consumer will reprocess from old offset",
                )
                raise RuntimeError(
                    f"skip_lag_if_needed failed: lag was {total_lag}, still {post_seek_lag} after seek_to_end+commit. "
                    "Check Redpanda connectivity and consumer group state."
                )

            logger.info(
                "kafka_consumer.lag_skip",
                lag=total_lag,
                max_lag=max_lag,
                action="seeked_to_end_verified",
                post_seek_lag=post_seek_lag,
            )

        return total_lag

    async def _calculate_lag(self, partitions: list[TopicPartition]) -> int:
        """Calculate total lag across partitions.

        Returns sum of (end_offset - committed_offset) for all assigned partitions.
        Uses committed() rather than position() deliberately: position() reflects the
        consumer's last actual fetch and does NOT update just because seek() was
        called (confirmed empirically -- it stays stale until another poll() actually
        fetches from the new position), so it can't verify a seek+commit took effect.
        committed() is also the semantically correct check for this method's purpose
        (what a restart will resume from), not just a seek-verification workaround.
        Returns 0 if partition assignment fails or offset queries fail.
        """
        total_lag = 0
        for tp in partitions:
            try:
                # Independent RPCs per partition -- run concurrently rather than serially.
                (_low, high), committed = await asyncio.gather(
                    asyncio.to_thread(self._consumer.get_watermark_offsets, tp, timeout=10.0),
                    asyncio.to_thread(self._consumer.committed, [tp], 10.0),
                )
                current = committed[0].offset if committed and committed[0].offset >= 0 else _low
                total_lag += max(0, high - current)
            except Exception as e:
                logger.warning(
                    "kafka_consumer.position_failed",
                    topic_partition=tp,
                    error=str(e),
                )
        return total_lag

    async def getmany(self, *, timeout_ms: int = 0, max_records: int = 100) -> list:
        """Non-blocking batch fetch — thin delegation to confluent_kafka's consume().

        Returns [Message, ...] immediately with any buffered messages (when
        timeout_ms=0). Used by agents that need to drain messages without blocking
        (e.g. BarAuditor contract cache invalidation).
        """
        return await asyncio.to_thread(
            self._consumer.consume, num_messages=max_records, timeout=timeout_ms / 1000
        )

    def _consume_loop_blocking(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
        stop_event: threading.Event,
    ) -> None:
        """Runs entirely in one dedicated background thread for messages()'s whole
        lifetime (a single asyncio.to_thread submission, not one per message) —
        submitting a fresh executor task per poll() call would flood the shared
        default thread pool's queue under high consume throughput, the same failure
        mode fixed in KafkaProducerClient's poll loop.

        Batch-polls via consume() rather than one message per poll() call: pushing
        each message across the thread boundary individually means paying a full
        run_coroutine_threadsafe round trip (schedule + block-and-wait) per message
        on the path this whole migration exists to speed up. Handing a whole batch
        across in one round trip amortizes that cost over up to _CONSUME_BATCH_SIZE
        messages instead. queue.put() on a full queue still blocks this thread
        (via .result()), so backpressure against a slow consumer is preserved —
        just applied per-batch instead of per-message.
        """
        consumer = self._consumer
        while not stop_event.is_set():
            batch = consumer.consume(num_messages=_CONSUME_BATCH_SIZE, timeout=1.0)
            if not batch:
                continue
            asyncio.run_coroutine_threadsafe(_put_batch(queue, batch), loop).result()

    async def messages(self) -> AsyncGenerator[tuple[str, str | None, dict]]:
        """Yield (topic, key, payload_dict) tuples from subscribed topics.

        Yields:
            A 3-tuple of:
              - topic (str): The Kafka topic the message arrived on.
              - key (str | None): Decoded message key (e.g. "ES:1m"), or None if no key.
              - payload (dict): Decoded JSON payload dict.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=_CONSUME_BATCH_SIZE)
        consume_task, stop_event = _run_blocking_loop(
            functools.partial(self._consume_loop_blocking, loop, queue)
        )
        try:
            while True:
                msg = await queue.get()
                if msg.error():
                    logger.error("Kafka consumer error", error=str(msg.error()))
                    continue

                topic = msg.topic()
                key = msg.key().decode() if msg.key() else None
                try:
                    payload = orjson.loads(msg.value())
                except Exception as e:
                    raw_value = msg.value()
                    logger.error(
                        "Kafka message decode failed",
                        topic=topic,
                        key=key,
                        value_type=type(raw_value).__name__,
                        error=str(e),
                        value_preview=raw_value[:200] if raw_value else None,
                    )
                    continue

                # Extract trace context from Kafka headers (no-op if no traceparent)
                carrier = _KafkaHeadersCarrier()
                for header_key, header_val in msg.headers() or []:
                    carrier.set(header_key, header_val.decode())
                ctx = extract(carrier)
                token = otel_context.attach(ctx)
                try:
                    yield topic, key, payload
                finally:
                    otel_context.detach(token)
        finally:
            await _stop_blocking_loop(consume_task, stop_event)
