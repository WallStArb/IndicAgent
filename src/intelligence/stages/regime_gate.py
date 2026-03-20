"""Regime Gate stage — suppresses signals based on HMM regime."""

from __future__ import annotations

import structlog

from src.config.settings import Settings
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_quality_gated, topic_regime_gated
from src.intelligence.stages.base import Stage

logger = structlog.get_logger(__name__)

# Allowed HMM regime values per plugin regime_type
# 0 = ranging/mean-reversion, 1 = trending, 2 = strong trend
_REGIME_MAP: dict[str, list[int]] = {
    "trend": [1, 2],
    "mean_reversion": [0],
    "any": [0, 1, 2],
}

_REGIME_PROB_MIN = 0.55   # Minimum HMM regime probability to trust the regime label
_REGIME_DUR_MIN = 3       # Minimum bars regime must have persisted


class RegimeGateService(Stage):
    """Suppresses signals when HMM regime is incompatible with plugin regime_type.

    Three-tier gate (priority order):
    1. hmm_regime_prob < 0.55  → suppress (regime label not confident)
    2. hmm_regime_duration < 3 → suppress (regime too new to trust)
    3. hmm_regime not in allowed regimes for plugin regime_type → suppress

    Inputs:  pipeline.quality_gated
    Outputs: pipeline.regime_gated

    Attribution:
    - value_added: 0.0 (gate is binary — no confidence change, just suppress flag)
    - reason: suppression_reason or "Regime eligible"
    """

    def __init__(self, settings: Settings) -> None:
        bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")
        env = getattr(settings, "env_name", "development")

        input_topic = topic_quality_gated(env)
        output_topic = topic_regime_gated(env)

        consumer = KafkaConsumerClient(
            input_topic,
            bootstrap_servers=bootstrap,
            group_id="regime_gate_group",
        )
        producer = KafkaProducerClient(bootstrap)
        attribution_producer = KafkaProducerClient(bootstrap)

        super().__init__(
            stage_name="regime_gate",
            input_topic=input_topic,
            output_topic=output_topic,
            consumer=consumer,
            producer=producer,
            attribution_producer=attribution_producer,
        )

    async def process(self, event) -> dict:
        """Apply regime gating to signal.

        Reads regime_data from event.features. Passes through if no regime_data.
        """
        result = event.model_dump()

        features = event.features if isinstance(event.features, dict) else {}
        regime_data = features.get("regime_data")

        # No regime data → pass through (graceful degradation)
        if regime_data is None:
            result["regime_eligible"] = True
            result["suppression_reason"] = None
            result["attribution_reason"] = "No regime data — gate skipped"
            return result

        hmm_regime = regime_data.get("hmm_regime")
        hmm_regime_prob = float(regime_data.get("hmm_regime_prob", 0.0))
        hmm_regime_duration = int(regime_data.get("hmm_regime_duration", 0))

        plugin_regime_type = result.get("regime_type", "any")
        allowed = _REGIME_MAP.get(plugin_regime_type, [0, 1, 2])

        regime_eligible = True
        suppression_reason = None

        if hmm_regime_prob < _REGIME_PROB_MIN:
            regime_eligible = False
            suppression_reason = "regime_prob"
        elif hmm_regime_duration < _REGIME_DUR_MIN:
            regime_eligible = False
            suppression_reason = "regime_duration"
        elif hmm_regime is not None and int(hmm_regime) not in allowed:
            regime_eligible = False
            suppression_reason = "regime_type"

        result["regime_eligible"] = regime_eligible
        result["suppression_reason"] = suppression_reason
        result["attribution_reason"] = (
            f"regime_gate:{suppression_reason}" if not regime_eligible else "Regime eligible"
        )
        result["attribution_inputs"] = {
            "hmm_regime": hmm_regime,
            "hmm_regime_prob": hmm_regime_prob,
            "hmm_regime_duration": hmm_regime_duration,
            "plugin_regime_type": plugin_regime_type,
        }

        logger.debug(
            "[regime_gate] Applied regime gate",
            symbol=event.symbol,
            timeframe=event.tf,
            regime_eligible=regime_eligible,
            suppression_reason=suppression_reason,
        )

        return result
