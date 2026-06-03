"""Unit tests for _make_signal_id — content-addressed signal identity."""

from src.intelligence.pipeline.signal_processor import _make_signal_id

_BAR_KWARGS = dict(
    symbol="ES",
    feature_ts_ns=1717440000000000000,
    feature_tf="1m",
    open_=5000.25,
    high=5010.0,
    low=4998.5,
    close=5005.0,
    volume=12345.0,
)


def test_signal_id_stable_across_identical_replay():
    """Same bar inputs produce the same ID on repeated calls."""
    assert _make_signal_id(**_BAR_KWARGS) == _make_signal_id(**_BAR_KWARGS)


def test_signal_id_different_for_different_timestamps():
    """Different epoch ns produce different IDs."""
    id1 = _make_signal_id(**{**_BAR_KWARGS, "feature_ts_ns": 1717440000000000000})
    id2 = _make_signal_id(**{**_BAR_KWARGS, "feature_ts_ns": 1717440000000000001})
    assert id1 != id2


def test_signal_id_different_for_different_close():
    """Different close price produces a different ID."""
    id1 = _make_signal_id(**{**_BAR_KWARGS, "close": 5005.0})
    id2 = _make_signal_id(**{**_BAR_KWARGS, "close": 5005.1})
    assert id1 != id2


def test_signal_id_tf_normalization():
    """Timeframe is lowercased before hashing."""
    id1 = _make_signal_id(**{**_BAR_KWARGS, "feature_tf": "1m"})
    id2 = _make_signal_id(**{**_BAR_KWARGS, "feature_tf": "1M"})
    assert id1 == id2


def test_signal_id_independent_of_plugin_outputs():
    """Two calls with the same bar inputs get the same ID regardless of call context."""
    assert _make_signal_id(**_BAR_KWARGS) == _make_signal_id(**_BAR_KWARGS)


def test_signal_id_is_32_hex_chars():
    """Result is always 32 hex characters."""
    sig_id = _make_signal_id(**_BAR_KWARGS)
    assert len(sig_id) == 32
    assert all(c in "0123456789abcdef" for c in sig_id)
