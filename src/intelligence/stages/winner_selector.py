"""Winner Selector stage — selects winning signal using CIS or priority/majority."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import structlog

from src.config.settings import Settings
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_ranked, topic_winner
from src.intelligence.enums.signal_status import SignalStatus
from src.intelligence.stages.base import Stage
from src.intelligence.trading.cis_scorer import CISScorer

logger = structlog.get_logger(__name__)

_CONFIDENCE_BOOST_PER_AGREE = 0.05


class WinnerSelectorService(Stage):
    """Selects winning signal using CIS override or priority/majority tiebreak.

    Collects ranked signals for the current bar in an in-memory buffer.
    On bar completion (detected by bar boundary marker — wired in Phase 40-04),
    selects winner and emits to pipeline.winner.

    CIS override path: picks highest-priority signal matching CIS direction,
    boosts confidence by 0.05 per additional agreeing plugin.
    Fallback path: majority direction, then sort by adjusted_rank ascending.

    ENUM RULE: Never use raw "pending"/"suppressed" strings.
    Always use SignalStatus.PENDING.value / SignalStatus.REGIME_SUPPRESSED.value.

    Inputs:  pipeline.ranked
    Outputs: pipeline.winner

    Attribution:
    - value_added: 0.0 (selection does not change confidence)
    - inputs: resolution_method, num_signals_fired, winner_plugin_name
    """

    def __init__(self, settings: Settings) -> None:
        bootstrap = settings.kafka_bootstrap_servers
        env = settings.env_name

        input_topic = topic_ranked(env)
        output_topic = topic_winner(env)

        consumer = KafkaConsumerClient(
            input_topic,
            bootstrap_servers=bootstrap,
            group_id="winner_selector_group",
        )
        producer = KafkaProducerClient(bootstrap)
        attribution_producer = KafkaProducerClient(bootstrap)

        super().__init__(
            stage_name="winner_selector",
            input_topic=input_topic,
            output_topic=output_topic,
            consumer=consumer,
            producer=producer,
            attribution_producer=attribution_producer,
            env=env,
        )

        # Buffer: {(symbol, tf): [signal_dicts]} — cleared after each bar
        self._bar_buffer: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self._cis_scorer = CISScorer()

    async def process(self, event) -> dict:
        """Buffer signal for current bar. Returns buffered status.

        Bar completion detection and winner emission is wired in Phase 40-04.
        """
        key = (event.symbol, event.tf if hasattr(event, "tf") else "1m")
        self._bar_buffer[key].append(event.model_dump())

        return {
            "status": "buffered",
            "signal_count": len(self._bar_buffer[key]),
        }

    async def _select_winner_for_bar(
        self,
        symbol: str,
        tf: str,
        signals: list[dict],
    ) -> dict[str, Any] | None:
        """Select winning signal from all ranked signals for a completed bar.

        Parameters
        ----------
        symbol : str
        tf : str
        signals : list[dict]
            All ranked signals for this bar (regime_eligible may be True or False).

        Returns
        -------
        dict | None
            None if no signals provided.
            Otherwise: {selected_signal, all_ranked, resolution_method, ...}
        """
        if not signals:
            return None

        # Separate active (eligible) from suppressed
        active = [s for s in signals if s.get("regime_eligible", True)]

        if not active:
            return {
                "selected_signal": None,
                "all_ranked": signals,
                "resolution_method": "no_signal",
                "num_signals_fired": 0,
                "status": SignalStatus.REGIME_SUPPRESSED.value,
            }

        # Attempt CIS override
        features = signals[0].get("features") or {}
        cis_result = None
        if features:
            try:
                plugin_outputs = {s["setup_plugin"]: s for s in signals if "setup_plugin" in s}
                cis_result = self._cis_scorer.score(features, plugin_outputs)
            except Exception:
                cis_result = None

        if cis_result is not None and getattr(cis_result, "direction", 0) != 0:
            return self._aggregate_via_cis(active, cis_result, signals)

        return self._aggregate_fallback(active, signals)

    def _aggregate_via_cis(
        self,
        active: list[dict],
        cis_result: Any,
        all_ranked: list[dict],
    ) -> dict[str, Any]:
        """Select winner matching CIS direction, boost by agreeing count."""
        cis_direction = cis_result.direction
        matching = [s for s in active if s.get("direction", 0) == cis_direction]

        if not matching:
            return self._aggregate_fallback(active, all_ranked)

        matching_sorted = sorted(matching, key=lambda s: s.get("adjusted_rank", 999))
        selected = matching_sorted[0]

        extra_agreeing = len(matching) - 1
        boosted = min(
            1.0,
            float(selected.get("confidence", 0.0)) + _CONFIDENCE_BOOST_PER_AGREE * extra_agreeing,
        )
        selected = dict(selected)
        selected["confidence"] = round(boosted, 4)
        selected["status"] = SignalStatus.PENDING.value

        return {
            "selected_signal": selected,
            "all_ranked": all_ranked,
            "resolution_method": "cis_override",
            "num_signals_fired": len(all_ranked),
            "num_agreeing": len(matching),
            "status": SignalStatus.PENDING.value,
        }

    def _aggregate_fallback(
        self,
        active: list[dict],
        all_ranked: list[dict],
    ) -> dict[str, Any]:
        """Select winner by majority direction, then adjusted_rank sort."""
        by_direction: dict[int, list[dict]] = defaultdict(list)
        for s in active:
            by_direction[s.get("direction", 0)].append(s)

        longs = len(by_direction.get(1, []))
        shorts = len(by_direction.get(-1, []))

        majority_group = by_direction[1] if longs >= shorts else by_direction[-1]
        sorted_group = sorted(majority_group, key=lambda s: s.get("adjusted_rank", 999))
        selected = dict(sorted_group[0])
        selected["status"] = SignalStatus.PENDING.value

        return {
            "selected_signal": selected,
            "all_ranked": all_ranked,
            "resolution_method": "priority_majority",
            "num_signals_fired": len(all_ranked),
            "num_agreeing": max(longs, shorts),
            "num_conflicting": min(longs, shorts),
            "status": SignalStatus.PENDING.value,
        }
