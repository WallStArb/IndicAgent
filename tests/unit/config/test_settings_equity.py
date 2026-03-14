# tests/unit/config/test_settings_equity.py
from src.config.settings import Settings, get_active_contracts
from src.core.models import AssetClass


class TestIbkrMaxSubscriptions:
    def test_default_is_80(self):
        s = Settings()
        assert s.ibkr_max_subscriptions == 80

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("IBKR_MAX_SUBSCRIPTIONS", "100")
        s = Settings()
        assert s.ibkr_max_subscriptions == 100


class TestPilotETFs:
    def test_pilot_etfs_present(self):
        s = Settings()
        symbols = {inst.symbol for inst in s.instruments}
        for sym in ["SPY", "XLF", "TLT", "GLD", "SMH"]:
            assert sym in symbols, f"Pilot ETF {sym} missing from settings"

    def test_pilot_etfs_are_equity(self):
        s = Settings()
        etfs = {
            inst.symbol: inst for inst in s.instruments if inst.asset_class == AssetClass.EQUITY
        }
        for sym in ["SPY", "XLF", "TLT", "GLD", "SMH"]:
            assert sym in etfs
            assert etfs[sym].session_id == "nyse"

    def test_etf_exchange_is_smart(self):
        s = Settings()
        for inst in s.instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.exchange == "SMART", f"{inst.symbol}: exchange should be SMART"

    def test_plj6_removed(self):
        s = Settings()
        symbols = {inst.symbol for inst in s.instruments}
        assert "PLJ6" not in symbols

    def test_solusd_removed(self):
        s = Settings()
        symbols = {inst.symbol for inst in s.instruments}
        assert "SOLUSD" not in symbols

    def test_fx_instruments_have_fx_session(self):
        s = Settings()
        fx = {inst.symbol: inst for inst in s.instruments if inst.asset_class == AssetClass.FX}
        for sym, inst in fx.items():
            assert inst.session_id == "fx_24_5", f"{sym}: FX should use fx_24_5"

    def test_crypto_instruments_have_crypto_session(self):
        s = Settings()
        crypto = {
            inst.symbol: inst for inst in s.instruments if inst.asset_class == AssetClass.CRYPTO
        }
        for sym, inst in crypto.items():
            assert inst.session_id == "crypto_24_7", f"{sym}: crypto should use crypto_24_7"

    def test_pilot_etf_point_value_is_1(self):
        s = Settings()
        for inst in s.instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.point_value == 1.0

    def test_pilot_etf_tick_size_is_001(self):
        s = Settings()
        for inst in s.instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.tick_size == 0.01

    def test_pilot_etfs_in_active_contracts(self):
        symbols = set(get_active_contracts())
        for sym in ["SPY", "XLF", "TLT", "GLD", "SMH"]:
            assert sym in symbols


class TestFullETFRollout:
    BROAD_MARKET = {"QQQ", "IWM", "DIA"}
    SECTORS = {"XLK", "XLE", "XLC", "XLY", "XLV", "XLI", "XLU", "XLRE", "XLP", "XLB"}
    INDUSTRY = {"IBB", "GDX", "GDXJ", "XOP", "ITB"}
    CREDIT = {"HYG", "LQD", "IEF", "SHY", "EMB"}
    FACTOR = {"MTUM", "QUAL", "VLUE", "USMV"}
    INTERNATIONAL = {"EFA", "EEM", "EWZ", "FXI"}
    COMMODITY = {"SLV", "USO"}

    ALL_NEW_ETFS = BROAD_MARKET | SECTORS | INDUSTRY | CREDIT | FACTOR | INTERNATIONAL | COMMODITY

    def test_all_33_etfs_present(self):
        symbols = {inst.symbol for inst in Settings().instruments}
        missing = self.ALL_NEW_ETFS - symbols
        assert not missing, f"Missing ETFs: {missing}"

    def test_all_etfs_are_equity_nyse(self):
        for inst in Settings().instruments:
            if inst.symbol in self.ALL_NEW_ETFS:
                assert inst.asset_class == AssetClass.EQUITY
                assert inst.session_id == "nyse"
                assert inst.exchange == "SMART"

    def test_total_instrument_count_60(self):
        """22 futures/FX/crypto + 38 ETFs = 60 total."""
        assert len(Settings().instruments) == 60

    def test_equity_count_38(self):
        equities = [i for i in Settings().instruments if i.asset_class == AssetClass.EQUITY]
        assert len(equities) == 38

    def test_pilot_etfs_still_present(self):
        symbols = {inst.symbol for inst in Settings().instruments}
        for sym in ["SPY", "XLF", "TLT", "GLD", "SMH"]:
            assert sym in symbols, f"Pilot ETF {sym} should still be present"

    def test_no_duplicate_symbols(self):
        symbols = [inst.symbol for inst in Settings().instruments]
        assert len(symbols) == len(set(symbols)), "Duplicate symbols in instruments list"

    def test_all_etfs_have_unit_point_value(self):
        for inst in Settings().instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.point_value == 1.0

    def test_all_etfs_have_standard_tick_size(self):
        for inst in Settings().instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.tick_size == 0.01

    def test_get_active_contracts_includes_all_etfs(self):
        active = set(get_active_contracts())
        for sym in self.ALL_NEW_ETFS:
            assert sym in active, f"{sym} missing from get_active_contracts()"
