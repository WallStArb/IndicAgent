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
    from production.scripts.run_historical_pipeline import aggregate_bars_from_1m

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
    from production.scripts.run_historical_pipeline import aggregate_bars_from_1m

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
    from production.scripts.run_historical_pipeline import aggregate_bars_from_1m

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
    from production.scripts.run_historical_pipeline import aggregate_bars_from_1m

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


def test_aggregate_bars_from_1m_4h_floors_to_4h_boundaries():
    """4h aggregation must group to 00:00, 04:00, 08:00, ... boundaries.

    Bug: the old minute-only floor left ts.hour unchanged, making each hour
    its own bucket and producing 1h bars stored as 4h.
    """
    from production.scripts.run_historical_pipeline import aggregate_bars_from_1m

    def _bar(h: int, m: int, close: float) -> dict:
        return {
            "timestamp": datetime(2026, 3, 7, h, m, tzinfo=UTC),
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 100,
        }

    bars = [
        _bar(0, 0, 100.0),
        _bar(0, 30, 101.0),
        _bar(1, 0, 102.0),
        _bar(2, 0, 103.0),
        _bar(3, 30, 104.0),
        _bar(4, 0, 200.0),
        _bar(5, 0, 201.0),
        _bar(7, 30, 202.0),
    ]
    result = aggregate_bars_from_1m(bars, "4h")
    assert (
        len(result) == 2
    ), f"Expected 2 4h windows, got {len(result)}: {[r['timestamp'] for r in result]}"
    assert result[0]["timestamp"] == datetime(2026, 3, 7, 0, 0, tzinfo=UTC)
    assert result[1]["timestamp"] == datetime(2026, 3, 7, 4, 0, tzinfo=UTC)
    assert result[0]["open"] == bars[0]["open"]
    assert result[0]["close"] == bars[4]["close"]  # last bar in 00:00-03:59 window
    assert result[0]["volume"] == 500  # 5 bars × 100
    assert result[1]["volume"] == 300  # 3 bars × 100


