"""
Tests for Settings base-symbol template contract defaults (Phase 58.1 cleanup).

Verifies that build_contracts() returns base-symbol templates for futures
(symbol == base, no expiry) while non-futures instruments are unchanged.
"""

from src.config.settings import Settings
from src.core.models import AssetClass


class TestBuildContractsBaseSymbolTemplates:
    """Verify build_contracts uses base-symbol templates after Phase 58.1 cleanup."""

    def test_futures_use_base_symbol(self):
        """All futures instruments should have symbol == base (no contract code suffix)."""
        s = Settings()
        futures = [c for c in s.contracts if c.asset_class == AssetClass.FUTURES]
        assert len(futures) > 0, "No futures instruments found"
        for f in futures:
            assert f.symbol == f.base, (
                f"Futures {f.symbol} should use base symbol {f.base} "
                f"(no contract code suffix like ESM6)"
            )

    def test_futures_no_expiry(self):
        """Futures templates should not have expiry (resolved from contract_metadata at runtime)."""
        s = Settings()
        futures = [c for c in s.contracts if c.asset_class == AssetClass.FUTURES]
        assert len(futures) > 0, "No futures instruments found"
        for f in futures:
            assert not f.expiry, (
                f"Futures {f.symbol} should have empty expiry, got '{f.expiry}'"
            )

    def test_futures_have_required_fields(self):
        """Each futures template must have exchange, point_value, tick_size, session_id, sector."""
        s = Settings()
        futures = [c for c in s.contracts if c.asset_class == AssetClass.FUTURES]
        assert len(futures) > 0, "No futures instruments found"
        for f in futures:
            assert f.exchange, f"{f.symbol} missing exchange"
            assert f.point_value > 0, f"{f.symbol} missing point_value"
            assert f.tick_size > 0, f"{f.symbol} missing tick_size"
            assert f.session_id, f"{f.symbol} missing session_id"
            assert f.sector, f"{f.symbol} missing sector"

    def test_non_futures_unchanged(self):
        """Non-futures instruments (crypto, FX, equity) should retain their symbols."""
        s = Settings()
        non_futures = [c for c in s.contracts if c.asset_class != AssetClass.FUTURES]
        assert len(non_futures) > 0, "No non-futures instruments found"
        for c in non_futures:
            assert c.symbol, "Non-futures instrument has empty symbol"

    def test_settings_instantiation(self):
        """Settings() should succeed with base-symbol templates."""
        s = Settings()
        assert len(s.contracts) > 0

    def test_known_futures_bases_present(self):
        """Known base symbols should be present in defaults."""
        s = Settings()
        futures_bases = {c.base for c in s.contracts if c.asset_class == AssetClass.FUTURES}
        expected_bases = {"ES", "NQ", "RTY", "YM"}
        for base in expected_bases:
            assert base in futures_bases, f"Missing futures base {base}"

    def test_futures_session_id_is_futures_24_5(self):
        """All futures templates should use futures_24_5 session."""
        s = Settings()
        futures = [c for c in s.contracts if c.asset_class == AssetClass.FUTURES]
        for f in futures:
            assert f.session_id == "futures_24_5", (
                f"{f.symbol} has session_id={f.session_id!r}, expected 'futures_24_5'"
            )

    def test_no_front_month_codes_in_futures_symbols(self):
        """Futures symbols should not contain quarterly contract codes (M6, H6, etc.)."""
        contract_suffixes = ("M6", "H6", "Z6", "U6", "K6", "J6", "M7", "H7", "Z7", "U7")
        s = Settings()
        futures = [c for c in s.contracts if c.asset_class == AssetClass.FUTURES]
        for f in futures:
            for suffix in contract_suffixes:
                assert not f.symbol.endswith(suffix), (
                    f"Futures symbol {f.symbol!r} looks like a front-month contract code; "
                    f"defaults should use base symbols only"
                )
