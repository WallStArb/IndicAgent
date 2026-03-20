"""Quality Gate stage — applies Hurst×Entropy and drift penalty multipliers."""

from __future__ import annotations

import structlog

from src.config.settings import Settings
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_intelligence, topic_quality_gated
from src.intelligence.stages.base import Stage

logger = structlog.get_logger(__name__)


class QualityGateService(Stage):
    """Applies Hurst×Entropy and KS drift penalty multipliers to signal confidence.

    Inputs:  intelligence:SYMBOL:TF (I7 signal events with quality features)
    Outputs: pipeline.quality_gated

    Attribution:
    - value_added: after_confidence - before_confidence (negative = suppression)
    - inputs: hurst_quality, entropy_quality, drift_penalty
    """

    def __init__(self, settings: Settings) -> None:
        bootstrap = settings.kafka_bootstrap_servers
        env = settings.env_name

        input_topic = topic_intelligence(env)
        output_topic = topic_quality_gated(env)

        consumer = KafkaConsumerClient(
            input_topic,
            bootstrap_servers=bootstrap,
            group_id="quality_gate_group",
        )
        producer = KafkaProducerClient(bootstrap)
        attribution_producer = KafkaProducerClient(bootstrap)

        super().__init__(
            stage_name="quality_gate",
            input_topic=input_topic,
            output_topic=output_topic,
            consumer=consumer,
            producer=producer,
            attribution_producer=attribution_producer,
            env=env,
        )

    async def process(self, event) -> dict:
        """Apply quality multipliers to signal confidence.

        Reads hurst_trend_quality, entropy_quality, and drift_penalty from
        event.features. Applies min(hurst_q, entropy_q) then drift_penalty.
        """
        result = event.model_dump()

        features = event.features if isinstance(event.features, dict) else {}
        before_confidence = float(features.get("confidence", 0.0))

        # Hurst×Entropy quality gate: use min() not product (correlated measures)
        hurst_quality = float(features.get("hurst_trend_quality", 1.0))
        entropy_quality = float(features.get("entropy_quality", 1.0))
        quality_multiplier = min(hurst_quality, entropy_quality)

        after_confidence = round(before_confidence * quality_multiplier, 4)

        # KS drift penalty — read pre-computed float from features (default 1.0 = no penalty)
        drift_penalty = float(features.get("drift_penalty", 1.0))
        after_confidence = round(after_confidence * drift_penalty, 4)

        # Propagate updated confidence
        result["confidence"] = after_confidence
        if isinstance(result.get("features"), dict):
            result["features"]["confidence"] = after_confidence

        result["attribution_reason"] = (
            f"quality_gate:hurst={hurst_quality:.2f},entropy={entropy_quality:.2f},"
            f"drift={drift_penalty:.2f}"
        )
        result["attribution_inputs"] = {
            "hurst_quality": hurst_quality,
            "entropy_quality": entropy_quality,
            "drift_penalty": drift_penalty,
            "before_confidence": before_confidence,
            "after_confidence": after_confidence,
        }

        logger.debug(
            "[quality_gate] Applied multipliers",
            symbol=event.symbol,
            timeframe=event.tf,
            before=before_confidence,
            after=after_confidence,
            hurst_quality=hurst_quality,
            entropy_quality=entropy_quality,
            drift_penalty=drift_penalty,
        )

        return result
