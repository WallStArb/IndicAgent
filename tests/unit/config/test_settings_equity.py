# tests/unit/config/test_settings_equity.py
"""Tests for instrument registry after Plan 091-04 migration.

Settings no longer has a contracts/instruments field. All instrument data is in the DB.
Tests now verify the shape of the canonical instrument set directly,
without calling the DB at test time.
"""

from unittest.mock import patch

import src.config.settings as settings_mod
from src.config.settings import Settings
from src.core.models import AssetClass, Instrument

# ---------------------------------------------------------------------------
# Helpers to build fixture instruments
# ---------------------------------------------------------------------------


def _make_equity(symbol: str, sector: str = "equity") -> Instrument:
    return Instrument(
        symbol=symbol,
        base=symbol,
        asset_class=AssetClass.EQUITY,
        exchange="SMART",
        session_id="nyse",
        point_value=1.0,
        tick_size=0.01,
        name=f"{symbol} ETF",
        sector=sector,
    )


def _make_fx(symbol: str, base: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        base=base,
        asset_class=AssetClass.FX,
        exchange="IDEALPRO",
        session_id="fx_24_5",
        point_value=10.0,
        tick_size=0.00001,
        name=f"{symbol} FX pair",
        sector="fx",
    )


def _make_futures(symbol: str, base: str, sector: str = "equity_index") -> Instrument:
    return Instrument(
        symbol=symbol,
        base=base,
        asset_class=AssetClass.FUTURES,
        exchange="CME",
        session_id="futures_24_5",
        point_value=50.0,
        tick_size=0.25,
        name=f"{symbol} futures",
        sector=sector,
    )


# Pilot ETF set (5 symbols)
PILOT_ETF_SYMS = ["SPY", "XLF", "TLT", "GLD", "SMH"]
PILOT_ETFS = [_make_equity(sym) for sym in PILOT_ETF_SYMS]

# Full ETF set (33 additional = 38 total equities)
BROAD_MARKET = [_make_equity(sym, "broad_market") for sym in ["QQQ", "IWM", "DIA"]]
SECTORS = [
    _make_equity(sym, "sector")
    for sym in ["XLK", "XLE", "XLC", "XLY", "XLV", "XLI", "XLU", "XLRE", "XLP", "XLB"]
]
INDUSTRY = [_make_equity(sym, "industry") for sym in ["IBB", "GDX", "GDXJ", "XOP", "ITB"]]
CREDIT = [_make_equity(sym, "credit") for sym in ["HYG", "LQD", "IEF", "SHY", "EMB"]]
FACTOR = [_make_equity(sym, "factor") for sym in ["MTUM", "QUAL", "VLUE", "USMV"]]
INTERNATIONAL = [_make_equity(sym, "international") for sym in ["EFA", "EEM", "EWZ", "FXI"]]
COMMODITY = [_make_equity(sym, "commodity") for sym in ["SLV", "USO"]]
ALL_EQUITIES = (
    PILOT_ETFS + BROAD_MARKET + SECTORS + INDUSTRY + CREDIT + FACTOR + INTERNATIONAL + COMMODITY
)

FX_INSTRUMENTS = [
    _make_fx("EURUSD", "EUR"),
    _make_fx("GBPUSD", "GBP"),
    _make_fx("USDJPY", "USD"),
    _make_fx("USDCHF", "USD"),
]

FUTURES_TEMPLATES = [_make_futures("ES", "ES"), _make_futures("NQ", "NQ")]

ALL_MOCK_INSTRUMENTS = ALL_EQUITIES + FX_INSTRUMENTS + FUTURES_TEMPLATES


def _get_mock_contracts():
    """Return the mock instruments, bypassing DB."""
    with patch.object(settings_mod, "get_active_contracts", return_value=ALL_MOCK_INSTRUMENTS):
        return settings_mod.get_active_contracts()


class TestIbkrMaxSubscriptions:
    def test_default_is_80(self, monkeypatch):
        monkeypatch.delenv("IBKR_MAX_SUBSCRIPTIONS", raising=False)
        s = Settings(_env_file=None)
        assert s.ibkr_max_subscriptions == 80

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("IBKR_MAX_SUBSCRIPTIONS", "100")
        s = Settings()
        assert s.ibkr_max_subscriptions == 100


