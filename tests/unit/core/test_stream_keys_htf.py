"""Tests for HTF (higher-timeframe) bar stream key."""

from src.core.stream_keys import topic_market_bars_htf


def test_topic_market_bars_htf_with_env():
    """HTF bars topic with environment prefix."""
    assert topic_market_bars_htf("development") == "development.market.bars.htf"


def test_topic_market_bars_htf_no_env():
    """HTF bars topic without environment prefix."""
    assert topic_market_bars_htf("") == "market.bars.htf"
