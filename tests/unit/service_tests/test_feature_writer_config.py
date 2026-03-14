"""Tests verifying feature_writer_service._load_config() uses get_active_contracts().

Ensures the default symbol list covers all 23 active H6/J6 contracts rather than
the stale 6-symbol hardcoded list (ESH6, NQH6, RTYH6, CLK6, GCM6, NGK6).
"""

from unittest.mock import MagicMock, patch


def _make_service():
    """Construct FeatureWriterService with infrastructure mocked out."""
    with (
        patch("services.feature_writer_service.start_metrics_server"),
        patch("services.feature_writer_service.DatabaseManager"),
        patch("services.feature_writer_service.counter", return_value=MagicMock()),
        patch("services.feature_writer_service.gauge", return_value=MagicMock()),
    ):
        import signal as _signal

        with patch.object(_signal, "signal"):
            from services.feature_writer_service import FeatureWriterService

            service = FeatureWriterService.__new__(FeatureWriterService)
            service.config = service._load_config(None)
    return service


def test_default_config_uses_active_contracts():
    """Default config symbols must include active H6 contracts and exclude stale ones.

    ESH6 and NQH6 are confirmed active. CLK6 (CL April) and GCM6 (GC June)
    are stale symbols that must no longer appear.
    """
    from src.config.settings import Settings, get_active_contracts

    service = _make_service()

    symbols = service.config["service"]["symbols"]
    active = get_active_contracts(Settings())

    assert "ESH6" in symbols, "ESH6 (active contract) must be in default symbol list"
    assert "NQH6" in symbols, "NQH6 (active contract) must be in default symbol list"
    assert "CLK6" not in symbols, "CLK6 (stale) must NOT be in default symbol list"
    assert "GCM6" not in symbols, "GCM6 (stale) must NOT be in default symbol list"
    assert symbols == active, "feature_writer symbols must exactly match get_active_contracts()"


def test_active_contracts_count():
    """Default symbol list must contain at least 20 entries (all 23 active contracts expected)."""
    service = _make_service()

    symbols = service.config["service"]["symbols"]
    assert (
        len(symbols) >= 20
    ), f"Expected at least 20 active contracts, got {len(symbols)}: {symbols}"
