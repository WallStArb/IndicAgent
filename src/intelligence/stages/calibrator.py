"""Calibrator stage — applies isotonic regression confidence calibration."""

from __future__ import annotations

import numpy as np
import structlog

from src.config.settings import Settings
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_calibrated, topic_tod_adjusted
from src.intelligence.stages.base import Stage

logger = structlog.get_logger(__name__)


class CalibratorService(Stage):
    """Applies isotonic regression calibration curves per (plugin_name, timeframe).

    Curves are loaded from the confidence_calibration table by a periodic loader
    (Phase 40-04 integration). When no curve is available for a (plugin, tf) pair,
    confidence passes through unchanged.

    Uses np.interp for fast monotonic curve lookup — same approach as aggregator.py.

    Inputs:  pipeline.tod_adjusted
    Outputs: pipeline.calibrated

    Attribution:
    - value_added: calibrated_confidence - raw_confidence
    - inputs: raw_confidence, calibrated_confidence, plugin_name, tf
    """

    def __init__(self, settings: Settings) -> None:
        bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")
        env = getattr(settings, "env_name", "development")

        input_topic = topic_tod_adjusted(env)
        output_topic = topic_calibrated(env)

        consumer = KafkaConsumerClient(
            input_topic,
            bootstrap_servers=bootstrap,
            group_id="calibrator_group",
        )
        producer = KafkaProducerClient(bootstrap)
        attribution_producer = KafkaProducerClient(bootstrap)

        super().__init__(
            stage_name="calibrator",
            input_topic=input_topic,
            output_topic=output_topic,
            consumer=consumer,
            producer=producer,
            attribution_producer=attribution_producer,
        )

        # {(plugin_name, tf): (breakpoints, values)} — loaded from DB
        self.calibration_curves: dict[tuple[str, str], tuple[list[float], list[float]]] = {}
        self._last_curve_load: float = 0.0

    async def process(self, event) -> dict:
        """Apply isotonic calibration curve to signal confidence.

        Passthrough when no curve available for (plugin_name, tf) pair.
        """
        result = event.model_dump()

        features = event.features if isinstance(event.features, dict) else {}
        raw_confidence = float(features.get("confidence", 0.0))

        plugin_name = result.get("setup_plugin", "unknown")
        tf = event.tf if hasattr(event, "tf") else result.get("tf", "1m")

        curve_key = (plugin_name, tf)
        curve = self.calibration_curves.get(curve_key)

        if curve is None:
            # No calibration curve — pass through unchanged
            calibrated_confidence = raw_confidence
            result["attribution_reason"] = f"No calibration curve for {plugin_name}:{tf}"
        else:
            breakpoints, values = curve
            calibrated_confidence = round(
                float(np.interp(raw_confidence, breakpoints, values)), 4
            )
            result["attribution_inputs"] = {
                "raw_confidence": raw_confidence,
                "calibrated_confidence": calibrated_confidence,
                "plugin_name": plugin_name,
                "timeframe": tf,
            }
            result["attribution_reason"] = f"Calibrated:{plugin_name}:{tf}"

        # Propagate calibrated confidence
        result["confidence"] = calibrated_confidence
        result["calibrated_confidence"] = calibrated_confidence
        if isinstance(result.get("features"), dict):
            result["features"]["confidence"] = calibrated_confidence

        logger.debug(
            "[calibrator] Applied calibration",
            symbol=event.symbol,
            timeframe=tf,
            plugin_name=plugin_name,
            raw_confidence=raw_confidence,
            calibrated_confidence=calibrated_confidence,
        )

        return result
