"""Tests for SWARM_* Settings, swarm Prometheus metrics, and SignalContextCache.build() dict I7."""

from __future__ import annotations


def test_swarm_settings_defaults():
    """SWARM_* settings have correct default values."""
    from src.config.settings import Settings

    s = Settings()
    assert s.SWARM_MIN_TF_MINUTES == 5
    assert s.SWARM_WEIGHT_MIN_SAMPLES == 30
    assert s.SWARM_WEIGHT_FLOOR == 0.05
    assert s.SWARM_MAX_CONCURRENT_CALLS >= 1  # value may vary by env


def test_swarm_settings_env_override(monkeypatch):
    """SWARM_MIN_TF_MINUTES can be overridden via environment variable."""
    monkeypatch.setenv("SWARM_MIN_TF_MINUTES", "15")
    from src.config.settings import Settings

    s = Settings()
    assert s.SWARM_MIN_TF_MINUTES == 15


def test_swarm_metrics_no_duplicate_on_reimport():
    """Swarm metrics are usable after re-importing the module (no duplicate-registration error).

    Full module reload cannot be tested here because ALL prometheus_client metrics
    in the module (plugin, circuit breaker, etc.) would also raise ValueError on reload.
    This test verifies the swarm metrics themselves are functional after repeated import.
    """
    # Re-import (not reload) — must be idempotent
    import importlib as _importlib

    import src.observability.metrics as m

    m2 = _importlib.import_module("src.observability.metrics")
    assert m2 is m  # Same module object (Python caches imports)

    # OTel API: .add() for counters, .add() for up_down_counters
    m.SWARM_INVOCATIONS_TOTAL.add(1, {"agent_id": "x", "timeframe": "5m", "status": "ok"})
    m.SWARM_AGENT_WEIGHT.add(0.7, {"agent_id": "x", "timeframe": "5m"})


def test_swarm_metrics_importable():
    """All five swarm metrics are importable from src.observability.metrics."""
    from src.observability.metrics import (
        SWARM_AGENT_WEIGHT,
        SWARM_AGGREGATED_MULTIPLIER,
        SWARM_INVOCATIONS_TOTAL,
        SWARM_MULTIPLIER_DISTRIBUTION,
        SWARM_SIGNAL_LEDGER_UPDATE_TOTAL,
    )

    assert SWARM_INVOCATIONS_TOTAL is not None
    assert SWARM_MULTIPLIER_DISTRIBUTION is not None
    assert SWARM_AGGREGATED_MULTIPLIER is not None
    assert SWARM_AGENT_WEIGHT is not None
    assert SWARM_SIGNAL_LEDGER_UPDATE_TOTAL is not None


def test_aicontext_build_accepts_dict_i7():
    """SignalContextCache.build() returns context with i7.winner_plugin when given dict I7 signal."""
    import time
    import types
    from datetime import UTC, datetime

    from src.core.ai.context import SignalContextCache, Tier

    cache = SignalContextCache()

    # Seed cache directly with a SimpleNamespace proxy (same pattern as seed_from_db_row)
    # This mimics what SignalContextCache.update() does with a full IntelligenceEvent
    proxy = types.SimpleNamespace(
        symbol="ES",
        tf="5m",
        ts=datetime.now(UTC),
        bar=None,
        i1=None,
        i2=None,
        i3=None,
        i4=None,
        i5=None,
        i6=None,
        smc=None,
    )
    cache._cache[("ES", "5m")] = (proxy, time.monotonic())

    # Build context with a signal dict (simulates dispatch passing signal.model_dump())
    # This is the key test: signal is a dict, not an object
    signal_dict = {
        "plugin": "TestPlugin",
        "direction": 1,
        "calibrated_confidence": 0.7,
        "entry_price": 5000.0,
    }

    ctx = cache.build(
        symbol="ES",
        tf="5m",
        tiers_needed=frozenset({Tier.I7}),
        signal=signal_dict,
        signal_id=None,
    )

    assert ctx is not None
    assert ctx.i7 is not None
    assert ctx.i7.winner_plugin == "TestPlugin"