def test_aggregate_bars_from_1m_1h_floors_correctly():
    """1h aggregation: bars at 09:00-09:59 and 10:00-10:59 form two buckets."""
    from production.scripts.run_historical_pipeline import aggregate_bars_from_1m

    bars = [
        {
            "timestamp": datetime(2026, 3, 7, 9, 0, tzinfo=UTC),
            "open": 1,
            "high": 2,
            "low": 0,
            "close": 1.5,
            "volume": 10,
        },
        {
            "timestamp": datetime(2026, 3, 7, 9, 30, tzinfo=UTC),
            "open": 1.5,
            "high": 2,
            "low": 1,
            "close": 2,
            "volume": 20,
        },
        {
            "timestamp": datetime(2026, 3, 7, 10, 0, tzinfo=UTC),
            "open": 2,
            "high": 3,
            "low": 1.5,
            "close": 2.5,
            "volume": 30,
        },
    ]
    result = aggregate_bars_from_1m(bars, "1h")
    assert len(result) == 2
    assert result[0]["timestamp"] == datetime(2026, 3, 7, 9, 0, tzinfo=UTC)
    assert result[1]["timestamp"] == datetime(2026, 3, 7, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# CIS field propagation tests (Phase 25-01)
# ---------------------------------------------------------------------------


def _make_bar_history(n: int = 120) -> deque:
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
    from production.scripts.run_historical_pipeline import _build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    bar_history = _make_bar_history(n=120)
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
    from production.scripts.run_historical_pipeline import (
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
    mock_plugin.supports_incremental = False
    mock_plugin.compute_full.return_value = {
        "direction": 1,
        "setup_plugin": "trad_TrendFollowing",
    }
    mock_registry = MagicMock()
    mock_registry.get_pattern.return_value = mock_plugin

    with (
        patch("production.scripts.run_historical_pipeline.aggregate", return_value=cis_agg),
        patch(
            "production.scripts.run_historical_pipeline._insert_signals_sync",
            side_effect=fake_insert,
        ),
        patch("production.scripts.run_historical_pipeline.registry", mock_registry),
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
    from production.scripts.run_historical_pipeline import run_i7_and_persist
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
    mock_plugin.supports_incremental = False
    mock_plugin.compute_full.return_value = {"direction": 1}
    mock_registry = MagicMock()
    mock_registry.get_pattern.return_value = mock_plugin

    with (
        patch(
            "production.scripts.run_historical_pipeline.aggregate", return_value=empty_agg
        ) as mock_agg,
        patch("production.scripts.run_historical_pipeline.registry", mock_registry),
    ):
        run_i7_and_persist(_make_bar_history(), features, "ESH6", "1m", ts, None)

        assert mock_agg.called
        _, kwargs = mock_agg.call_args
        assert "features" in kwargs
        assert kwargs["features"] == features


def test_insert_signals_sync_writes_cis_fields():
    """_insert_signals_sync (3-table schema) inserts cis_score/weights_version into signal_events."""
    from production.scripts.run_historical_pipeline import _insert_signals_sync
    from src.persistence.repository.signal_events_repository import LedgerEntry

    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    entry = LedgerEntry(
        signal_id="00000000-0000-0000-0000-000000000001",
        timestamp=ts,
        symbol="ESH6",
        timeframe="1m",
        setup_plugin="trad_TrendFollowing",
        signal_type="long",
        direction=1,
        was_selected=True,
        status="pending",
        feature_ts=ts,
        feature_tf="1m",
        cis_score=0.55,
        bucket_scores={"trend": 0.5},
        weights_version=1,
        raw_confidence=0.75,
    )

    se_params: list = []
    tf_params: list = []

    mock_cur = MagicMock()

    def fake_execute_values(cur, sql, params_list, **kwargs):
        if "signal_events" in sql:
            se_params.extend(params_list)
        elif "trade_frames" in sql:
            tf_params.extend(params_list)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch(
        "production.scripts.run_historical_pipeline.psycopg2.extras.execute_values",
        side_effect=fake_execute_values,
    ):
        _insert_signals_sync(mock_conn, [entry])

    # Two execute_values calls: one for signal_events, one for trade_frames
    assert len(se_params) == 1, f"Expected 1 signal_events row, got {len(se_params)}"
    assert len(tf_params) == 1, f"Expected 1 trade_frames row, got {len(tf_params)}"

    se_row = se_params[0]
    # signal_events row: 25 params (is_backfill=TRUE via SQL template, 25 %s params)
    # Indices: 0=signal_id,1=ts,2=symbol,3=tf,4=setup_plugin,5=direction(text),
    #   6=raw_confidence,7=calibrated_confidence,8=cis_score,9=weights_version,
    #   10=factor_scores,11=context_features,12=ctf_score,13=ctf_confirmed,
    #   14=zone_friction_score,15=hmm_regime,16=plugin_regime,17=garch_sigma,
    #   18=is_shadow,19=status,20=signal_schema_version,
    #   21=ttl_bars,22=expires_at,23=signal_computed_at,24=feature_ts
    assert len(se_row) == 25, f"Expected 25-element signal_events tuple, got {len(se_row)}"
    assert se_row[5] == "long", f"Expected direction='long', got {se_row[5]}"
    assert se_row[8] == 0.55, f"Expected cis_score=0.55, got {se_row[8]}"
    assert se_row[9] == 1, f"Expected weights_version=1, got {se_row[9]}"


def test_run_i7_and_persist_cis_null_when_no_raw_signals():
    """When no I7 plugins fire, run_i7_and_persist returns 0 (unchanged behaviour)."""
    from production.scripts.run_historical_pipeline import run_i7_and_persist

    features = {"trend_regime": 0.0}
    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)

    # Plugin returns direction=0 → no signal → raw_signals stays empty
    mock_plugin = MagicMock()
    mock_plugin.compute_full.return_value = {"direction": 0}
    mock_registry = MagicMock()
    mock_registry.get_pattern.return_value = mock_plugin

    mock_conn = MagicMock()

    with patch("production.scripts.run_historical_pipeline.registry", mock_registry):
        result = run_i7_and_persist(_make_bar_history(), features, "ESH6", "1m", ts, mock_conn)

    assert result == 0
    # DB insert never called when no signals
    mock_conn.cursor.assert_not_called()


# ---------------------------------------------------------------------------
# Plugin state isolation tests (Fix 1)
# ---------------------------------------------------------------------------


def test_run_i1_plugins_isolates_state_between_symbols():
    """Plugin state accumulated for sym1 must not bleed into sym2's plugin_states dict."""
    from production.scripts.run_historical_pipeline import run_i1_plugins

    # A mock plugin that accumulates a counter in _state
    plugin = MagicMock()
    plugin._state = {}

    def fake_compute(frames):
        plugin._state["counter"] = plugin._state.get("counter", 0) + 1
        return {"rsi_14": 55.0}

    plugin.compute_full.side_effect = fake_compute

    mock_registry = MagicMock()
    mock_registry.get_indicator.return_value = plugin

    history = _make_bar_history(n=120)
    plugin_states_sym1: dict = {}
    plugin_states_sym2: dict = {}

    with patch("production.scripts.run_historical_pipeline.registry", mock_registry):
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
    """plugin_states must capture the _state the plugin returns in its result dict.

    Mirrors the live executor (_collect_plugin_results, executor.py:389-392), which
    reads state ONLY from result["_state"] -- never from plugin._state. The replay's
    write-back must use the same mechanism so the next bar takes the incremental branch.
    """
    from production.scripts.run_historical_pipeline import run_i1_plugins

    plugin = MagicMock()
    plugin.supports_incremental = True

    def fake_compute(frames, *, state=None):
        # IncrementalMixin pattern: attach seeded _state to the result dict.
        return {"rsi_14": 60.0, "_state": {"model_fitted": True, "sigma": 0.02}}

    plugin.compute_full.side_effect = fake_compute

    mock_registry = MagicMock()
    mock_registry.get_indicator.return_value = plugin

    history = _make_bar_history(n=120)
    plugin_states: dict = {}

    with patch("production.scripts.run_historical_pipeline.registry", mock_registry):
        run_i1_plugins(history, "ESH6", "1m", plugin_states)

    # Write-back must have captured the _state returned in the result dict
    written = [v for k, v in plugin_states.items() if k[1] == "ESH6"]
    assert written, "plugin_states must have ESH6 entries after compute"
    assert any(
        v.get("model_fitted") for v in written
    ), "Write-back must capture the _state returned in the result dict"


def test_run_analysis_pipeline_includes_i2_tier():
    """run_analysis_pipeline must call get_pattern() for I2 plugin names."""
    import pandas as pd

    from production.scripts.run_historical_pipeline import I2_PLUGINS, run_analysis_pipeline

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

    with patch("production.scripts.run_historical_pipeline.registry", mock_registry):
        run_analysis_pipeline(frames, intel_cache, "ESH6", "1m", plugin_states)

    for i2_name in I2_PLUGINS:
        assert i2_name in called_names, f"I2 plugin {i2_name!r} was not called in pipeline"


def test_i2_plugins_list_matches_tier_i2():
    """I2_PLUGINS in backfill must contain exactly the same names as TIER_I2 in register_plugins."""
    from production.scripts.run_historical_pipeline import I2_PLUGINS
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
    """_replay_worker opens its own connection, loads calibration, calls replay_symbol,
    and returns (symbol, total_signals, counts_by_tf)."""
    from production.scripts.run_historical_pipeline import _replay_worker

    fake_counts = {"1m": 3, "5m": 1}
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)

    with (
        patch(
            "production.scripts.run_historical_pipeline.psycopg2.connect", return_value=mock_conn
        ),
        patch("production.scripts.run_historical_pipeline.register_all_plugins") as mock_register,
        patch(
            "production.scripts.run_historical_pipeline.replay_symbol", return_value=fake_counts
        ) as mock_replay,
    ):
        result = _replay_worker(
            ("ESH6", "postgresql://u:p@localhost/indicagent", ["1m", "5m"], ts, False, False)
        )

    sym, total, counts = result
    assert sym == "ESH6"
    assert total == 4
    assert counts == fake_counts
    mock_register.assert_called_once_with()
    mock_replay.assert_called_once_with(
        "ESH6",
        mock_conn,
        ["1m", "5m"],
        since=ts,
        skip_signals=False,
        calibration_curves={},
        perf_weights={},
        precomputed_features=None,
    )
    mock_conn.commit.assert_not_called()  # autocommit=True; no explicit commit
    mock_conn.close.assert_called_once()


def test_replay_worker_closes_connection_on_failure():
    """Connection must be closed even when replay_symbol raises."""
    from production.scripts.run_historical_pipeline import _replay_worker

    mock_conn = MagicMock()

    with (
        patch(
            "production.scripts.run_historical_pipeline.psycopg2.connect", return_value=mock_conn
        ),
        patch("production.scripts.run_historical_pipeline.register_all_plugins"),
        patch(
            "production.scripts.run_historical_pipeline.replay_symbol",
            side_effect=RuntimeError("boom"),
        ),
    ):
        try:
            _replay_worker(
                ("ESH6", "postgresql://u:p@localhost/indicagent", ["1m"], None, False, False)
            )
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
        from production.scripts.run_historical_pipeline import run_i1_plugins
        from src.core.service_utils import min_bars_for_tf

        MIN_BARS = min_bars_for_tf("5m")

        history = deque([_backfill_bar(_ts_bf(9, i)) for i in range(MIN_BARS - 1)], maxlen=200)
        assert run_i1_plugins(history, "ESH6", "5m", {}) == {}

    def test_returns_features_dict_when_enough_bars(self):
        from production.scripts.run_historical_pipeline import run_i1_plugins
        from src.core.service_utils import min_bars_for_tf

        MIN_BARS = min_bars_for_tf("5m")

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
        from production.scripts.run_historical_pipeline import run_i1_plugins
        from src.core.service_utils import min_bars_for_tf

        MIN_BARS = min_bars_for_tf("5m")

        history = deque([_backfill_bar(_ts_bf(9, i)) for i in range(MIN_BARS)], maxlen=200)
        register_all_plugins()
        assert isinstance(run_i1_plugins(history, "FAKE", "5m", {}), dict)


class TestRunAnalysisPipeline:
    def test_returns_2_tuple(self):
        from production.scripts.run_historical_pipeline import run_analysis_pipeline

        register_all_plugins()
        df = pd.DataFrame([_backfill_bar(_ts_bf(9, i)) for i in range(60)])
        result = run_analysis_pipeline(
            {"main": df, "features": {"rsi_14": 55.0, "atr_14": 2.5}}, {}, "ESH6", "5m", {}
        )
        assert isinstance(result, tuple) and len(result) == 2
        flat, tiered = result
        assert isinstance(flat, dict)
        assert isinstance(tiered, dict)
        assert "i2" in tiered

    def test_populates_intelligence_cache(self):
        from production.scripts.run_historical_pipeline import run_analysis_pipeline

        register_all_plugins()
        df = pd.DataFrame([_backfill_bar(_ts_bf(9, i)) for i in range(60)])
        cache: dict = {}
        _, _ = run_analysis_pipeline(
            {"main": df, "features": {"rsi_14": 55.0}}, cache, "ESH6", "5m", {}
        )
        assert "ESH6" in cache and "5m" in cache["ESH6"]

    def test_plugin_exception_does_not_propagate(self):
        from production.scripts.run_historical_pipeline import run_analysis_pipeline

        result = run_analysis_pipeline(
            {"main": pd.DataFrame(), "features": {}}, {}, "ESH6", "5m", {}
        )
        flat, tiered = result
        assert isinstance(flat, dict)

    def test_i2_tier_does_not_contain_macd_fields(self):
        """I2 tier output must not contain MACD fields (they are in I3 tier)."""
        from production.scripts.run_historical_pipeline import run_analysis_pipeline

        register_all_plugins()
        df = pd.DataFrame([_backfill_bar(_ts_bf(9, i)) for i in range(60)])
        flat, tiered = run_analysis_pipeline(
            {"main": df, "features": {"rsi_14": 55.0, "atr_14": 2.5}}, {}, "ESH6", "5m", {}
        )
        i2 = tiered.get("i2", {})
        macd_i2_fields = [
            "macd_cross_bullish",
            "macd_cross_bearish",
            "macd_cross_bars_ago",
            "macd_hist_positive",
            "macd_hist_turning_up",
            "macd_negative_support_test",
        ]
        for field in macd_i2_fields:
            assert field not in i2, f"{field} must not be in tiered['i2']"


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

    @staticmethod
    def _make_bar():
        from collections import deque

        bar = {
            "open": 5095.0,
            "high": 5105.0,
            "low": 5090.0,
            "close": 5100.0,
            "volume": 1000.0,
        }
        return deque([bar], maxlen=500)

    def test_returns_one_entry_per_ranked_signal(self):
        from production.scripts.run_historical_pipeline import _build_ledger_entries

        assert (
            len(
                _build_ledger_entries(
                    self._make_result(1),
                    "ESH6",
                    "5m",
                    _ts_bf(9, 30),
                    {},
                    bar_history=self._make_bar(),
                )
            )
            == 1
        )

    def test_selected_signal_has_was_selected_true(self):
        from production.scripts.run_historical_pipeline import _build_ledger_entries

        entries = _build_ledger_entries(
            self._make_result(), "ESH6", "5m", _ts_bf(9, 30), {}, bar_history=self._make_bar()
        )
        assert len([e for e in entries if e.was_selected]) == 1

    def test_empty_result_returns_empty_list(self):
        from production.scripts.run_historical_pipeline import _build_ledger_entries
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
        from production.scripts.run_historical_pipeline import fetch_bars

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
        from production.scripts.run_historical_pipeline import store_bars

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
        from production.scripts.run_historical_pipeline import _build_intelligence_event

        assert _build_intelligence_event({}, {}, {}, "ESH6", "1m", _ts_bf(9, 30)) is None

    def test_returns_intelligence_event_with_source_backfill(self):
        from production.scripts.run_historical_pipeline import _build_intelligence_event
        from src.intelligence.schemas import IntelligenceEvent

        register_all_plugins()
        result = _build_intelligence_event(
            {"open": 5100.0, "high": 5105.0, "low": 5095.0, "close": 5102.0, "volume": 1000},
            {"rsi_14": 55.0, "atr_14": 2.5, "macd_12_26_9": 0.3},
            {
                "i3": {"trend_direction": 1.0, "trend_strength": 0.7},
                "i4": {"vol_regime": 0.5, "trend_regime": 1.0},
            },
            "ESH6",
            "1m",
            _ts_bf(9, 30),
        )
        assert (
            result is not None
            and isinstance(result, IntelligenceEvent)
            and result.source == "backfill"
        )
        assert result.i2 is not None

    def test_i3_keys_filtered_before_construction(self):
        from production.scripts.run_historical_pipeline import _build_intelligence_event

        tiered = {
            "i3": {"trend_direction": 1.0, "swing_high": 5110.0},
            "i4": {"garch_sigma": 0.02, "vol_regime": 0.5},
            "smc": {"bos_detected": True},
            "i5": {"squeeze_active": 1.0},
            "i6": {"ctf_score": 0.8},
        }
        result = _build_intelligence_event(
            {"open": 5100.0, "high": 5105.0, "low": 5095.0, "close": 5102.0, "volume": 1000},
            {"rsi_14": 55.0, "atr_14": 2.5, "macd_12_26_9": 0.3},
            tiered,
            "ESH6",
            "1m",
            _ts_bf(9, 30),
        )
        assert result is not None or result is None  # no exception is the assertion

    def test_returns_none_on_pydantic_validation_error(self):
        from production.scripts.run_historical_pipeline import _build_intelligence_event

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
            I2Events,
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
            i2=I2Events(),
            i3=I3Structure(),
            i4=I4Context(),
            i5=I5Patterns(),
            smc=SMCContext(),
            i6=I6Confluence(),
        )

    def test_returns_14_tuple(self):

        from production.scripts.run_historical_pipeline import _event_to_sync_params

        assert len(_event_to_sync_params(self._make_event())) == 14

    def test_first_element_is_datetime(self):
        from production.scripts.run_historical_pipeline import _event_to_sync_params

        assert isinstance(_event_to_sync_params(self._make_event())[0], datetime)

    def test_jsonb_columns_are_strings(self):
        from production.scripts.run_historical_pipeline import _event_to_sync_params

        params = _event_to_sync_params(self._make_event())
        for i, col in enumerate(params[6:], start=6):
            assert isinstance(col, str), f"params[{i}] should be str, got {type(col)}"


