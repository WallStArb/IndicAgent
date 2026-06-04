"""Unit tests for make_signal_id — per-signal content-addressed identity."""

from src.intelligence.trading.signal_schema import make_signal_id

_BAR_KWARGS = dict(
    symbol="ES",
    feature_ts_ns=1717440000000000000,
    feature_tf="1m",
    open_=5000.25,
    high=5010.0,
    low=4998.5,
    close=5005.0,
    volume=12345.0,
    setup_plugin="trad_TrendFollowing",
    direction=1,
)


def test_signal_id_stable_across_identical_replay():
    """Same inputs produce the same ID on repeated calls."""
    assert make_signal_id(**_BAR_KWARGS) == make_signal_id(**_BAR_KWARGS)


def test_signal_id_different_for_different_timestamps():
    """Different epoch ns produce different IDs."""
    id1 = make_signal_id(**{**_BAR_KWARGS, "feature_ts_ns": 1717440000000000000})
    id2 = make_signal_id(**{**_BAR_KWARGS, "feature_ts_ns": 1717440000000000001})
    assert id1 != id2


def test_signal_id_different_for_different_close():
    """Different close price produces a different ID."""
    id1 = make_signal_id(**{**_BAR_KWARGS, "close": 5005.0})
    id2 = make_signal_id(**{**_BAR_KWARGS, "close": 5005.1})
    assert id1 != id2


def test_signal_id_tf_normalization():
    """Timeframe is lowercased before hashing."""
    id1 = make_signal_id(**{**_BAR_KWARGS, "feature_tf": "1m"})
    id2 = make_signal_id(**{**_BAR_KWARGS, "feature_tf": "1M"})
    assert id1 == id2


def test_signal_id_different_plugins_same_bar():
    """Two plugins firing on the same bar produce distinct IDs."""
    id1 = make_signal_id(**{**_BAR_KWARGS, "setup_plugin": "trad_TrendFollowing"})
    id2 = make_signal_id(**{**_BAR_KWARGS, "setup_plugin": "trad_MomentumBreakout"})
    assert id1 != id2


def test_signal_id_different_directions_same_bar():
    """Long and short signals from the same plugin on the same bar are distinct."""
    id1 = make_signal_id(**{**_BAR_KWARGS, "direction": 1})
    id2 = make_signal_id(**{**_BAR_KWARGS, "direction": -1})
    assert id1 != id2


def test_signal_id_is_32_hex_chars():
    """Result is always 32 hex characters."""
    sig_id = make_signal_id(**_BAR_KWARGS)
    assert len(sig_id) == 32
    assert all(c in "0123456789abcdef" for c in sig_id)
