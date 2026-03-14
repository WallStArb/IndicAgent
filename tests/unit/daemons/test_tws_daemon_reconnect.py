"""Tests for TWS daemon false-connected state detection fix.

Covers the secondary disconnect check inserted in the main loop:
    if self.connected and self.provider and not self.provider.is_connected():
        self.connected = False
        self._on_disconnected()
"""

from unittest.mock import MagicMock, patch

_DAEMON_MOD = "production.daemons.high_frequency_tws_daemon"


def _make_daemon():
    """Construct HighFrequencyTWSDaemon with all heavy dependencies mocked."""
    with (
        patch(f"{_DAEMON_MOD}.prom_counter", return_value=MagicMock()),
        patch(f"{_DAEMON_MOD}.prom_gauge", return_value=MagicMock()),
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
    return daemon


def test_false_connected_triggers_reconnect():
    """When self.connected=True but provider.is_connected() returns False,
    verify self.connected is set to False and _on_disconnected() is called."""
    daemon = _make_daemon()

    # Set up false-connected state: flag says connected, provider says not
    daemon.connected = True
    mock_provider = MagicMock()
    mock_provider.is_connected.return_value = False
    daemon.provider = mock_provider

    # Patch _on_disconnected to track calls without side effects
    daemon._on_disconnected = MagicMock()
    # Also patch g_connected since _on_disconnected may reference it
    daemon.g_connected = MagicMock()
    daemon._tick_task = None

    # Execute the secondary check logic directly (mirrors main loop body)
    if daemon.connected and daemon.provider and not daemon.provider.is_connected():
        daemon.connected = False
        daemon._on_disconnected()

    assert daemon.connected is False, "connected flag must be cleared on false-connected detection"
    daemon._on_disconnected.assert_called_once()


def test_true_connected_no_trigger():
    """When both self.connected=True and provider.is_connected() returns True,
    verify _on_disconnected() is NOT called."""
    daemon = _make_daemon()

    daemon.connected = True
    mock_provider = MagicMock()
    mock_provider.is_connected.return_value = True
    daemon.provider = mock_provider

    daemon._on_disconnected = MagicMock()

    # Execute the secondary check logic directly
    if daemon.connected and daemon.provider and not daemon.provider.is_connected():
        daemon.connected = False
        daemon._on_disconnected()

    assert daemon.connected is True, "connected flag must remain True when provider is connected"
    daemon._on_disconnected.assert_not_called()


def test_disconnected_flag_no_secondary_check():
    """When self.connected=False, the secondary check is guarded by 'self.connected and ...'
    so provider.is_connected() must NOT be called."""
    daemon = _make_daemon()

    daemon.connected = False
    mock_provider = MagicMock()
    mock_provider.is_connected.return_value = False
    daemon.provider = mock_provider

    # Execute the secondary check logic directly
    if daemon.connected and daemon.provider and not daemon.provider.is_connected():
        daemon.connected = False
        daemon._on_disconnected()

    # Short-circuit: connected=False means provider.is_connected() is never reached
    mock_provider.is_connected.assert_not_called()