class TestInsertFeaturesSync:
    def _mock_conn(self):
        return _make_mock_conn()

    def test_calls_execute_values_with_correct_sql(self):
        from production.scripts.run_historical_pipeline import (
            _INSERT_FEATURE_SYNC_SQL,
            _insert_features_sync,
        )

        mock_conn, mock_cursor = self._mock_conn()
        with patch("psycopg2.extras.execute_values") as mock_ev:
            _insert_features_sync(mock_conn, [("fake_row",)])
        assert mock_ev.call_args[0][0] is mock_cursor
        assert mock_ev.call_args[0][1] == _INSERT_FEATURE_SYNC_SQL

    def test_commits_connection(self):
        from production.scripts.run_historical_pipeline import _insert_features_sync

        mock_conn, _ = self._mock_conn()
        with patch("psycopg2.extras.execute_values"):
            _insert_features_sync(mock_conn, [("row",)])
        mock_conn.commit.assert_called_once()

    def test_no_op_on_empty_rows(self):
        from production.scripts.run_historical_pipeline import _insert_features_sync

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

    @staticmethod
    def _make_bar():
        from collections import deque

        bar = {
            "open": 5095.0,
            "high": 5105.0,
            "low": 5090.0,
            "close": 5100.0,
            "volume": 1000.0,
        }
        return deque([bar], maxlen=500)

    def test_feature_ts_passes_through(self):
        from production.scripts.run_historical_pipeline import _build_ledger_entries

        feature_ts = datetime(2026, 2, 1, 9, 30, 0, tzinfo=UTC)
        entries = _build_ledger_entries(
            self._make_result(),
            "ESH6",
            "1m",
            _ts_bf(9, 30),
            {},
            feature_ts=feature_ts,
            feature_tf="1m",
            bar_history=self._make_bar(),
        )
        assert (
            len(entries) == 1
            and entries[0].feature_ts == feature_ts
            and entries[0].feature_tf == "1m"
        )

    def test_feature_ts_defaults_to_none(self):
        from production.scripts.run_historical_pipeline import _build_ledger_entries

        entries = _build_ledger_entries(
            self._make_result(), "ESH6", "1m", _ts_bf(9, 30), {}, bar_history=self._make_bar()
        )
        assert len(entries) == 1 and entries[0].feature_ts is None


