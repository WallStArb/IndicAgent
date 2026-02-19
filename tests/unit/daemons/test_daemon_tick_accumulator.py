"""Tests for per-symbol tick OHLCV accumulator in the HF daemon."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _make_daemon():
    """Instantiate HighFrequencyTWSDaemon with all external deps mocked."""
    with (
        patch("production.daemons.high_frequency_tws_daemon.prom_counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.prom_gauge", return_value=MagicMock()),
        patch("prometheus_client.Counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.Settings") as mock_settings,
        patch("production.daemons.high_frequency_tws_daemon.MarketHoursManager"),
    ):
        mock_settings.return_value.env_name = ""
        mock_settings.return_value.contracts = []
        mock_settings.return_value.metrics_port = "9108"
        mock_settings.return_value.ib_host = "127.0.0.1"
        mock_settings.return_value.ib_port = 7497
        mock_settings.return_value.ib_client_id = 1
        mock_settings.return_value.hf_async_publish = True
        mock_settings.return_value.redis_host = "localhost"
        mock_settings.return_value.redis_port = 6379
        mock_settings.return_value.redis_db = 0
        mock_settings.return_value.redis_max_connections = 10
        from production.daemons.high_frequency_tws_daemon import HighFrequencyTWSDaemon
        return HighFrequencyTWSDaemon()


def test_tick_accum_initialized_empty():
    """tick_accum starts as empty dict on daemon init."""
    daemon = _make_daemon()
    assert hasattr(daemon, "tick_accum")
    assert daemon.tick_accum == {}


def test_update_tick_accumulator_new_minute():
    """First tick of a minute initializes open/high/low/close from last price."""
    daemon = _make_daemon()
    now = datetime(2026, 2, 18, 14, 5, 30)
    tick = {"last": 5100.25, "volume": 15000}

    daemon._update_tick_accumulator("ESH6", tick, now)

    acc = daemon.tick_accum["ESH6"]
    assert acc["minute"] == 5
    assert acc["open"] == 5100.25
    assert acc["high"] == 5100.25
    assert acc["low"] == 5100.25
    assert acc["close"] == 5100.25
    assert acc["vol_start"] == 15000
    assert acc["vol_current"] == 15000


def test_update_tick_accumulator_running_minute():
    """Subsequent ticks within same minute update high/low/close but not open."""
    daemon = _make_daemon()
    now = datetime(2026, 2, 18, 14, 5, 30)
    daemon._update_tick_accumulator("ESH6", {"last": 5100.25, "volume": 15000}, now)

    # Higher tick
    daemon._update_tick_accumulator("ESH6", {"last": 5103.00, "volume": 15050},
                                    now.replace(second=45))
    # Lower tick
    daemon._update_tick_accumulator("ESH6", {"last": 5099.50, "volume": 15080},
                                    now.replace(second=55))

    acc = daemon.tick_accum["ESH6"]
    assert acc["open"] == 5100.25    # unchanged
    assert acc["high"] == 5103.00    # max seen
    assert acc["low"] == 5099.50     # min seen
    assert acc["close"] == 5099.50   # most recent
    assert acc["vol_current"] == 15080


def test_update_tick_accumulator_minute_rollover():
    """Tick in a new minute resets the accumulator cleanly."""
    daemon = _make_daemon()
    now = datetime(2026, 2, 18, 14, 5, 30)
    daemon._update_tick_accumulator("ESH6", {"last": 5100.25, "volume": 15000}, now)

    # New minute
    new_now = datetime(2026, 2, 18, 14, 6, 5)
    daemon._update_tick_accumulator("ESH6", {"last": 5105.00, "volume": 15200}, new_now)

    acc = daemon.tick_accum["ESH6"]
    assert acc["minute"] == 6
    assert acc["open"] == 5105.00    # reset to new first tick
    assert acc["vol_start"] == 15200  # reset to current cumulative volume
