"""Verify dead synchronous tick path has been removed from the daemon."""
from unittest.mock import MagicMock, patch


def _make_daemon():
    """Instantiate daemon with all external dependencies mocked."""
    with (
        patch("production.daemons.high_frequency_tws_daemon.prom_counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.prom_gauge", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.prometheus_client", create=True),
        patch(
            "production.daemons.high_frequency_tws_daemon.HighFrequencyTWSDaemon.__init__.__globals__",
            create=True,
        ),
    ):
        # Direct import after patching at module level
        import importlib

        import production.daemons.high_frequency_tws_daemon as mod
        importlib.reload(mod)

        with (
            patch.object(mod, "prom_counter", return_value=MagicMock()),
            patch.object(mod, "prom_gauge", return_value=MagicMock()),
        ):
            from unittest.mock import patch as p2
            with p2("prometheus_client.Counter") as mock_counter:
                mock_counter.return_value = MagicMock()
                daemon = mod.HighFrequencyTWSDaemon.__new__(mod.HighFrequencyTWSDaemon)
                return daemon, mod


def test_tick_buffer_attribute_removed():
    """tick_buffer deque must not exist after dead code removal."""
    from unittest.mock import MagicMock, patch
    with (
        patch("production.daemons.high_frequency_tws_daemon.prom_counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.prom_gauge", return_value=MagicMock()),
        patch("prometheus_client.Counter", return_value=MagicMock()),
        patch("production.daemons.high_frequency_tws_daemon.Settings"),
    ):
        from production.daemons.high_frequency_tws_daemon import HighFrequencyTWSDaemon
        daemon = HighFrequencyTWSDaemon.__new__(HighFrequencyTWSDaemon)
        assert not hasattr(daemon, "tick_buffer"), "tick_buffer deque should be removed"


def test_process_tick_buffer_method_removed():
    """process_tick_buffer() method must not exist after dead code removal."""
    from production.daemons.high_frequency_tws_daemon import HighFrequencyTWSDaemon
    assert not hasattr(HighFrequencyTWSDaemon, "process_tick_buffer"), (
        "process_tick_buffer should be removed"
    )