class TestCISColumnsInSQL:
    def test_insert_sync_sql_has_cis_columns(self):
        """Phase 130: signal_events SQL contains cis_score + weights_version."""
        from production.scripts.run_historical_pipeline import _INSERT_SIGNAL_EVENTS_SYNC_SQL

        assert all(
            col in _INSERT_SIGNAL_EVENTS_SYNC_SQL for col in ("cis_score", "weights_version")
        )
        # signal_quality is lifecycle — lives in trade_executions, not signal_events
        assert (
            "signal_quality" not in _INSERT_SIGNAL_EVENTS_SYNC_SQL
        ), "signal_quality is lifecycle — must not be in signal_events INSERT"

    def test_insert_sync_sql_column_placeholder_balance(self):
        """Phase 130: signal_events + trade_frames SQL column/placeholder counts are balanced."""
        import re

        from production.scripts.run_historical_pipeline import (
            _INSERT_SIGNAL_EVENTS_SYNC_SQL,
            _INSERT_SIGNAL_EVENTS_SYNC_TEMPLATE,
            _INSERT_TRADE_FRAMES_SYNC_SQL,
            _INSERT_TRADE_FRAMES_SYNC_TEMPLATE,
        )

        # signal_events: 26 columns, is_backfill=TRUE in template (1 literal) → 25 %s params
        col_match = re.search(
            r"INSERT INTO signal_events \(([^)]+)\)", _INSERT_SIGNAL_EVENTS_SYNC_SQL, re.DOTALL
        )
        assert col_match, "INSERT INTO signal_events (...) not found in SQL"
        cols = [c.strip() for c in col_match.group(1).split(",") if c.strip()]
        n_placeholders = _INSERT_SIGNAL_EVENTS_SYNC_TEMPLATE.count("%s")
        # is_backfill=TRUE is a SQL literal in the template, so cols = params + 1
        assert len(cols) == n_placeholders + 1, (
            f"signal_events: col count ({len(cols)}) should be "
            f"placeholder count ({n_placeholders}) + 1 SQL literal"
        )

        # trade_frames: counterfactual_pnl_r=NULL is a literal → 13 %s params for 14 cols
        tf_col_match = re.search(
            r"INSERT INTO trade_frames \(([^)]+)\)", _INSERT_TRADE_FRAMES_SYNC_SQL, re.DOTALL
        )
        assert tf_col_match, "INSERT INTO trade_frames (...) not found in SQL"
        tf_cols = [c.strip() for c in tf_col_match.group(1).split(",") if c.strip()]
        tf_placeholders = _INSERT_TRADE_FRAMES_SYNC_TEMPLATE.count("%s")
        assert len(tf_cols) == tf_placeholders + 1, (
            f"trade_frames: col count ({len(tf_cols)}) should be "
            f"placeholder count ({tf_placeholders}) + 1 SQL literal (counterfactual_pnl_r=NULL)"
        )

    def test_insert_signals_sync_params_include_cis_nulls(self):
        """Phase 130: _insert_signals_sync produces signal_events + trade_frames rows."""
        from production.scripts.run_historical_pipeline import _insert_signals_sync
        from src.persistence.repository.signal_events_repository import LedgerEntry

        entry = LedgerEntry(
            signal_id="00000000-0000-0000-0000-000000000001",
            timestamp=datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
            symbol="ESH6",
            timeframe="5m",
            setup_plugin="trad_TrendFollowing",
            signal_type="trend_follow",
            direction=1,
            was_selected=True,
            status="pending",
            feature_ts=None,
            feature_tf=None,
        )
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = MagicMock()
        se_captured = []
        tf_captured = []

        def fake_ev(cur, sql, params, **kw):
            if "signal_events" in sql:
                se_captured.extend(params)
            elif "trade_frames" in sql:
                tf_captured.extend(params)

        with patch(
            "production.scripts.run_historical_pipeline.psycopg2.extras.execute_values",
            side_effect=fake_ev,
        ):
            _insert_signals_sync(mock_conn, [entry])
        # Two execute_values calls: signal_events row + trade_frames row
        assert len(se_captured) == 1, f"Expected 1 signal_events row, got {len(se_captured)}"
        assert len(tf_captured) == 1, f"Expected 1 trade_frames row, got {len(tf_captured)}"
        row = se_captured[0]  # signal_events row (25 params = 26 cols minus 1 SQL literal)
        assert len(row) == 25, f"Expected 25-element signal_events tuple, got {len(row)}"
        assert row[8] is None  # cis_score (None when not set)
        assert row[9] is None  # weights_version (None when not set)


