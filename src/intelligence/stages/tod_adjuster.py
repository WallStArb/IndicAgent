"""Time-of-Day Adjuster stage — applies TOD win-rate multipliers."""

from __future__ import annotations

import zoneinfo
from datetime import datetime

import structlog

from src.config.settings import Settings
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_regime_gated, topic_tod_adjusted
from src.intelligence.stages.base import Stage

logger = structlog.get_logger(__name__)

_ET = zoneinfo.ZoneInfo("America/New_York")

# TOD session priors — mirrored from signal_generator_service.py
# Key: (regime_type, hour_et) → prior win-rate ratio (>1.0 = favourable, <1.0 = avoid)
_TOD_SESSION_PRIORS: dict[tuple[str, int], float] = {
    ("trend",           9): 1.10,
    ("mean_reversion",  9): 1.00,
    ("any",             9): 1.00,
    ("trend",          11): 0.90,
    ("mean_reversion", 11): 0.90,
    ("any",            11): 0.90,
    ("trend",          12): 0.90,
    ("mean_reversion", 12): 0.90,
    ("any",            12): 0.90,
    ("mean_reversion", 14): 1.08,
    ("any",            15): 1.10,
}

_TOD_ALPHA: float = 20.0        # Bayesian prior weight (virtual observations)
_TOD_CLAMP: tuple[float, float] = (0.7, 1.3)   # Hard multiplier bounds


class TODAdjusterService(Stage):
    """Applies time-of-day Bayesian multipliers to signal confidence.

    Multipliers are grouped by (regime_type, tf, hour_et) — up to 120 cells.
    Falls back to session priors from signal_generator_service when DB not loaded.
    Multiplier is clamped to [0.7, 1.3] to prevent extreme adjustments.

    Inputs:  pipeline.regime_gated
    Outputs: pipeline.tod_adjusted

    Attribution:
    - value_added: after_confidence - before_confidence
    - inputs: tod_multiplier, regime_type, tf, hour_et
    """

    def __init__(self, settings: Settings) -> None:
        bootstrap = settings.kafka_bootstrap_servers
        env = settings.env_name

        input_topic = topic_regime_gated(env)
        output_topic = topic_tod_adjusted(env)

        consumer = KafkaConsumerClient(
            input_topic,
            bootstrap_servers=bootstrap,
            group_id="tod_adjuster_group",
        )
        producer = KafkaProducerClient(bootstrap)
        attribution_producer = KafkaProducerClient(bootstrap)

        super().__init__(
            stage_name="tod_adjuster",
            input_topic=input_topic,
            output_topic=output_topic,
            consumer=consumer,
            producer=producer,
            attribution_producer=attribution_producer,
            env=env,
        )

        # Populated from DB every ~4h by a periodic loader (Phase 40-04 integration)
        self.tod_multipliers: dict[tuple[str, str, int], float] = {}
        self._last_multiplier_load: float = 0.0

    async def process(self, event) -> dict:
        """Apply TOD multiplier to signal confidence.

        Key: (regime_type, tf, hour_et). Falls back to session priors if cell absent.
        """
        result = event.model_dump()

        features = event.features if isinstance(event.features, dict) else {}
        before_confidence = float(features.get("confidence", 0.0))

        regime_type = result.get("regime_type_at_fire", "any")
        tf = event.tf if hasattr(event, "tf") else result.get("tf", "1m")

        # Convert timestamp to ET hour
        ts = event.ts if hasattr(event, "ts") else None
        if ts is None:
            ts_str = result.get("ts") or result.get("timestamp", "")
            if ts_str:
                ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        hour_et = ts.astimezone(_ET).hour if ts else 10  # default to market hours

        # Lookup DB multiplier first
        cell_key = (regime_type, tf, hour_et)
        tod_multiplier = self.tod_multipliers.get(cell_key)

        if tod_multiplier is None:
            # Fall back to session priors
            tod_multiplier = _TOD_SESSION_PRIORS.get((regime_type, hour_et), 1.0)

        # Clamp
        tod_multiplier = max(_TOD_CLAMP[0], min(_TOD_CLAMP[1], tod_multiplier))

        after_confidence = round(before_confidence * tod_multiplier, 4)

        # Propagate
        result["confidence"] = after_confidence
        if isinstance(result.get("features"), dict):
            result["features"]["confidence"] = after_confidence
        result["tod_multiplier"] = tod_multiplier
        result["attribution_reason"] = (
            f"TOD:{regime_type},{tf},{hour_et}h={tod_multiplier:.3f}"
        )
        result["attribution_inputs"] = {
            "tod_multiplier": tod_multiplier,
            "regime_type": regime_type,
            "timeframe": tf,
            "hour_et": hour_et,
            "before_confidence": before_confidence,
            "after_confidence": after_confidence,
        }

        logger.debug(
            "[tod_adjuster] Applied TOD multiplier",
            symbol=event.symbol,
            timeframe=tf,
            regime_type=regime_type,
            hour_et=hour_et,
            tod_multiplier=tod_multiplier,
            before=before_confidence,
            after=after_confidence,
        )

        return result