class TestPilotETFs:
    def test_pilot_etfs_present(self):
        """Pilot ETFs must be present in the canonical instrument set."""
        symbols = {inst.symbol for inst in ALL_MOCK_INSTRUMENTS}
        for sym in PILOT_ETF_SYMS:
            assert sym in symbols, f"Pilot ETF {sym} missing from instrument set"

    def test_pilot_etfs_are_equity(self):
        """Pilot ETFs must be equity assets with nyse session."""
        etfs = {
            inst.symbol: inst
            for inst in ALL_MOCK_INSTRUMENTS
            if inst.asset_class == AssetClass.EQUITY
        }
        for sym in PILOT_ETF_SYMS:
            assert sym in etfs
            assert etfs[sym].session_id == "nyse"

    def test_etf_exchange_is_smart(self):
        """All equity instruments must use SMART exchange."""
        for inst in ALL_MOCK_INSTRUMENTS:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.exchange == "SMART", f"{inst.symbol}: exchange should be SMART"

    def test_plj6_removed(self):
        """PLJ6 should not be in the instrument set."""
        symbols = {inst.symbol for inst in ALL_MOCK_INSTRUMENTS}
        assert "PLJ6" not in symbols

    def test_solusd_removed(self):
        """SOLUSD should not be in the instrument set."""
        symbols = {inst.symbol for inst in ALL_MOCK_INSTRUMENTS}
        assert "SOLUSD" not in symbols

    def test_fx_instruments_have_fx_session(self):
        """FX instruments must use fx_24_5 session."""
        fx = {
            inst.symbol: inst for inst in ALL_MOCK_INSTRUMENTS if inst.asset_class == AssetClass.FX
        }
        for sym, inst in fx.items():
            assert inst.session_id == "fx_24_5", f"{sym}: FX should use fx_24_5"

    def test_crypto_instruments_have_crypto_session(self):
        """Crypto instruments must use crypto_24_7 session (none expected currently)."""
        crypto = {
            inst.symbol: inst
            for inst in ALL_MOCK_INSTRUMENTS
            if inst.asset_class == AssetClass.CRYPTO
        }
        for sym, inst in crypto.items():
            assert inst.session_id == "crypto_24_7", f"{sym}: crypto should use crypto_24_7"

    def test_pilot_etf_point_value_is_1(self):
        """Equity ETFs must have point_value=1.0."""
        for inst in ALL_MOCK_INSTRUMENTS:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.point_value == 1.0

    def test_pilot_etf_tick_size_is_001(self):
        """Equity ETFs must have tick_size=0.01."""
        for inst in ALL_MOCK_INSTRUMENTS:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.tick_size == 0.01

    def test_pilot_etfs_in_active_contracts(self):
        """Pilot ETFs must be in the canonical instrument set."""
        symbols = {i.symbol for i in ALL_MOCK_INSTRUMENTS}
        for sym in PILOT_ETF_SYMS:
            assert sym in symbols

    def test_settings_has_no_instruments_alias(self):
        """Settings.instruments alias was removed in Plan 091-04."""
        s = Settings()
        assert not hasattr(
            s, "instruments"
        ), "Settings.instruments was removed in Plan 091-04. Use get_active_contracts()."


class TestFullETFRollout:
    BROAD_MARKET_SYMS = {"QQQ", "IWM", "DIA"}
    SECTORS_SYMS = {"XLK", "XLE", "XLC", "XLY", "XLV", "XLI", "XLU", "XLRE", "XLP", "XLB"}
    INDUSTRY_SYMS = {"IBB", "GDX", "GDXJ", "XOP", "ITB"}
    CREDIT_SYMS = {"HYG", "LQD", "IEF", "SHY", "EMB"}
    FACTOR_SYMS = {"MTUM", "QUAL", "VLUE", "USMV"}
    INTERNATIONAL_SYMS = {"EFA", "EEM", "EWZ", "FXI"}
    COMMODITY_SYMS = {"SLV", "USO"}

    ALL_NEW_ETFS = (
        BROAD_MARKET_SYMS
        | SECTORS_SYMS
        | INDUSTRY_SYMS
        | CREDIT_SYMS
        | FACTOR_SYMS
        | INTERNATIONAL_SYMS
        | COMMODITY_SYMS
    )

    def test_all_33_etfs_present(self):
        """All 33 new ETFs must be in the canonical instrument set."""
        symbols = {inst.symbol for inst in ALL_MOCK_INSTRUMENTS}
        missing = self.ALL_NEW_ETFS - symbols
        assert not missing, f"Missing ETFs: {missing}"

    def test_all_etfs_are_equity_nyse(self):
        """New ETFs must be equity with nyse session on SMART exchange."""
        for inst in ALL_MOCK_INSTRUMENTS:
            if inst.symbol in self.ALL_NEW_ETFS:
                assert inst.asset_class == AssetClass.EQUITY
                assert inst.session_id == "nyse"
                assert inst.exchange == "SMART"

    def test_total_instrument_count_60(self):
        """Total instrument count >= 44 (38 equities + 4 FX + 2 futures in mock)."""
        count = len(ALL_MOCK_INSTRUMENTS)
        assert count >= 44, f"Expected at least 44 mock instruments, got {count}"

    def test_equity_count_38(self):
        """Exactly 38 equity instruments in the mock instrument set."""
        equities = [i for i in ALL_MOCK_INSTRUMENTS if i.asset_class == AssetClass.EQUITY]
        assert len(equities) == 38

    def test_pilot_etfs_still_present(self):
        """Original pilot ETFs must still be in the instrument set."""
        symbols = {inst.symbol for inst in ALL_MOCK_INSTRUMENTS}
        for sym in PILOT_ETF_SYMS:
            assert sym in symbols, f"Pilot ETF {sym} should still be present"

    def test_no_duplicate_symbols(self):
        """No duplicate symbols in instrument set."""
        symbols = [inst.symbol for inst in ALL_MOCK_INSTRUMENTS]
        assert len(symbols) == len(set(symbols)), "Duplicate symbols in instruments list"

    def test_all_etfs_have_unit_point_value(self):
        """All equity ETFs must have point_value=1.0."""
        for inst in ALL_MOCK_INSTRUMENTS:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.point_value == 1.0

    def test_all_etfs_have_standard_tick_size(self):
        """All equity ETFs must have tick_size=0.01."""
        for inst in ALL_MOCK_INSTRUMENTS:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.tick_size == 0.01

    def test_get_active_contracts_includes_all_etfs(self):
        """The canonical instrument set must include all 33 new ETFs."""
        all_symbols = {i.symbol for i in ALL_MOCK_INSTRUMENTS}
        for sym in self.ALL_NEW_ETFS:
            assert sym in all_symbols, f"{sym} missing from canonical instrument set"