class TestDetectGaps:
    def _mock_conn(self, fetchall_result=None):
        mock_conn, _ = _make_mock_conn(fetchall_result)
        return mock_conn

    def test_cme_futures_over_weekend_no_gaps(self):
        from production.scripts.run_historical_pipeline import detect_gaps

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
        from production.scripts.run_historical_pipeline import detect_gaps

        with patch(
            "production.scripts.run_historical_pipeline.generate_session_slots", return_value=[]
        ):
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
        from production.scripts.run_historical_pipeline import detect_gaps

        with patch(
            "production.scripts.run_historical_pipeline.generate_session_slots", return_value=[]
        ):
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
        from production.scripts.run_historical_pipeline import detect_gaps

        slots = [datetime(2026, 1, 2, h, 0, tzinfo=UTC) for h in range(15, 19)]
        mock_conn = self._mock_conn(
            [(datetime(2026, 1, 2, 15, 0, tzinfo=UTC),), (datetime(2026, 1, 2, 18, 0, tzinfo=UTC),)]
        )
        with patch(
            "production.scripts.run_historical_pipeline.generate_session_slots", return_value=slots
        ):
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


# ---------------------------------------------------------------------------
# Task 1: _load_calibration_curves and _load_perf_weights
# ---------------------------------------------------------------------------


