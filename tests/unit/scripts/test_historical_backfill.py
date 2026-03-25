import json
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[3]))

from src.core.bar_normalizer import SOURCE_DERIVED_1M


def test_aggregate_bars_from_1m_5m_groups_correctly():
    """Five 1m bars in the same 5m window produce one aggregated bar."""
    from production.scripts.historical_backfill import aggregate_bars_from_1m

    base = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    bars = [
        {
            "timestamp": base.replace(minute=30 + i),
            "open": 100 + i,
            "high": 105 + i,
            "low": 99 + i,
            "close": 101 + i,
            "volume": 10,
        }
        for i in range(5)
    ]
    result = aggregate_bars_from_1m(bars, "5m")
    assert len(result) == 1
    agg = result[0]
    assert agg["timestamp"] == base.replace(minute=30)
    assert agg["open"] == bars[0]["open"]
    assert agg["close"] == bars[-1]["close"]
    assert agg["high"] == max(b["high"] for b in bars)
    assert agg["low"] == min(b["low"] for b in bars)
    assert agg["volume"] == 50
    assert agg["source"] == SOURCE_DERIVED_1M


def test_aggregate_bars_from_1m_splits_across_windows():
    """Bars spanning two 5m windows produce two aggregated bars."""
    from production.scripts.historical_backfill import aggregate_bars_from_1m

    base = datetime(2026, 3, 7, 9, 33, 0, tzinfo=UTC)
    bars = [
        {
            "timestamp": base.replace(minute=33),
            "open": 100,
            "high": 102,
            "low": 99,
            "close": 101,
            "volume": 5,
        },
        {
            "timestamp": base.replace(minute=34),
            "open": 101,
            "high": 103,
            "low": 100,
            "close": 102,
            "volume": 5,
        },
        {
            "timestamp": base.replace(minute=35),
            "open": 102,
            "high": 104,
            "low": 101,
            "close": 103,
            "volume": 5,
        },
    ]
    result = aggregate_bars_from_1m(bars, "5m")
    assert len(result) == 2
    assert result[0]["timestamp"] == base.replace(minute=30)
    assert result[1]["timestamp"] == base.replace(minute=35)


def test_aggregate_bars_from_1m_daily_floors_to_midnight():
    """1d aggregation floors timestamps to midnight."""
    from production.scripts.historical_backfill import aggregate_bars_from_1m

    bars = [
        {
            "timestamp": datetime(2026, 3, 7, 9, 30, tzinfo=UTC),
            "open": 100,
            "high": 105,
            "low": 99,
            "close": 104,
            "volume": 100,
        },
        {
            "timestamp": datetime(2026, 3, 7, 15, 0, tzinfo=UTC),
            "open": 104,
            "high": 106,
            "low": 103,
            "close": 105,
            "volume": 200,
        },
    ]
    result = aggregate_bars_from_1m(bars, "1d")
    assert len(result) == 1
    assert result[0]["timestamp"] == datetime(2026, 3, 7, 0, 0, tzinfo=UTC)
    assert result[0]["volume"] == 300


def test_aggregate_bars_from_1m_none_volume_treated_as_zero():
    """None volume values (FX has no volume) are treated as 0."""
    from production.scripts.historical_backfill import aggregate_bars_from_1m

    base = datetime(2026, 3, 7, 9, 30, tzinfo=UTC)
    bars = [
        {
            "timestamp": base,
            "open": 1.10,
            "high": 1.11,
            "low": 1.09,
            "close": 1.105,
            "volume": None,
        },
        {
            "timestamp": base.replace(minute=31),
            "open": 1.105,
            "high": 1.112,
            "low": 1.104,
            "close": 1.11,
            "volume": None,
        },
    ]
    result = aggregate_bars_from_1m(bars, "5m")
    assert result[0]["volume"] == 0


# ---------------------------------------------------------------------------
# CIS field propagation tests (Phase 25-01)
# ---------------------------------------------------------------------------


def _make_bar_history(n: int = 55) -> deque:
    """Return a deque of n minimal bar dicts for testing."""
    base = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    bars = deque(maxlen=200)
    for i in range(n):
        bars.append(
            {
                "timestamp": base.replace(minute=base.minute + i % 30),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 100,
            }
        )
    return bars


