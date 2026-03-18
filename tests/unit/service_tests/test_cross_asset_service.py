"""Unit tests for services/cross_asset_service.py

Uses CrossAssetService.__new__ to bypass __init__ (no Kafka/DB required).
Tests cover:
- _extract_base_symbol with known futures symbols
- Message routing fills correct deques
- Non-EQ_INDEX symbols are skipped
- Dedup logic (same tf+ts skipped)
- Staleness detection
- data_quality_score computation
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Service construction helper (bypasses __init__)
# ---------------------------------------------------------------------------

_SYMBOLS = ["ES", "NQ", "RTY", "YM"]
_GROUPS = {"EQ_INDEX": frozenset({"ES", "NQ", "RTY", "YM"})}
_WINDOW = 20
_SHORT = 5
_MIN_NEEDED = _WINDOW + _SHORT  # 25


def _make_service():
    """Construct CrossAssetService without __init__ (no Kafka/DB calls)."""
    from services.cross_asset_service import CrossAssetService

    svc = CrossAssetService.__new__(CrossAssetService)
    svc.running = False
    svc.shutdown_requested = False
    svc.env_name = "development"
    svc._cross_asset_enabled = True
    svc._window_bars = _WINDOW
    svc._metrics_port = 9118
    svc._kafka_bootstrap = "localhost:19092"
    svc._database_url = "postgresql://localhost/indicagent"
    svc._groups = _GROUPS
    svc._close_windows = defaultdict(lambda: deque(maxlen=_MIN_NEEDED + 1))
    svc._vol_windows = defaultdict(lambda: deque(maxlen=_MIN_NEEDED + 1))
    svc._last_bar_ts: dict[str, datetime] = {}
    svc._last_published_ts: dict[str, datetime] = {}
    svc.logger = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# _extract_base_symbol
# ---------------------------------------------------------------------------


def test_extract_base_symbol_es():
    from services.cross_asset_service import _extract_base_symbol

    assert _extract_base_symbol("ESM6") == "ES"


def test_extract_base_symbol_nq():
    from services.cross_asset_service import _extract_base_symbol

    assert _extract_base_symbol("NQM6") == "NQ"


def test_extract_base_symbol_rty():
    from services.cross_asset_service import _extract_base_symbol

    assert _extract_base_symbol("RTYM6") == "RTY"


def test_extract_base_symbol_ym():
    from services.cross_asset_service import _extract_base_symbol

    assert _extract_base_symbol("YMM6") == "YM"


def test_extract_base_symbol_non_eq_index_returns_none():
    from services.cross_asset_service import _extract_base_symbol

    # CL and GC are not in EQ_INDEX group
    assert _extract_base_symbol("CLM6") is None
    assert _extract_base_symbol("GCJ6") is None


# ---------------------------------------------------------------------------
# Message routing: filling correct deques
# ---------------------------------------------------------------------------


def _make_bar_payload(
    symbol: str,
    close: float = 4000.0,
    volume: int = 1000,
    ts: str = "2026-03-18T14:00:00Z",
    tf: str = "1m",
) -> dict:
    """Minimal IntelligenceEvent-like payload dict."""
    return {
        "symbol": symbol,
        "timeframe": tf,
        "ts": ts,
        "bar": {"o": close - 5, "h": close + 5, "l": close - 8, "c": close, "v": volume},
        "i1": {},
        "i2": {},
        "i3": {},
        "i4": {},
        "i5": {},
        "smc": {},
        "i6": {},
    }


def test_message_routing_appends_to_correct_deques():
    """A message for ESM6 should append close/vol to the 'ES' keyed deque."""
    svc = _make_service()
    payload = _make_bar_payload("ESM6", close=4100.0, volume=2000, tf="1m")

    svc._route_message(payload, "1m")

    key = "ES:1m"
    assert len(svc._close_windows[key]) == 1
    assert svc._close_windows[key][-1] == pytest.approx(4100.0)
    assert svc._vol_windows[key][-1] == pytest.approx(2000.0)


def test_non_eq_index_symbol_is_skipped():
    """CLM6 (crude oil) should not populate any deque."""
    svc = _make_service()
    payload = _make_bar_payload("CLM6", close=85.0, tf="1m")

    svc._route_message(payload, "1m")

    # No deque should have been populated
    assert len(svc._close_windows) == 0


def test_last_bar_ts_updated_on_message():
    """_last_bar_ts["ES:1m"] should be set after routing an ES message."""
    svc = _make_service()
    ts_str = "2026-03-18T14:00:00Z"
    payload = _make_bar_payload("ESM6", ts=ts_str, tf="1m")

    svc._route_message(payload, "1m")

    assert "ES:1m" in svc._last_bar_ts


# ---------------------------------------------------------------------------
# Dedup: same (tf, ts) should not trigger re-publish
# ---------------------------------------------------------------------------


def test_dedup_prevents_double_publish():
    """Service should not publish twice for the same (tf, ts)."""
    svc = _make_service()
    ts = datetime(2026, 3, 18, 14, 0, 0, tzinfo=UTC)

    # Mark as already published
    svc._last_published_ts["1m"] = ts

    # Check dedup
    assert svc._is_duplicate("1m", ts) is True


def test_dedup_allows_new_ts():
    """A new timestamp should not be considered a duplicate."""
    svc = _make_service()
    ts1 = datetime(2026, 3, 18, 14, 0, 0, tzinfo=UTC)
    ts2 = datetime(2026, 3, 18, 14, 1, 0, tzinfo=UTC)

    svc._last_published_ts["1m"] = ts1

    assert svc._is_duplicate("1m", ts2) is False


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------

_TF_INTERVAL = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def test_staleness_detected_when_symbol_is_stale():
    """If any symbol's last bar is older than 1 TF-interval, group is stale."""
    svc = _make_service()
    now = datetime(2026, 3, 18, 14, 5, 0, tzinfo=UTC)

    # Set all symbols fresh except RTY (3 minutes stale on 1m => > 1 bar interval)
    interval = timedelta(seconds=_TF_INTERVAL["1m"])
    for sym in _SYMBOLS:
        key = f"{sym}:1m"
        svc._last_bar_ts[key] = now - timedelta(seconds=30)  # fresh

    # RTY is 3 minutes old (3x interval)
    svc._last_bar_ts["RTY:1m"] = now - timedelta(seconds=180)

    is_stale, quality = svc._check_group_staleness("EQ_INDEX", "1m", now)
    assert is_stale is True
    assert quality < 1.0