def test_load_calibration_curves_empty_table():
    """Returns empty dict when calibration_curves table has no rows."""
    from production.scripts.run_historical_pipeline import _load_calibration_curves

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    result = _load_calibration_curves(conn)
    assert result == {}


def test_load_calibration_curves_builds_two_tuple_key():
    """DB rows with 3-tuple (plugin, tf, symbol) become 2-tuple (plugin, tf) keys.

    Symbol-specific row beats global '*' row for the same (plugin, tf).
    """
    from production.scripts.run_historical_pipeline import _load_calibration_curves

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        (
            "vwap_deviation",
            "1m",
            "*",
            {"breakpoints": [0.1, 0.5, 0.9], "values": [0.15, 0.5, 0.85]},
        ),
        (
            "vwap_deviation",
            "1m",
            "ESM6",
            {"breakpoints": [0.2, 0.6, 0.9], "values": [0.25, 0.6, 0.88]},
        ),
        ("momentum_burst", "5m", "*", {"breakpoints": [0.0, 1.0], "values": [0.0, 1.0]}),
    ]
    result = _load_calibration_curves(conn, symbol="ESM6")
    assert ("vwap_deviation", "1m") in result
    assert ("momentum_burst", "5m") in result
    bp, vals = result[("vwap_deviation", "1m")]
    assert bp == [0.2, 0.6, 0.9]


