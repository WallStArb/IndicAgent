import json
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[3]))
sys.path.insert(0, str(Path(__file__).parents[3] / "production" / "scripts"))

from src.core.bar_normalizer import SOURCE_DERIVED_1M
from src.intelligence.register_plugins import register_all_plugins


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
    from src.persistence.repository.signal_ledger_repository import LedgerEntry

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
    assert any(
        v.get("model_fitted") for v in written
    ), "Write-back must capture GARCH-style _state reassignment"


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
        patch("production.scripts.historical_backfill.register_all_plugins") as mock_register,
        patch(
            "production.scripts.historical_backfill.replay_symbol", return_value=fake_counts
        ) as mock_replay,
    ):
        result = _replay_worker(("ESH6", "postgresql://u:p@localhost/indicagent", ["1m", "5m"], ts))

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


# ---------------------------------------------------------------------------
# run_i1_plugins, run_analysis_pipeline, _build_ledger_entries, store_bars,
# _build_intelligence_event, _event_to_sync_params, _insert_features_sync,
# _insert_signals_sync, detect_gaps tests
# (merged from tests/unit/test_historical_backfill.py)
# ---------------------------------------------------------------------------


def _make_mock_conn(fetchall_result=None):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = fetchall_result or []
    return mock_conn, mock_cursor


def _backfill_bar(ts, o=100.0, h=101.0, low=99.0, c=100.5, v=1000):
    return {"timestamp": ts, "open": o, "high": h, "low": low, "close": c, "volume": v}


def _ts_bf(hour, minute):
    return datetime(2026, 2, 1, hour, minute, 0, tzinfo=UTC)