def test_build_ledger_entries_sets_market_entry_price_to_bar_close():
    """market_entry_price must equal the close of the last bar in bar_history (signal bar close)."""
    from production.scripts.historical_backfill import _build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    bar_history = _make_bar_history(n=55)
    expected_close = bar_history[-1]["close"]  # 100.5 + 54 = 154.5

    result = AggregatedResult(
        selected_signal={"direction": 1, "composite_rank": 1},
        all_ranked=[
            {
                "direction": 1,
                "composite_rank": 1,
                "setup_plugin": "trad_TrendFollowing",
                "signal_type": "long",
                "entry_price": 160.0,  # zone entry — different from market close
                "stop_loss": 150.0,
                "targets": [170.0],
                "confidence": 0.7,
                "confluence_score": 0.8,
                "regime_context": "trend",
                "supporting_factors": [],
            }
        ],
        resolution_method="highest_rank",
        num_signals_fired=1,
        num_agreeing=1,
        num_conflicting=0,
        cis_score=0.42,
        bucket_scores={},
        weights_version=0,
    )

    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    entries = _build_ledger_entries(result, "ESH6", "1m", ts, {}, bar_history=bar_history)

    assert len(entries) == 1
    assert entries[0].market_entry_price == expected_close


def test_run_i7_and_persist_populates_cis_fields():
    """CIS fields from AggregatedResult flow through _build_ledger_entries into LedgerEntry."""
    from production.scripts.historical_backfill import (
        run_i7_and_persist,
    )
    from src.intelligence.trading.aggregator import AggregatedResult

    cis_agg = AggregatedResult(
        selected_signal={"direction": 1, "composite_rank": 1},
        all_ranked=[
            {
                "direction": 1,
                "composite_rank": 1,
                "setup_plugin": "trad_TrendFollowing",
                "signal_type": "long",
                "entry_price": 100.0,
                "stop_loss": 99.0,
                "targets": [102.0],
                "confidence": 0.7,
                "confluence_score": 0.8,
                "regime_context": "trend",
                "supporting_factors": [],
            }
        ],
        resolution_method="highest_rank",
        num_signals_fired=1,
        num_agreeing=1,
        num_conflicting=0,
        cis_score=0.42,
        bucket_scores={"trend": 0.4, "momentum": 0.3},
        weights_version=0,
    )

    features = {"trend_regime": 1.0}
    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)

    captured_entries: list = []

    def fake_insert(conn, entries):
        captured_entries.extend(entries)

    mock_plugin = MagicMock()
    mock_plugin.compute_full.return_value = {
        "direction": 1,
        "setup_plugin": "trad_TrendFollowing",
    }
    mock_registry = MagicMock()
    mock_registry.get_pattern.return_value = mock_plugin

    with (
        patch("production.scripts.historical_backfill.aggregate", return_value=cis_agg),
        patch(
            "production.scripts.historical_backfill._insert_signals_sync", side_effect=fake_insert
        ),
        patch("production.scripts.historical_backfill.registry", mock_registry),
    ):
        mock_conn = MagicMock()
        run_i7_and_persist(
            _make_bar_history(),
            features,
            "ESH6",
            "1m",
            ts,
            mock_conn,
        )

    assert len(captured_entries) == 1
    entry = captured_entries[0]
    assert entry.cis_score == 0.42
    assert entry.bucket_scores == {"trend": 0.4, "momentum": 0.3}
    assert entry.weights_version == 0


def test_run_i7_and_persist_passes_features_kwarg_to_aggregate():
    """run_i7_and_persist must call aggregate(..., features=features_dict)."""
    from production.scripts.historical_backfill import run_i7_and_persist
    from src.intelligence.trading.aggregator import AggregatedResult

    fired_signal = {
        "direction": 1,
        "setup_plugin": "trad_TrendFollowing",
        "signal_type": "long",
        "entry_price": 100.0,
        "stop_loss": 99.0,
        "targets": [102.0],
        "confidence": 0.7,
        "confluence_score": 0.8,
        "regime_context": "trend",
        "supporting_factors": [],
        "composite_rank": 1,
    }
    _ = fired_signal  # used as fixture data for mock below
    empty_agg = AggregatedResult(
        selected_signal=None,
        all_ranked=[],
        resolution_method="no_signal",
        num_signals_fired=0,
    )

    features = {"trend_regime": 1.0, "some_feature": 42.0}
    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)

    mock_plugin = MagicMock()
    mock_plugin.compute_full.return_value = {"direction": 1}
    mock_registry = MagicMock()
    mock_registry.get_pattern.return_value = mock_plugin

    with (
        patch(
            "production.scripts.historical_backfill.aggregate", return_value=empty_agg
        ) as mock_agg,
        patch("production.scripts.historical_backfill.registry", mock_registry),
    ):
        run_i7_and_persist(_make_bar_history(), features, "ESH6", "1m", ts, None)

        assert mock_agg.called
        _, kwargs = mock_agg.call_args
        assert "features" in kwargs
        assert kwargs["features"] == features