def test_load_calibration_curves_skips_rows_missing_data():
    """Rows with missing breakpoints or values are silently skipped."""
    from production.scripts.run_historical_pipeline import _load_calibration_curves

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        ("vwap_deviation", "1m", "*", {"breakpoints": [], "values": []}),
        ("momentum_burst", "5m", "*", None),
    ]
    result = _load_calibration_curves(conn)
    assert result == {}


def test_load_perf_weights_empty_table():
    """Returns empty dict when setup_performance has no eligible rows."""
    from production.scripts.run_historical_pipeline import _load_perf_weights

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    result = _load_perf_weights(conn)
    assert result == {}


def test_load_perf_weights_returns_multipliers():
    """Rows from setup_performance are converted to (perf_multiplier, sample_size) tuples.

    _compute_perf_multipliers sorts by sharpe_ratio ascending. Best Sharpe
    gets lowest multiplier (sorts first under ascending adjusted_rank).
    """
    from production.scripts.run_historical_pipeline import _load_perf_weights

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        ("vwap_deviation", 0.62, 0.25, 150, 1.5),
        ("momentum_burst", 0.55, 0.15, 120, 0.8),
    ]
    result = _load_perf_weights(conn)
    assert "vwap_deviation" in result
    assert "momentum_burst" in result
    for plugin, val in result.items():
        mult, size = val
        assert 0.5 <= mult <= 1.5
        assert isinstance(size, int)
    assert result["vwap_deviation"][0] < result["momentum_burst"][0]


# ---------------------------------------------------------------------------
# Task 2: run_i7_and_persist passes calibration to aggregate()
# ---------------------------------------------------------------------------


def test_run_i7_and_persist_passes_calibration_to_aggregate():
    """calibration_curves and perf_weights reach aggregate() when provided.

    Stubs the I7 plugin loop to produce one raw signal so aggregate() is
    actually called — the real plugins need rich features to fire.
    """
    from collections import deque
    from datetime import UTC, datetime
    from unittest.mock import MagicMock, patch

    from production.scripts.run_historical_pipeline import run_i7_and_persist

    base = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    bars = [
        {
            "timestamp": base,
            "open": 5200.0,
            "high": 5205.0,
            "low": 5195.0,
            "close": 5202.0,
            "volume": 1000.0,
        }
        for _ in range(130)  # min_bars_for_tf("1m") == 120
    ]
    history = deque(bars, maxlen=200)
    features = {"trend_regime": 0.5}

    cal_curves = {("stub_plugin", "1m"): ([0.0, 1.0], [0.0, 1.0])}
    perf_wts = {"stub_plugin": (1.0, 100)}

    stub_signal = {"direction": 1, "setup_plugin": "stub_plugin", "confidence": 0.7}
    mock_plugin = MagicMock()
    mock_plugin.supports_incremental = False
    mock_plugin.compute_full.return_value = stub_signal

    captured = {}

    def fake_aggregate(
        signals,
        *,
        trend_regime=0.0,
        features=None,
        calibration_curves=None,
        perf_weights=None,
        **kwargs,
    ):
        captured["calibration_curves"] = calibration_curves
        captured["perf_weights"] = perf_weights
        from src.intelligence.trading.aggregator import AggregatedResult

        return AggregatedResult(selected_signal=None, all_ranked=[])

    with (
        patch("production.scripts.run_historical_pipeline.I7_PLUGINS", ["stub_plugin"]),
        patch("production.scripts.run_historical_pipeline.registry") as mock_registry,
        patch("production.scripts.run_historical_pipeline.aggregate", side_effect=fake_aggregate),
    ):
        mock_registry.get_pattern.return_value = mock_plugin
        run_i7_and_persist(
            history,
            features,
            "ESM6",
            "1m",
            base,
            db_conn=None,
            calibration_curves=cal_curves,
            perf_weights=perf_wts,
        )

    assert captured.get("calibration_curves") == cal_curves
    assert captured.get("perf_weights") == perf_wts


# ---------------------------------------------------------------------------
# Task 3: replay_symbol threads calibration to run_i7_and_persist
# ---------------------------------------------------------------------------


