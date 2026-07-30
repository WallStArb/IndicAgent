"""Regression test: the live path must never assign feature_vectors.regime itself.

_process_bar_compute previously derived a heuristic regime label ("ranging"/
"trending_up", never "trending_down") from cache.hmm_regime_prob/hmm_entropy --
FeatureCache's fixed-params K=3 forward-filter HMM, a different model from
regime_writer.py's fitted, BIC-selected K=5 HMM. regime_writer.py's discovery
(`SELECT DISTINCT symbol FROM feature_vectors WHERE regime IS NULL`) is
symbol-level and restart-safe: once a row's regime is non-NULL, it is never
revisited. A live bar published with a heuristic regime value therefore kept
that value permanently -- a silent single-writer-invariant violation on a
measurement-critical column, found investigating todo 205 (2026-07-30).

regime_writer.py must be the sole writer of feature_vectors.regime, matching
the DAG Invariant pattern used elsewhere in this codebase (ProviderMerger is
the sole writer to market.bars, alpha_publisher is the sole alpha_events
writer). The live path always publishes regime=None -- exactly like
backfill_feature_factory.py already does.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.bar_normalizer import SOURCE_IBKR_NAMED
from src.core.schemas.bar_message import BarMessage, SessionType
from tests.unit.pipeline.pipeline_helpers import make_agent


def _bar(ts: datetime, *, high: float, low: float, close: float, volume: int = 1000) -> BarMessage:
    return BarMessage(
        ts=ts,
        symbol="SPY",
        tf="1m",
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=SOURCE_IBKR_NAMED,
        session_type=SessionType.RTH,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_bar_compute_never_assigns_regime():
    """Live-path _process_bar_compute must publish regime=None regardless of
    cache.hmm_regime_prob/hmm_entropy -- even when those values are high-confidence
    enough that the old heuristic would have assigned a non-NULL label."""
    agent = make_agent()
    agent._kafka_producer = AsyncMock()
    agent._bars_processed = MagicMock()

    ts1 = datetime(2026, 3, 23, 14, 30, 0, tzinfo=UTC)
    ts2 = datetime(2026, 3, 23, 14, 31, 0, tzinfo=UTC)

    bar1 = _bar(ts1, high=100.0, low=98.0, close=99.0)
    bar2 = _bar(ts2, high=101.0, low=99.0, close=100.9)

    agent._bar_history.append(bar1)
    agent._bar_history.append(bar2)

    cache = agent._get_cache("SPY", "1m")
    # Force the values that would have driven the old heuristic to its most
    # confident non-NULL branch (hmm_prob >= 0.6, entropy < 0.5 -> "ranging").
    cache.hmm_regime_prob = 0.95
    cache.hmm_entropy = 0.1

    await agent._process_bar_compute(bar2, t0=0.0, gap=False)
    # publish() runs on a fire-and-forget asyncio.create_task() -- let it complete.
    if agent._background_tasks:
        await asyncio.gather(*agent._background_tasks)

    assert agent._kafka_producer.publish.await_count == 1
    published_kwargs = agent._kafka_producer.publish.await_args.kwargs
    record_dict = published_kwargs["msg"]

    assert record_dict["regime"] is None, (
        "Live path must never assign a regime label -- regime_writer.py is the "
        f"sole writer. Got regime={record_dict['regime']!r} despite high-confidence "
        "cache.hmm_regime_prob/hmm_entropy that would have triggered the old "
        "removed heuristic."
    )
