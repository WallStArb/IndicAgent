"""Pipeline stage base class for DAG-based signal processing.

All 6 stage services (QualityGate, RegimeGate, TODAdjuster, Calibrator,
Ranker, WinnerSelector) inherit from this base class, which provides:

- Consistent Kafka consumer/producer lifecycle
- Circuit breaker for fault tolerance
- Data quality validation at input and output
- Attribution emission to side-channel topic
- Prometheus metrics for all stage operations
- Graceful bypass on failure (events pass through unchanged)

Renaissance principle: All status/outcome handling uses typed enums.
Raw string literals ("pending", "target_1", etc.) are NEVER used in stage code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import structlog
from prometheus_client import Counter, Gauge
from pydantic import ValidationError  # noqa: I001

from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_attribution
from src.intelligence.enums.signal_outcome import (
    SignalOutcome,  # noqa: F401 — re-exported for subclasses
)
from src.intelligence.enums.signal_status import (
    SignalStatus,  # noqa: F401 — re-exported for subclasses
)
from src.intelligence.monitoring.data_quality_monitor import DataQualityMonitor
from src.intelligence.schemas import IntelligenceEvent
from src.observability.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = structlog.get_logger(__name__)

# Map circuit state values to numeric gauge values for Prometheus
_CIRCUIT_STATE_GAUGE_VALUES = {"closed": 0.0, "open": 1.0, "half_open": 2.0}


class Stage(ABC):
    """Base class for all DAG pipeline stages.

    Each stage:
    - Subscribes to one input Kafka topic
    - Validates input with DataQualityMonitor
    - Processes events through CircuitBreaker protection
    - Emits attribution metadata to side-channel topic
    - Publishes processed output to next stage topic
    - Degrades gracefully: bypasses on circuit open or processing failure

    Subclasses must implement:
        async def process(self, event: IntelligenceEvent) -> dict

    Constructor parameters
    ----------------------
    stage_name : str
        Unique stage identifier (e.g. "quality_gated"). Used as DQM schema key.
    input_topic : str
        Kafka topic to consume from.
    output_topic : str
        Kafka topic to publish processed results to.
    consumer : KafkaConsumerClient
        Pre-constructed consumer (injected for testability).
    producer : KafkaProducerClient
        Pre-constructed producer for output topic.
    attribution_producer : KafkaProducerClient
        Pre-constructed producer for attribution side channel.
    """

    def __init__(
        self,
        stage_name: str,
        input_topic: str,
        output_topic: str,
        consumer: KafkaConsumerClient,
        producer: KafkaProducerClient,
        attribution_producer: KafkaProducerClient,
        env: str = "development",
    ) -> None:
        self.stage_name = stage_name
        self._output_topic = output_topic
        self._attribution_topic = topic_attribution(env)

        # Kafka clients
        self.consumer = consumer
        self.producer = producer
        self.attribution_producer = attribution_producer

        # Fault tolerance and data quality
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout_sec=60)
        self.data_quality_monitor = DataQualityMonitor(stage_name)
        self._last_circuit_state: str = "closed"

        # Prometheus labeled counters/gauges
        # Use prometheus_client directly (not metrics.counter/gauge) to support labels.
        self.events_consumed = Counter(
            f"stage_{stage_name}_events_consumed_total",
            f"Total events consumed by {stage_name} stage",
            ["stage", "symbol", "timeframe"],
        )
        self.events_produced = Counter(
            f"stage_{stage_name}_events_produced_total",
            f"Total events produced by {stage_name} stage",
            ["stage", "symbol", "timeframe"],
        )
        self.processing_errors = Counter(
            f"stage_{stage_name}_errors_total",
            f"Total processing errors in {stage_name} stage",
            ["stage", "error_type"],
        )
        self.circuit_state = Gauge(
            f"stage_{stage_name}_circuit_state",
            f"Circuit breaker state for {stage_name} (0=closed, 1=open, 2=half_open)",
            ["stage"],
        )

        logger.info("Stage initialized", stage=stage_name)

    @abstractmethod
    async def process(self, event: IntelligenceEvent) -> dict:
        """Process an intelligence event through this stage.

        Parameters
        ----------
        event : IntelligenceEvent
            Validated input event from upstream topic.

        Returns
        -------
        dict
            Processed event with stage-specific transformations applied.
            Must include at minimum the fields defined in the stage schema.

        Raises
        ------
        NotImplementedError
            Always — subclasses must override this method.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.process() must be implemented")

    async def emit_attribution(
        self,
        event: IntelligenceEvent,
        result: dict,
        value_added: float = 0.0,
        reason: str = "",
    ) -> None:
        """Emit attribution metadata to the pipeline.attribution side channel.

        Parameters
        ----------
        event : IntelligenceEvent
            The original input event before processing.
        result : dict
            The processed output from this stage.
        value_added : float
            Delta between output confidence and input confidence.
        reason : str
            Human-readable explanation of what this stage contributed.
        """
        attribution_payload = {
            "symbol": event.symbol,
            "timeframe": event.tf,
            "timestamp": event.ts.isoformat(),
            "stage": self.stage_name,
            "before_confidence": 0.0,
            "after_confidence": result.get("confidence", 0.0),
            "value_added": round(value_added, 4),
            "reason": reason,
            "inputs": result.get("attribution_inputs", {}),
        }

        await self.attribution_producer.publish(
            topic=self._attribution_topic,
            msg=attribution_payload,
            key=f"{event.symbol}:{event.tf}",
        )

    async def run(self) -> None:
        """Main processing loop.

        Flow per message:
        1. Deserialize IntelligenceEvent from Kafka message
        2. Validate input with DataQualityMonitor (drop invalid)
        3. Call process() through CircuitBreaker
        4. On CircuitOpenError: bypass — pass event through unchanged
        5. On process() exception: bypass with error details
        6. Validate output (drop invalid)
        7. Emit attribution (skipped when bypassed)
        8. Publish to next stage topic
        9. Update metrics

        Outer exception handler ensures errors never kill the loop.
        """
        logger.info("Starting stage run loop", stage=self.stage_name)

        # Start Kafka clients before entering message loop
        await self.consumer.start()
        try:
            await self.producer.start()
            await self.attribution_producer.start()
        except Exception:
            await self.consumer.stop()
            raise

        try:
            async for _topic, _key, raw_payload in self.consumer.messages():
                try:
                    # Parse IntelligenceEvent
                    try:
                        event = IntelligenceEvent.model_validate(raw_payload)
                    except (ValidationError, TypeError) as exc:
                        logger.error(
                            "Failed to parse IntelligenceEvent",
                            stage=self.stage_name,
                            error=str(exc),
                        )
                        self.processing_errors.labels(
                            stage=self.stage_name,
                            error_type="parse_error",
                        ).inc()
                        continue

                    symbol = event.symbol
                    timeframe = event.tf

                    self.events_consumed.labels(
                        stage=self.stage_name,
                        symbol=symbol,
                        timeframe=timeframe,
                    ).inc()

                    # Data quality check (input)
                    if not await self.data_quality_monitor.validate_input(raw_payload):
                        logger.warning(
                            "Input validation failed — dropping message",
                            stage=self.stage_name,
                            symbol=symbol,
                            timeframe=timeframe,
                        )
                        self.processing_errors.labels(
                            stage=self.stage_name,
                            error_type="input_validation",
                        ).inc()
                        continue

                    # Process through circuit breaker
                    try:
                        result = await self.circuit_breaker.call(self.process, event)

                    except CircuitOpenError:
                        logger.warning(
                            "Circuit OPEN — bypassing stage",
                            stage=self.stage_name,
                            symbol=symbol,
                            timeframe=timeframe,
                        )
                        result = raw_payload.copy()
                        result["bypassed"] = True
                        result["bypass_reason"] = "circuit_open"
                        self.processing_errors.labels(
                            stage=self.stage_name,
                            error_type="circuit_open",
                        ).inc()

                    except Exception as exc:
                        logger.error(
                            "Process failed — bypassing stage",
                            stage=self.stage_name,
                            symbol=symbol,
                            timeframe=timeframe,
                            error=str(exc),
                        )
                        result = raw_payload.copy()
                        result["bypassed"] = True
                        result["bypass_reason"] = "process_error"
                        result["error"] = str(exc)
                        self.circuit_breaker.record_failure()
                        self.processing_errors.labels(
                            stage=self.stage_name,
                            error_type="process_error",
                        ).inc()

                    # Data quality check (output)
                    if not await self.data_quality_monitor.validate_output(result):
                        logger.error(
                            "Output validation failed — dropping message",
                            stage=self.stage_name,
                            symbol=symbol,
                            timeframe=timeframe,
                        )
                        self.processing_errors.labels(
                            stage=self.stage_name,
                            error_type="output_validation",
                        ).inc()
                        continue

                    # Emit attribution (only for non-bypassed events)
                    if not result.get("bypassed", False):
                        after_conf = result.get("confidence", 0.0)
                        reason = result.pop("attribution_reason", "")
                        await self.emit_attribution(
                            event,
                            result,
                            value_added=after_conf,
                            reason=reason,
                        )

                    # Publish to next stage
                    await self.producer.publish(
                        topic=self._output_topic,
                        msg=result,
                        key=f"{symbol}:{timeframe}",
                    )

                    self.events_produced.labels(
                        stage=self.stage_name,
                        symbol=symbol,
                        timeframe=timeframe,
                    ).inc()

                    # Update circuit state gauge only on state change (avoids lock per message)
                    current_state = self.circuit_breaker.state.value
                    if current_state != self._last_circuit_state:
                        self._last_circuit_state = current_state
                        self.circuit_state.labels(stage=self.stage_name).set(
                            _CIRCUIT_STATE_GAUGE_VALUES.get(current_state, 0.0)
                        )

                except Exception as exc:
                    logger.exception(
                        "Unexpected error in run loop — continuing",
                        stage=self.stage_name,
                        error=str(exc),
                    )
                    self.processing_errors.labels(
                        stage=self.stage_name,
                        error_type="unexpected",
                    ).inc()

        finally:
            # Graceful shutdown: stop Kafka clients (runs on normal exit and CancelledError)
            await self.consumer.stop()
            await self.producer.stop()
            await self.attribution_producer.stop()

        logger.info("Stage run loop stopped", stage=self.stage_name)