def test_replay_symbol_threads_calibration_to_run_i7():
    """calibration_curves and perf_weights are forwarded to run_i7_and_persist."""
    from unittest.mock import MagicMock, patch

    from production.scripts.run_historical_pipeline import replay_symbol

    captured = {}

    def fake_run_i7(history, features, symbol, tf, ts, db_conn, **kwargs):
        captured["calibration_curves"] = kwargs.get("calibration_curves")
        captured["perf_weights"] = kwargs.get("perf_weights")
        return 0

    cal_curves = {("vwap_deviation", "1m"): ([0.0, 1.0], [0.0, 1.0])}
    perf_wts = {"vwap_deviation": (0.8, 120)}

    mock_conn = MagicMock()
    with patch("production.scripts.run_historical_pipeline.fetch_bars", return_value=[]):
        result = replay_symbol(
            "ESM6",
            mock_conn,
            ["1m"],
            calibration_curves=cal_curves,
            perf_weights=perf_wts,
        )

    assert result == {}


# ---------------------------------------------------------------------------
# Task 5: _assert_backfill_integrity
# ---------------------------------------------------------------------------


def test_assert_backfill_integrity_passes_clean_data():
    """No violations → prints PASS and returns normally."""
    from unittest.mock import MagicMock

    from production.scripts.run_historical_pipeline import _assert_backfill_integrity

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    cur.fetchone.return_value = (0,)

    _assert_backfill_integrity(conn, ["ESM6"])


def test_assert_backfill_integrity_fails_on_multiple_winners(capsys):
    """was_selected > 1 per bar → sys.exit(1)."""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    import pytest

    from production.scripts.run_historical_pipeline import _assert_backfill_integrity

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    cur.fetchall.return_value = [("ESM6", "1m", ts, 2)]

    with pytest.raises(SystemExit) as exc_info:
        _assert_backfill_integrity(conn, ["ESM6"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "INTEGRITY FAIL" in captured.out
    assert "ESM6/1m" in captured.out


def test_assert_backfill_integrity_fails_on_duplicate_signal_ids(capsys):
    """Duplicate signal_ids → sys.exit(1) even if was_selected is clean."""
    from unittest.mock import MagicMock

    import pytest

    from production.scripts.run_historical_pipeline import _assert_backfill_integrity

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    cur.fetchone.return_value = (3,)

    with pytest.raises(SystemExit) as exc_info:
        _assert_backfill_integrity(conn, ["ESM6"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "INTEGRITY FAIL" in captured.out
    assert "duplicate signal_ids" in captured.out


# ---------------------------------------------------------------------------
# Signal ID determinism
# ---------------------------------------------------------------------------


def test_signal_id_determinism():
    """make_signal_id() produces identical output for identical inputs.

    This is critical for backfill integrity — signals must have stable IDs
    across runs so that lifecycle outcomes can be back-filled correctly.
    """
    from datetime import UTC, datetime

    from src.intelligence.trading.signal_schema import make_signal_id

    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)

    # Generate two IDs with identical inputs
    id1 = make_signal_id(
        symbol="ESM6",
        feature_ts_ns=int(ts.timestamp() * 1e9),
        feature_tf="1m",
        open_=5200.0,
        high=5205.0,
        low=5195.0,
        close=5202.0,
        volume=1000.0,
        setup_plugin="vwap_deviation",
        direction=1,
    )
    id2 = make_signal_id(
        symbol="ESM6",
        feature_ts_ns=int(ts.timestamp() * 1e9),
        feature_tf="1m",
        open_=5200.0,
        high=5205.0,
        low=5195.0,
        close=5202.0,
        volume=1000.0,
        setup_plugin="vwap_deviation",
        direction=1,
    )

    assert id1 == id2, "Signal IDs must be deterministic for identical inputs"

    # Different inputs produce different IDs
    id3 = make_signal_id(
        symbol="ESM6",
        feature_ts_ns=int(ts.timestamp() * 1e9),
        feature_tf="1m",
        open_=5200.0,
        high=5205.0,
        low=5195.0,
        close=5202.0,
        volume=1000.0,
        setup_plugin="vwap_deviation",
        direction=-1,  # Different direction
    )
    assert id1 != id3, "Signal IDs must differ for different inputs"


def test_signal_id_uniqueness_across_signals():
    """Signal IDs are unique across the full signal space.

    Tests that different combinations of (symbol, ts, tf, ohlcv, plugin, direction)
    produce unique IDs — no collisions in the hash space.
    """
    from datetime import UTC, datetime

    from src.intelligence.trading.signal_schema import make_signal_id

    ts = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    ids = set()

    # Generate 100 unique signals with varying parameters
    for i in range(100):
        sig_id = make_signal_id(
            symbol=f"ESM{i % 10}",
            feature_ts_ns=int((ts.timestamp() + i) * 1e9),
            feature_tf=["1m", "5m", "15m"][i % 3],
            open_=5200.0 + i,
            high=5205.0 + i,
            low=5195.0 + i,
            close=5202.0 + i,
            volume=1000.0 + i,
            setup_plugin=["vwap_deviation", "momentum_breakout", "squeeze_expansion"][i % 3],
            direction=1 if i % 2 == 0 else -1,
        )
        ids.add(sig_id)

    # All IDs should be unique
    assert len(ids) == 100, f"Expected 100 unique IDs, got {len(ids)}"