def test_staleness_not_triggered_when_all_fresh():
    """When all symbols are within 1 TF-interval, group is not stale."""
    svc = _make_service()
    now = datetime(2026, 3, 18, 14, 5, 0, tzinfo=UTC)

    for sym in _SYMBOLS:
        key = f"{sym}:1m"
        svc._last_bar_ts[key] = now - timedelta(seconds=30)  # fresh (< 60s)

    is_stale, quality = svc._check_group_staleness("EQ_INDEX", "1m", now)
    assert is_stale is False
    assert quality == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# data_quality_score
# ---------------------------------------------------------------------------


def test_data_quality_score_partial_fresh():
    """3 of 4 fresh => quality = 0.75."""
    svc = _make_service()
    now = datetime(2026, 3, 18, 14, 5, 0, tzinfo=UTC)
    interval = _TF_INTERVAL["1m"]

    # 3 fresh, 1 stale
    for sym in ["ES", "NQ", "YM"]:
        svc._last_bar_ts[f"{sym}:1m"] = now - timedelta(seconds=30)
    svc._last_bar_ts["RTY:1m"] = now - timedelta(seconds=interval * 3)

    _, quality = svc._check_group_staleness("EQ_INDEX", "1m", now)
    assert quality == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Service does not publish until all 4 symbols have >= window_bars data
# ---------------------------------------------------------------------------


def test_no_publish_until_sufficient_data():
    """_is_group_ready should return False when any symbol has < window_bars data."""
    svc = _make_service()

    # Only 5 bars for each symbol (insufficient)
    for sym in _SYMBOLS:
        key = f"{sym}:1m"
        for _ in range(5):
            svc._close_windows[key].append(4000.0)
            svc._vol_windows[key].append(1000.0)

    assert svc._is_group_ready("EQ_INDEX", "1m") is False


def test_group_ready_when_all_symbols_have_enough_data():
    """_is_group_ready returns True when all 4 symbols have >= window_bars data."""
    svc = _make_service()

    for sym in _SYMBOLS:
        key = f"{sym}:1m"
        for _ in range(_MIN_NEEDED):
            svc._close_windows[key].append(4000.0)
            svc._vol_windows[key].append(1000.0)

    assert svc._is_group_ready("EQ_INDEX", "1m") is True