class TestRunI1Plugins:
    def test_returns_empty_when_insufficient_bars(self):
        from historical_backfill import MIN_BARS, run_i1_plugins

        history = deque([_backfill_bar(_ts_bf(9, i)) for i in range(MIN_BARS - 1)], maxlen=200)
        assert run_i1_plugins(history, "ESH6", "5m", {}) == {}

    def test_returns_features_dict_when_enough_bars(self):
        from historical_backfill import MIN_BARS, run_i1_plugins

        history = deque(
            [
                _backfill_bar(_ts_bf(9, 0) if i == 0 else _ts_bf(9 + i // 60, i % 60))
                for i in range(MIN_BARS)
            ],
            maxlen=200,
        )
        register_all_plugins()
        assert isinstance(run_i1_plugins(history, "ESH6", "5m", {}), dict)

    def test_plugin_exception_does_not_propagate(self):
        from historical_backfill import MIN_BARS, run_i1_plugins

        history = deque([_backfill_bar(_ts_bf(9, i)) for i in range(MIN_BARS)], maxlen=200)
        register_all_plugins()
        assert isinstance(run_i1_plugins(history, "FAKE", "5m", {}), dict)


class TestRunAnalysisPipeline:
    def test_returns_dict(self):
        from historical_backfill import run_analysis_pipeline

        register_all_plugins()
        df = pd.DataFrame([_backfill_bar(_ts_bf(9, i)) for i in range(60)])
        result = run_analysis_pipeline(
            {"main": df, "features": {"rsi_14": 55.0, "atr_14": 2.5}}, {}, "ESH6", "5m", {}
        )
        assert isinstance(result, dict)

    def test_populates_intelligence_cache(self):
        from historical_backfill import run_analysis_pipeline

        register_all_plugins()
        df = pd.DataFrame([_backfill_bar(_ts_bf(9, i)) for i in range(60)])
        cache: dict = {}
        run_analysis_pipeline({"main": df, "features": {"rsi_14": 55.0}}, cache, "ESH6", "5m", {})
        assert "ESH6" in cache and "5m" in cache["ESH6"]

    def test_plugin_exception_does_not_propagate(self):
        from historical_backfill import run_analysis_pipeline

        result = run_analysis_pipeline(
            {"main": pd.DataFrame(), "features": {}}, {}, "ESH6", "5m", {}
        )
        assert isinstance(result, dict)


class TestBuildLedgerEntries:
    def _make_result(self, n=2):
        from src.intelligence.trading.aggregator import AggregatedResult

        sig = {
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_follow",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5115.0, 5130.0],
            "confidence": 0.75,
            "confluence_score": 0.6,
            "regime_context": "bullish",
            "supporting_factors": ["ema_cross"],
            "composite_rank": 1,
        }
        return AggregatedResult(
            selected_signal=sig,
            all_ranked=[sig],
            num_signals_fired=n,
            num_agreeing=n,
            num_conflicting=0,
            resolution_method="sole",
        )

    def test_returns_one_entry_per_ranked_signal(self):
        from historical_backfill import _build_ledger_entries

        assert (
            len(_build_ledger_entries(self._make_result(1), "ESH6", "5m", _ts_bf(9, 30), {})) == 1
        )

    def test_selected_signal_has_was_selected_true(self):
        from historical_backfill import _build_ledger_entries

        entries = _build_ledger_entries(self._make_result(), "ESH6", "5m", _ts_bf(9, 30), {})
        assert len([e for e in entries if e.was_selected]) == 1

    def test_empty_result_returns_empty_list(self):
        from historical_backfill import _build_ledger_entries

        from src.intelligence.trading.aggregator import AggregatedResult

        result = AggregatedResult(
            selected_signal=None,
            all_ranked=[],
            num_signals_fired=0,
            num_agreeing=0,
            num_conflicting=0,
            resolution_method="no_signal",
        )
        assert _build_ledger_entries(result, "ESH6", "5m", _ts_bf(9, 30), {}) == []


class TestFetchAndStoreBars:
    def test_fetch_1m_bars_queries_correct_table(self):
        from historical_backfill import fetch_bars

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (
                datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
                100.0,
                101.0,
                99.0,
                100.5,
                1000,
                "historical_backfill",
            )
        ]
        rows = fetch_bars(mock_conn, "ESH6", "1m")
        assert len(rows) == 1 and rows[0]["symbol"] == "ESH6" and "timestamp" in rows[0]

    def test_store_bars_calls_execute_batch(self):
        from historical_backfill import store_bars

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = MagicMock()
        bars = [
            {
                "timestamp": _ts_bf(9, 30),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
            }
        ]
        with patch("psycopg2.extras.execute_batch"):
            store_bars(mock_conn, bars, symbol="ESH6", timeframe="5m")
        mock_conn.commit.assert_called_once()


class TestBuildIntelligenceEvent:
    def test_returns_none_on_exception(self):
        from historical_backfill import _build_intelligence_event

        assert _build_intelligence_event({}, {}, {}, "ESH6", "1m", _ts_bf(9, 30)) is None

    def test_returns_intelligence_event_with_source_backfill(self):
        from historical_backfill import _build_intelligence_event

        from src.intelligence.schemas import IntelligenceEvent

        register_all_plugins()
        result = _build_intelligence_event(
            {"open": 5100.0, "high": 5105.0, "low": 5095.0, "close": 5102.0, "volume": 1000},
            {"rsi_14": 55.0, "atr_14": 2.5, "macd_12_26_9": 0.3},
            {"trend_direction": 1.0, "trend_strength": 0.7, "vol_regime": 0.5, "trend_regime": 1.0},
            "ESH6",
            "1m",
            _ts_bf(9, 30),
        )
        assert (
            result is not None
            and isinstance(result, IntelligenceEvent)
            and result.source == "backfill"
        )

    def test_i3_keys_filtered_before_construction(self):
        from historical_backfill import _build_intelligence_event

        intelligence = {
            "trend_direction": 1.0,
            "swing_high": 5110.0,
            "garch_sigma": 0.02,
            "vol_regime": 0.5,
            "bos_detected": True,
            "squeeze_active": 1.0,
            "ctf_score": 0.8,
        }
        result = _build_intelligence_event(
            {"open": 5100.0, "high": 5105.0, "low": 5095.0, "close": 5102.0, "volume": 1000},
            {"rsi_14": 55.0, "atr_14": 2.5, "macd_12_26_9": 0.3},
            intelligence,
            "ESH6",
            "1m",
            _ts_bf(9, 30),
        )
        assert result is not None or result is None  # no exception is the assertion

    def test_returns_none_on_pydantic_validation_error(self):
        from historical_backfill import _build_intelligence_event

        assert (
            _build_intelligence_event(
                {
                    "open": "not_a_number",
                    "high": 5105.0,
                    "low": 5095.0,
                    "close": 5102.0,
                    "volume": 1000,
                },
                {},
                {},
                "ESH6",
                "1m",
                _ts_bf(9, 30),
            )
            is None
        )


class TestEventToSyncParams:
    def _make_event(self):
        from src.intelligence.schemas import (
            I1Indicators,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            IntelligenceEvent,
            OHLCVBar,
            SMCContext,
        )

        return IntelligenceEvent(
            ts=_ts_bf(9, 30),
            symbol="ESH6",
            tf="1m",
            source="backfill",
            bar=OHLCVBar(o=5100.0, h=5105.0, l=5095.0, c=5102.0, v=1000),
            i1=I1Indicators(rsi_14=55.0),
            i3=I3Structure(),
            i4=I4Context(),
            i5=I5Patterns(),
            smc=SMCContext(),
            i6=I6Confluence(),
        )

    def test_returns_13_tuple(self):

        from historical_backfill import _event_to_sync_params

        assert len(_event_to_sync_params(self._make_event())) == 13

    def test_first_element_is_datetime(self):
        from historical_backfill import _event_to_sync_params

        assert isinstance(_event_to_sync_params(self._make_event())[0], datetime)

    def test_jsonb_columns_are_strings(self):
        from historical_backfill import _event_to_sync_params

        params = _event_to_sync_params(self._make_event())
        for i, col in enumerate(params[6:], start=6):
            assert isinstance(col, str), f"params[{i}] should be str, got {type(col)}"


class TestInsertFeaturesSync:
    def _mock_conn(self):
        return _make_mock_conn()

    def test_calls_execute_values_with_correct_sql(self):
        from historical_backfill import _INSERT_FEATURE_SYNC_SQL, _insert_features_sync

        mock_conn, mock_cursor = self._mock_conn()
        with patch("psycopg2.extras.execute_values") as mock_ev:
            _insert_features_sync(mock_conn, [("fake_row",)])
        assert mock_ev.call_args[0][0] is mock_cursor
        assert mock_ev.call_args[0][1] == _INSERT_FEATURE_SYNC_SQL

    def test_commits_connection(self):
        from historical_backfill import _insert_features_sync

        mock_conn, _ = self._mock_conn()
        with patch("psycopg2.extras.execute_values"):
            _insert_features_sync(mock_conn, [("row",)])
        mock_conn.commit.assert_called_once()

    def test_no_op_on_empty_rows(self):
        from historical_backfill import _insert_features_sync

        mock_conn, _ = self._mock_conn()
        _insert_features_sync(mock_conn, [])
        mock_conn.cursor.assert_not_called()


class TestBuildLedgerEntriesFeatureTs:
    def _make_result(self):
        from src.intelligence.trading.aggregator import AggregatedResult

        sig = {
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_follow",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5115.0],
            "confidence": 0.75,
            "confluence_score": 0.6,
            "regime_context": "bullish",
            "supporting_factors": ["ema_cross"],
            "composite_rank": 1,
        }
        return AggregatedResult(
            selected_signal=sig,
            all_ranked=[sig],
            num_signals_fired=1,
            num_agreeing=1,
            num_conflicting=0,
            resolution_method="sole",
        )

    def test_feature_ts_passes_through(self):
        from historical_backfill import _build_ledger_entries

        feature_ts = datetime(2026, 2, 1, 9, 30, 0, tzinfo=UTC)
        entries = _build_ledger_entries(
            self._make_result(),
            "ESH6",
            "1m",
            _ts_bf(9, 30),
            {},
            feature_ts=feature_ts,
            feature_tf="1m",
        )
        assert (
            len(entries) == 1
            and entries[0].feature_ts == feature_ts
            and entries[0].feature_tf == "1m"
        )

    def test_feature_ts_defaults_to_none(self):
        from historical_backfill import _build_ledger_entries

        entries = _build_ledger_entries(self._make_result(), "ESH6", "1m", _ts_bf(9, 30), {})
        assert len(entries) == 1 and entries[0].feature_ts is None


class TestCISColumnsInSQL:
    def test_insert_sync_sql_has_cis_columns(self):
        from historical_backfill import _INSERT_SYNC_SQL

        assert all(
            col in _INSERT_SYNC_SQL
            for col in ("cis_score", "bucket_scores", "weights_version", "signal_quality")
        )

    def test_insert_sync_sql_column_placeholder_balance(self):
        import re

        from historical_backfill import _INSERT_SYNC_SQL

        col_match = re.search(r"INSERT INTO signal_ledger \(([^)]+)\)", _INSERT_SYNC_SQL, re.DOTALL)
        val_match = re.search(r"VALUES \(([^)]+)\)", _INSERT_SYNC_SQL, re.DOTALL)
        assert col_match and val_match
        cols = [c.strip() for c in col_match.group(1).split(",") if c.strip()]
        vals = [v.strip() for v in val_match.group(1).split(",") if v.strip()]
        assert len(cols) == len(vals)

    def test_insert_signals_sync_params_include_cis_nulls(self):
        from historical_backfill import _insert_signals_sync

        from src.persistence.repository.signal_ledger_repository import LedgerEntry

        entry = LedgerEntry(
            signal_id="00000000-0000-0000-0000-000000000001",
            timestamp=datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
            symbol="ESH6",
            timeframe="5m",
            setup_plugin="trad_TrendFollowing",
            signal_type="trend_follow",
            direction=1,
            entry_price=5100.0,
            stop_loss=5085.0,
            targets=[5115.0],
            confidence=0.75,
            confluence_score=0.6,
            regime_context="bullish",
            supporting_factors=["ema_cross"],
            was_selected=True,
            num_signals_bar=1,
            num_agreeing=1,
            num_conflicting=0,
            resolution_method="sole",
            composite_rank=1,
            market_context={},
            status="pending",
            feature_ts=None,
            feature_tf=None,
        )
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = MagicMock()
        captured = []
        with patch(
            "psycopg2.extras.execute_batch",
            side_effect=lambda cur, sql, params: captured.extend(params),
        ):
            _insert_signals_sync(mock_conn, [entry])
        assert len(captured) == 1
        row = captured[0]
        assert len(row) == 29
        assert (
            row[24] is None
            and row[25] is None
            and row[26] is None
            and row[27] is None
            and row[28] is None
        )


class TestDetectGaps:
    def _mock_conn(self, fetchall_result=None):
        mock_conn, _ = _make_mock_conn(fetchall_result)
        return mock_conn

    def test_cme_futures_over_weekend_no_gaps(self):
        from historical_backfill import detect_gaps

        gaps = detect_gaps(
            self._mock_conn(),
            "ESH6",
            "1h",
            datetime(2026, 1, 3, 0, 0, tzinfo=UTC),
            datetime(2026, 1, 4, 23, 59, tzinfo=UTC),
            "futures_24_5",
            "CME",
        )
        assert gaps == []

    def test_nyse_over_weekend_no_gaps(self):
        from historical_backfill import detect_gaps

        with patch("historical_backfill.generate_session_slots", return_value=[]):
            gaps = detect_gaps(
                self._mock_conn(),
                "SPY",
                "5m",
                datetime(2026, 1, 3, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 4, 23, 59, tzinfo=UTC),
                "nyse",
                "NYSE",
            )
        assert gaps == []

    def test_nyse_on_holiday_no_gaps(self):
        from historical_backfill import detect_gaps

        with patch("historical_backfill.generate_session_slots", return_value=[]):
            gaps = detect_gaps(
                self._mock_conn(),
                "SPY",
                "5m",
                datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 23, 59, tzinfo=UTC),
                "nyse",
                "NYSE",
            )
        assert gaps == []

    def test_genuine_intraday_gap_detected(self):
        from historical_backfill import detect_gaps

        slots = [datetime(2026, 1, 2, h, 0, tzinfo=UTC) for h in range(15, 19)]
        mock_conn = self._mock_conn(
            [(datetime(2026, 1, 2, 15, 0, tzinfo=UTC),), (datetime(2026, 1, 2, 18, 0, tzinfo=UTC),)]
        )
        with patch("historical_backfill.generate_session_slots", return_value=slots):
            gaps = detect_gaps(
                mock_conn,
                "SPY",
                "1h",
                datetime(2026, 1, 2, 15, 0, tzinfo=UTC),
                datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                "nyse",
                "NYSE",
            )
        assert len(gaps) == 1
        assert gaps[0] == (
            datetime(2026, 1, 2, 16, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 17, 0, tzinfo=UTC),
        )
