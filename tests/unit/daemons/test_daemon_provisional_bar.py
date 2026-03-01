"""Tests for provisional bar flushing and minute-boundary poll logic."""
from datetime import datetime
from unittest.mock import MagicMock, patch


def _make_daemon():
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
        daemon = HighFrequencyTWSDaemon()
    daemon.redis_client = MagicMock()
    daemon.redis_client.xadd = MagicMock()
    daemon.m_bars = MagicMock()
    return daemon


def test_flush_provisional_bar_publishes_tick_derived():
    """_flush_provisional_bars publishes a bar with source='tick_derived'."""
    daemon = _make_daemon()
    # Accumulator has data for minute 5 (the just-closed minute): now=(14,6) → closed=(14,5)
    daemon.tick_accum["ESH6"] = {
        "minute": (14, 5),
        "open": 5100.0, "high": 5108.0, "low": 5097.0, "close": 5104.0,
        "vol_start": 1000, "vol_current": 1250,
    }
    # now = 14:06:02 → closed minute = 14:05:00
    now = datetime(2026, 2, 18, 14, 6, 2)
    daemon._flush_provisional_bars(now)

    assert daemon.redis_client.xadd.called
    call_args = daemon.redis_client.xadd.call_args
    bar_data = call_args[0][1]  # second positional arg = the fields dict
    assert bar_data["source"] == "tick_derived"
    assert bar_data["open"] == "5100.0"
    assert bar_data["high"] == "5108.0"
    assert bar_data["low"] == "5097.0"
    assert bar_data["close"] == "5104.0"
    assert bar_data["volume"] == "250"           # 1250 - 1000
    assert bar_data["timeframe"] == "1m"
    assert bar_data["symbol"] == "ESH6"
    assert "14:05:00" in bar_data["timestamp"]   # start of closed minute


def test_flush_provisional_bar_skips_wrong_minute():
    """_flush_provisional_bars skips symbols whose accumulator minute doesn't match."""
    daemon = _make_daemon()
    # Accumulator for minute 3, but we're flushing for minute 5 (closed)
    daemon.tick_accum["ESH6"] = {
        "minute": (14, 3),  # stale — closed minute is (14, 5)
        "open": 5100.0, "high": 5100.0, "low": 5100.0, "close": 5100.0,
        "vol_start": 1000, "vol_current": 1050,
    }
    now = datetime(2026, 2, 18, 14, 6, 2)  # closed minute = 5 != 3
    daemon._flush_provisional_bars(now)

    assert not daemon.redis_client.xadd.called


def test_minute_boundary_attributes_exist():
    """Daemon must have last_bar_poll_minute and last_provisional_minute initialized."""
    daemon = _make_daemon()
    assert hasattr(daemon, "last_bar_poll_minute")
    assert daemon.last_bar_poll_minute == -1
    assert hasattr(daemon, "last_provisional_minute")
    assert daemon.last_provisional_minute == -1