def test_insert_signals_sync_writes_cis_fields():
    """_insert_signals_sync must NOT hardcode None for cis_score/bucket_scores/weights_version."""
    from production.scripts.historical_backfill import _insert_signals_sync
    from src.intelligence.trading.signal_ledger import LedgerEntry

    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    entry = LedgerEntry(
        signal_id="00000000-0000-0000-0000-000000000001",
        timestamp=ts,
        symbol="ESH6",
        timeframe="1m",
        setup_plugin="trad_TrendFollowing",
        signal_type="long",
        direction=1,
        entry_price=100.0,
        stop_loss=99.0,
        targets=[102.0],
        confidence=0.7,
        confluence_score=0.8,
        regime_context="trend",
        supporting_factors=[],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="highest_rank",
        composite_rank=1,
        market_context={},
        status="pending",
        feature_ts=ts,
        feature_tf="1m",
        cis_score=0.55,
        bucket_scores={"trend": 0.5},
        weights_version=1,
    )

    captured_params: list = []

    mock_cur = MagicMock()

    def fake_execute_batch(cur, sql, params_list):
        captured_params.extend(params_list)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch(
        "production.scripts.historical_backfill.psycopg2.extras.execute_batch",
        side_effect=fake_execute_batch,
    ):
        _insert_signals_sync(mock_conn, [entry])

    assert len(captured_params) == 1
    row = captured_params[0]
    # Positions 24, 25, 26 (0-indexed) are cis_score, bucket_scores, weights_version
    assert row[24] == 0.55, f"Expected cis_score=0.55, got {row[24]}"
    assert row[25] == json.dumps({"trend": 0.5}), f"Expected bucket_scores json, got {row[25]}"
    assert row[26] == 1, f"Expected weights_version=1, got {row[26]}"
    assert row[27] is None, "signal_quality should still be None"


def test_run_i7_and_persist_cis_null_when_no_raw_signals():
    """When no I7 plugins fire, run_i7_and_persist returns 0 (unchanged behaviour)."""
    from production.scripts.historical_backfill import run_i7_and_persist

    features = {"trend_regime": 0.0}
    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)

    # Plugin returns direction=0 → no signal → raw_signals stays empty
    mock_plugin = MagicMock()
    mock_plugin.compute_full.return_value = {"direction": 0}
    mock_registry = MagicMock()
    mock_registry.get_pattern.return_value = mock_plugin

    mock_conn = MagicMock()

    with patch("production.scripts.historical_backfill.registry", mock_registry):
        result = run_i7_and_persist(_make_bar_history(), features, "ESH6", "1m", ts, mock_conn)

    assert result == 0
    # DB insert never called when no signals
    mock_conn.cursor.assert_not_called()


# ---------------------------------------------------------------------------
# Plugin state isolation tests (Fix 1)
# ---------------------------------------------------------------------------


def test_run_i1_plugins_isolates_state_between_symbols():
    """Plugin state accumulated for sym1 must not bleed into sym2's plugin_states dict."""
    from production.scripts.historical_backfill import run_i1_plugins

    # A mock plugin that accumulates a counter in _state
    plugin = MagicMock()
    plugin._state = {}

    def fake_compute(frames):
        plugin._state["counter"] = plugin._state.get("counter", 0) + 1
        return {"rsi_14": 55.0}

    plugin.compute_full.side_effect = fake_compute

    mock_registry = MagicMock()
    mock_registry.get_indicator.return_value = plugin

    history = _make_bar_history(n=55)
    plugin_states_sym1: dict = {}
    plugin_states_sym2: dict = {}

    with patch("production.scripts.historical_backfill.registry", mock_registry):
        run_i1_plugins(history, "ESH6", "1m", plugin_states_sym1)
        # Simulate what would happen if sym1's state leaked into sym2 by checking that
        # sym2's plugin_states starts with empty dicts (no inherited counter)
        run_i1_plugins(history, "NQH6", "1m", plugin_states_sym2)

    # ESH6 state keys exist only in sym1's dict
    sym1_keys = {k for k in plugin_states_sym1 if k[1] == "ESH6"}
    sym2_keys = {k for k in plugin_states_sym2 if k[1] == "NQH6"}
    assert sym1_keys, "sym1 plugin_states must have ESH6 entries"
    assert sym2_keys, "sym2 plugin_states must have NQH6 entries"

    # No ESH6 state should appear in sym2's dict and vice versa
    assert not any(k[1] == "NQH6" for k in plugin_states_sym1), "ESH6 dict must not have NQH6 keys"
    assert not any(k[1] == "ESH6" for k in plugin_states_sym2), "NQH6 dict must not have ESH6 keys"


