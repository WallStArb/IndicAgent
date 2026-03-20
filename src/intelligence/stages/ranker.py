"""Ranker stage — computes adjusted_rank for signals by performance-weighted priority."""

from __future__ import annotations

import structlog

from src.config.settings import Settings
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_calibrated, topic_ranked
from src.intelligence.stages.base import Stage

logger = structlog.get_logger(__name__)

# Setup priority from aggregator.py — lower value = higher priority when sorted ascending
SETUP_PRIORITY: dict[str, int] = {
    "trad_MeanReversion": 1,
    "trad_SqueezeExpansion": 2,
    "trad_TrendFollowing": 3,
    "trad_MTFAlignment": 4,
    "trad_LiquiditySweepReclaim": 5,
}


class RankerService(Stage):
    """Computes adjusted_rank = priority × perf_multiplier for each signal.

    Signals with lower adjusted_rank win in the WinnerSelector sort.
    perf_weights loaded from setup_performance table every 15 min by a periodic
    loader (Phase 40-04 integration). Defaults to 1.0 (neutral) when absent.

    Inputs:  pipeline.calibrated
    Outputs: pipeline.ranked

    Attribution:
    - value_added: 0.0 (ranking does not change confidence)
    - inputs: priority, perf_multiplier, adjusted_rank
    """

    def __init__(self, settings: Settings) -> None:
        bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")
        env = getattr(settings, "env_name", "development")

        input_topic = topic_calibrated(env)
        output_topic = topic_ranked(env)

        consumer = KafkaConsumerClient(
            input_topic,
            bootstrap_servers=bootstrap,
            group_id="ranker_group",
        )
        producer = KafkaProducerClient(bootstrap)
        attribution_producer = KafkaProducerClient(bootstrap)

        super().__init__(
            stage_name="ranker",
            input_topic=input_topic,
            output_topic=output_topic,
            consumer=consumer,
            producer=producer,
            attribution_producer=attribution_producer,
        )

        # {(plugin_name, tf): perf_multiplier} — loaded from setup_performance table
        self.perf_weights: dict[tuple[str, str], float] = {}
        self._last_weight_load: float = 0.0

    async def process(self, event) -> dict:
        """Compute adjusted_rank for the signal.

        adjusted_rank = SETUP_PRIORITY * perf_multiplier
        Lower = higher priority in WinnerSelector sort.
        """
        result = event.model_dump()

        plugin_name = result.get("setup_plugin", "unknown")
        tf = event.tf if hasattr(event, "tf") else result.get("tf", "1m")

        priority = SETUP_PRIORITY.get(plugin_name, 999)
        perf_multiplier = self.perf_weights.get((plugin_name, tf), 1.0)
        adjusted_rank = round(priority * perf_multiplier, 4)

        result["adjusted_rank"] = adjusted_rank
        result["perf_multiplier"] = perf_multiplier
        result["attribution_reason"] = (
            f"Ranked:pri={priority},perf={perf_multiplier:.2f},rank={adjusted_rank}"
        )
        result["attribution_inputs"] = {
            "priority": priority,
            "perf_multiplier": perf_multiplier,
            "adjusted_rank": adjusted_rank,
        }

        logger.debug(
            "[ranker] Computed adjusted_rank",
            symbol=event.symbol,
            timeframe=tf,
            plugin_name=plugin_name,
            priority=priority,
            perf_multiplier=perf_multiplier,
            adjusted_rank=adjusted_rank,
        )

        return result