def test_run_i1_plugins_state_written_back_after_compute():
    """plugin_states must be updated with the plugin's _state after compute_full()."""
    from production.scripts.historical_backfill import run_i1_plugins

    plugin = MagicMock()
    plugin._state = {}

    def fake_compute(frames):
        # Simulate GARCH-style full reassignment of _state
        plugin._state = {"model_fitted": True, "sigma": 0.02}
        return {"rsi_14": 60.0}

    plugin.compute_full.side_effect = fake_compute

    mock_registry = MagicMock()
    mock_registry.get_indicator.return_value = plugin

    history = _make_bar_history(n=55)
    plugin_states: dict = {}

    with patch("production.scripts.historical_backfill.registry", mock_registry):
        run_i1_plugins(history, "ESH6", "1m", plugin_states)

    # Write-back must have captured the reassigned _state
    written = [v for k, v in plugin_states.items() if k[1] == "ESH6"]
    assert written, "plugin_states must have ESH6 entries after compute"
    assert any(v.get("model_fitted") for v in written), (
        "Write-back must capture GARCH-style _state reassignment"
    )


def test_run_analysis_pipeline_includes_i2_tier():
    """run_analysis_pipeline must call get_pattern() for I2 plugin names."""
    import pandas as pd

    from production.scripts.historical_backfill import I2_PLUGINS, run_analysis_pipeline

    called_names: list[str] = []

    plugin = MagicMock()
    plugin._state = {}
    plugin.compute_full.return_value = {}

    def fake_get_pattern(name):
        called_names.append(name)
        p = MagicMock()
        p._state = {}
        p.compute_full.return_value = {}
        return p

    mock_registry = MagicMock()
    mock_registry.get_pattern.side_effect = fake_get_pattern

    df = pd.DataFrame([_make_bar_history(n=1)[0]])
    frames = {"main": df, "features": {"rsi_14": 55.0}}
    intel_cache: dict = {}
    plugin_states: dict = {}

    with patch("production.scripts.historical_backfill.registry", mock_registry):
        run_analysis_pipeline(frames, intel_cache, "ESH6", "1m", plugin_states)

    for i2_name in I2_PLUGINS:
        assert i2_name in called_names, f"I2 plugin {i2_name!r} was not called in pipeline"


def test_i2_plugins_list_matches_tier_i2():
    """I2_PLUGINS in backfill must contain exactly the same names as TIER_I2 in register_plugins."""
    from production.scripts.historical_backfill import I2_PLUGINS
    from src.intelligence.register_plugins import TIER_I2

    assert set(I2_PLUGINS) == set(TIER_I2), (
        f"I2_PLUGINS mismatch.\n"
        f"  In backfill only : {set(I2_PLUGINS) - set(TIER_I2)}\n"
        f"  In TIER_I2 only  : {set(TIER_I2) - set(I2_PLUGINS)}"
    )


# ---------------------------------------------------------------------------
# Parallel worker tests
# ---------------------------------------------------------------------------


def test_replay_worker_calls_replay_symbol_and_returns_tuple():
    """_replay_worker opens its own connection, calls replay_symbol, and returns
    (symbol, total_signals, counts_by_tf)."""
    from production.scripts.historical_backfill import _replay_worker

    fake_counts = {"1m": 3, "5m": 1}
    mock_conn = MagicMock()
    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)

    with (
        patch("production.scripts.historical_backfill.psycopg2.connect", return_value=mock_conn),
        patch(
            "production.scripts.historical_backfill.register_all_plugins"
        ) as mock_register,
        patch(
            "production.scripts.historical_backfill.replay_symbol", return_value=fake_counts
        ) as mock_replay,
    ):
        result = _replay_worker(
            ("ESH6", "postgresql://u:p@localhost/indicagent", ["1m", "5m"], ts)
        )

    sym, total, counts = result
    assert sym == "ESH6"
    assert total == 4
    assert counts == fake_counts
    mock_register.assert_not_called()  # registry inherited via Linux fork
    mock_replay.assert_called_once_with("ESH6", mock_conn, ["1m", "5m"], since=ts)
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


def test_replay_worker_closes_connection_on_failure():
    """Connection must be closed even when replay_symbol raises."""
    from production.scripts.historical_backfill import _replay_worker

    mock_conn = MagicMock()

    with (
        patch("production.scripts.historical_backfill.psycopg2.connect", return_value=mock_conn),
        patch("production.scripts.historical_backfill.register_all_plugins"),
        patch(
            "production.scripts.historical_backfill.replay_symbol",
            side_effect=RuntimeError("boom"),
        ),
    ):
        try:
            _replay_worker(("ESH6", "postgresql://u:p@localhost/indicagent", ["1m"], None))
        except RuntimeError:
            pass

    mock_conn.close.assert_called_once()
    mock_conn.commit.assert_not_called()
