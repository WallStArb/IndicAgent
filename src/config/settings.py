"""
Application Settings for IndicAgent

Version: 1.0.0
Last Updated: 2025-08-09
Status: Current ✅

Centralizes configuration using pydantic-settings. Provides typed access to IBKR,
Redis, and daemon flags with sensible defaults and environment variable
overrides.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.models import AssetClass, Instrument

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Deprecated alias — use Instrument directly
IBKRContract = Instrument


class Settings(BaseSettings):
    # General
    env_name: str = Field(default="", validation_alias="INDICAGENT_ENV")
    metrics_port: int = Field(default=9108, validation_alias="INDICAGENT_METRICS_PORT")
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/indicagent",
        validation_alias="DATABASE_URL",
    )

    # Redis (kept through Phase 30 Plan 4 dual-run; removed in Plan 5)
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_max_connections: int = Field(default=20)

    # Kafka / Redpanda
    kafka_bootstrap_servers: str = Field(
        default="localhost:19092",
        validation_alias="KAFKA_BOOTSTRAP_SERVERS",
    )

    # IBKR
    ib_host: str = Field(
        default="172.18.176.1",
        validation_alias=AliasChoices("ib_host", "IBKR_HOST", "IB_HOST"),
    )
    ib_port: int = Field(
        default=7497,
        validation_alias=AliasChoices("ib_port", "IBKR_PORT", "IB_PORT"),
    )
    ib_client_id: int = Field(default=35, validation_alias="IB_CLIENT_ID")
    ib_timeout_sec: float = Field(
        default=20.0,
        validation_alias=AliasChoices("ib_timeout_sec", "IBKR_TIMEOUT_SEC", "IB_TIMEOUT_SEC"),
        description="Timeout in seconds for IBKR API operations (connect, requests)",
    )

    # High-frequency daemon
    hf_async_publish: bool = Field(default=True, validation_alias="HF_ASYNC_PUBLISH")

    # Contracts (JSON string). Accept two aliases for convenience.
    contracts_json: str | None = Field(default=None, validation_alias="HF_CONTRACTS_JSON")
    ibkr_contracts_json: str | None = Field(default=None, validation_alias="IBKR_CONTRACTS_JSON")

    # LLM providers
    zai_api_key: str = Field(default="", validation_alias="ZAI_API_KEY")
    zai_base_url: str = Field(
        default="https://api.z.ai/api/paas/v4", validation_alias="ZAI_BASE_URL"
    )
    zai_model: str = Field(default="glm-5", validation_alias="ZAI_MODEL")
    zai_timeout_sec: float = Field(default=30.0, validation_alias="ZAI_TIMEOUT_SEC")

    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    llm_timeout_sec: float = Field(
        default=60.0,
        validation_alias=AliasChoices("llm_timeout_sec", "LLM_TIMEOUT_SEC"),
        description="Timeout in seconds for LLM provider API calls",
    )

    # IBKR subscription cap (market data lines)
    ibkr_max_subscriptions: int = Field(default=80, validation_alias="IBKR_MAX_SUBSCRIPTIONS")

    # Computed contracts list
    contracts: list[Instrument] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_prefix="", extra="ignore", env_file=str(_ENV_FILE))

    @property
    def instruments(self) -> list[Instrument]:
        """Alias for contracts — preferred name for multi-asset-class context."""
        return self.contracts

    @field_validator("contracts", mode="before")
    @classmethod
    def build_contracts(cls, v, info):  # type: ignore[override]
        if isinstance(v, list) and v:
            return v
        data = info.data
        raw = data.get("contracts_json") or data.get("ibkr_contracts_json")
        if raw:
            try:
                import json

                parsed = json.loads(raw)
                return [Instrument(**item) for item in parsed if isinstance(item, dict)]
            except Exception:
                # Fall through to defaults
                pass
        # Defaults: All configured futures contracts; front-month as of Feb 2026
        return [
            # Equity Index Futures — June 2026 (M6); rolled from H6 on 2026-03-16 (expires 2026-03-20)
            Instrument(
                symbol="ESM6",
                base="ES",
                exchange="CME",
                expiry="202606",
                name="E-mini S&P 500",
                point_value=50,
                tick_size=0.25,
                sector="equity_index",
            ),
            Instrument(
                symbol="NQM6",
                base="NQ",
                exchange="CME",
                expiry="202606",
                name="E-mini Nasdaq",
                point_value=20,
                tick_size=0.25,
                sector="equity_index",
            ),
            Instrument(
                symbol="RTYM6",
                base="RTY",
                exchange="CME",
                expiry="202606",
                name="E-mini Russell 2000",
                point_value=50,
                tick_size=0.10,
                sector="equity_index",
            ),
            Instrument(
                symbol="YMM6",
                base="YM",
                exchange="CBOT",
                expiry="202606",
                name="E-mini Dow",
                point_value=5,
                tick_size=1.0,
                sector="equity_index",
            ),
            # Energy Futures — May 2026 (CL K6); rolled from J6 on 2026-03-16 (expires 2026-03-20)
            Instrument(
                symbol="CLK6",
                base="CL",
                exchange="NYMEX",
                expiry="202605",
                name="Crude Oil WTI",
                point_value=1000,
                tick_size=0.01,
                sector="energy",
            ),
            # Precious & Industrial Metals — April 2026
            Instrument(
                symbol="GCJ6",
                base="GC",
                exchange="COMEX",
                expiry="20260428",
                name="Gold",
                point_value=100,
                tick_size=0.10,
                sector="metals",
            ),
            Instrument(
                symbol="SIH6",
                base="SI",
                exchange="COMEX",
                expiry="20260327",
                name="Silver",
                point_value=5000,
                tick_size=0.005,
                sector="metals",
            ),
            Instrument(
                symbol="HGH6",
                base="HG",
                exchange="COMEX",
                expiry="20260327",
                name="Copper",
                point_value=25000,
                tick_size=0.0005,
                sector="metals",
            ),
            # Volatility — April 2026 (J6)
            Instrument(
                symbol="VXJ6",
                base="VIX",
                exchange="CFE",
                expiry="20260415",
                name="CBOE VIX Futures",
                point_value=1000,
                tick_size=0.05,
                sector="volatility",
                provider_meta={"trading_class": "VX"},
            ),
            # Interest Rate Futures — June 2026 (M6); ZN/ZB rolled from H6 on 2026-03-16 (expires 2026-03-20)
            Instrument(
                symbol="ZNM6",
                base="ZN",
                exchange="CBOT",
                expiry="202606",
                name="10-Year T-Note",
                point_value=1000,
                tick_size=0.015625,
                sector="interest_rates",
            ),
            Instrument(
                symbol="ZFM6",
                base="ZF",
                exchange="CBOT",
                expiry="202606",
                name="5-Year T-Note",
                point_value=1000,
                tick_size=0.0078125,
                sector="interest_rates",
            ),
            Instrument(
                symbol="ZBM6",
                base="ZB",
                exchange="CBOT",
                expiry="202606",
                name="30-Year T-Bond",
                point_value=1000,
                tick_size=0.03125,
                sector="interest_rates",
            ),
            Instrument(
                symbol="ZTH6",
                base="ZT",
                exchange="CBOT",
                expiry="20260331",
                name="2-Year T-Note",
                point_value=2000,
                tick_size=0.0078125,
                sector="interest_rates",
            ),
            # Agriculture — May 2026 (K6); rolled from H6 on 2026-03-16 (H6 expired 2026-03-13)
            # Grains trade H,K,N,U,Z (Mar,May,Jul,Sep,Dec) — no April contract
            Instrument(
                symbol="ZSK6",
                base="ZS",
                exchange="CBOT",
                expiry="202605",
                name="Soybeans",
                point_value=50,
                tick_size=0.25,
                sector="agriculture",
            ),
            Instrument(
                symbol="ZCK6",
                base="ZC",
                exchange="CBOT",
                expiry="202605",
                name="Corn",
                point_value=50,
                tick_size=0.25,
                sector="agriculture",
            ),
            Instrument(
                symbol="ZWK6",
                base="ZW",
                exchange="CBOT",
                expiry="202605",
                name="Wheat",
                point_value=50,
                tick_size=0.25,
                sector="agriculture",
            ),
            # FX — Spot (IDEALPRO); point_value = USD per pip (0.0001) on 100k lot
            Instrument(
                symbol="EURUSD",
                base="EUR",
                exchange="IDEALPRO",
                sector="fx",
                asset_class=AssetClass.FX,
                session_id="fx_24_5",
                name="Euro/US Dollar",
                point_value=10.0,
                tick_size=0.00001,
            ),
            Instrument(
                symbol="GBPUSD",
                base="GBP",
                exchange="IDEALPRO",
                sector="fx",
                asset_class=AssetClass.FX,
                session_id="fx_24_5",
                name="British Pound/US Dollar",
                point_value=10.0,
                tick_size=0.00001,
            ),
            Instrument(
                symbol="USDJPY",
                base="USD",
                exchange="IDEALPRO",
                sector="fx",
                asset_class=AssetClass.FX,
                session_id="fx_24_5",
                name="US Dollar/Japanese Yen",
                point_value=9.0,
                tick_size=0.001,
            ),
            Instrument(
                symbol="USDCHF",
                base="USD",
                exchange="IDEALPRO",
                sector="fx",
                asset_class=AssetClass.FX,
                session_id="fx_24_5",
                name="US Dollar/Swiss Franc",
                point_value=10.0,
                tick_size=0.00001,
            ),
            # Spot Crypto (PAXOS) — no expiry, 24/7
            Instrument(
                symbol="BTCUSD",
                base="BTC",
                exchange="PAXOS",
                sector="crypto",
                asset_class=AssetClass.CRYPTO,
                session_id="crypto_24_7",
                name="Bitcoin/US Dollar",
                point_value=1.0,
                tick_size=0.01,
            ),
            Instrument(
                symbol="ETHUSD",
                base="ETH",
                exchange="PAXOS",
                sector="crypto",
                asset_class=AssetClass.CRYPTO,
                session_id="crypto_24_7",
                name="Ether/US Dollar",
                point_value=1.0,
                tick_size=0.01,
            ),
            # ETFs — Pilot 5 (equity expansion phase A)
            Instrument(
                symbol="SPY",
                base="SPY",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="SPDR S&P 500 ETF",
                sector="equity",
            ),
            Instrument(
                symbol="XLF",
                base="XLF",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Financial Select Sector SPDR",
                sector="equity",
            ),
            Instrument(
                symbol="TLT",
                base="TLT",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares 20+ Year Treasury Bond ETF",
                sector="equity",
            ),
            Instrument(
                symbol="GLD",
                base="GLD",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="SPDR Gold Shares",
                sector="equity",
            ),
            Instrument(
                symbol="SMH",
                base="SMH",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="VanEck Semiconductor ETF",
                sector="equity",
            ),
            # Broad market
            Instrument(
                symbol="QQQ",
                base="QQQ",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Invesco QQQ Trust",
                sector="broad_market",
            ),
            Instrument(
                symbol="IWM",
                base="IWM",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares Russell 2000 ETF",
                sector="broad_market",
            ),
            Instrument(
                symbol="DIA",
                base="DIA",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="SPDR Dow Jones Industrial Average ETF",
                sector="broad_market",
            ),
            # Sectors
            Instrument(
                symbol="XLK",
                base="XLK",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Technology Select Sector SPDR",
                sector="technology",
            ),
            Instrument(
                symbol="XLE",
                base="XLE",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Energy Select Sector SPDR",
                sector="energy",
            ),
            Instrument(
                symbol="XLC",
                base="XLC",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Communication Services SPDR",
                sector="communications",
            ),
            Instrument(
                symbol="XLY",
                base="XLY",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Consumer Discretionary SPDR",
                sector="consumer_discretionary",
            ),
            Instrument(
                symbol="XLV",
                base="XLV",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Health Care Select Sector SPDR",
                sector="healthcare",
            ),
            Instrument(
                symbol="XLI",
                base="XLI",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Industrial Select Sector SPDR",
                sector="industrials",
            ),
            Instrument(
                symbol="XLU",
                base="XLU",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Utilities Select Sector SPDR",
                sector="utilities",
            ),
            Instrument(
                symbol="XLRE",
                base="XLRE",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Real Estate Select Sector SPDR",
                sector="real_estate",
            ),
            Instrument(
                symbol="XLP",
                base="XLP",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Consumer Staples Select Sector SPDR",
                sector="consumer_staples",
            ),
            Instrument(
                symbol="XLB",
                base="XLB",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="Materials Select Sector SPDR",
                sector="materials",
            ),
            # Industry/thematic
            Instrument(
                symbol="IBB",
                base="IBB",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares Biotechnology ETF",
                sector="biotech",
            ),
            Instrument(
                symbol="GDX",
                base="GDX",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="VanEck Gold Miners ETF",
                sector="gold_miners",
            ),
            Instrument(
                symbol="GDXJ",
                base="GDXJ",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="VanEck Junior Gold Miners ETF",
                sector="gold_miners",
            ),
            Instrument(
                symbol="XOP",
                base="XOP",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="SPDR Oil & Gas Exploration ETF",
                sector="energy",
            ),
            Instrument(
                symbol="ITB",
                base="ITB",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares U.S. Home Construction ETF",
                sector="homebuilders",
            ),
            # Credit/rates
            Instrument(
                symbol="HYG",
                base="HYG",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares iBoxx High Yield Corporate Bond ETF",
                sector="credit",
            ),
            Instrument(
                symbol="LQD",
                base="LQD",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares iBoxx Investment Grade Corporate Bond ETF",
                sector="credit",
            ),
            Instrument(
                symbol="IEF",
                base="IEF",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares 7-10 Year Treasury Bond ETF",
                sector="rates",
            ),
            Instrument(
                symbol="SHY",
                base="SHY",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares 1-3 Year Treasury Bond ETF",
                sector="rates",
            ),
            Instrument(
                symbol="EMB",
                base="EMB",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares J.P. Morgan USD Emerging Markets Bond ETF",
                sector="emerging_markets",
            ),
            # Factor
            Instrument(
                symbol="MTUM",
                base="MTUM",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares MSCI USA Momentum Factor ETF",
                sector="factor",
            ),
            Instrument(
                symbol="QUAL",
                base="QUAL",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares MSCI USA Quality Factor ETF",
                sector="factor",
            ),
            Instrument(
                symbol="VLUE",
                base="VLUE",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares MSCI USA Value Factor ETF",
                sector="factor",
            ),
            Instrument(
                symbol="USMV",
                base="USMV",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares MSCI USA Min Vol Factor ETF",
                sector="factor",
            ),
            # International
            Instrument(
                symbol="EFA",
                base="EFA",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares MSCI EAFE ETF",
                sector="international",
            ),
            Instrument(
                symbol="EEM",
                base="EEM",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares MSCI Emerging Markets ETF",
                sector="emerging_markets",
            ),
            Instrument(
                symbol="EWZ",
                base="EWZ",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares MSCI Brazil ETF",
                sector="emerging_markets",
            ),
            Instrument(
                symbol="FXI",
                base="FXI",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares China Large-Cap ETF",
                sector="emerging_markets",
            ),
            # Macro/commodity
            Instrument(
                symbol="SLV",
                base="SLV",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="iShares Silver Trust",
                sector="commodity",
            ),
            Instrument(
                symbol="USO",
                base="USO",
                asset_class=AssetClass.EQUITY,
                exchange="SMART",
                session_id="nyse",
                point_value=1.0,
                tick_size=0.01,
                name="United States Oil Fund",
                sector="energy",
            ),
        ]


# ---------------------------------------------------------------------------
# Module-level helpers — drop-in replacements for config.symbol_config
# ---------------------------------------------------------------------------

_settings_singleton: Settings | None = None


def _default_settings() -> Settings:
    """Lazily create a module-level Settings instance."""
    global _settings_singleton  # noqa: PLW0603
    if _settings_singleton is None:
        _settings_singleton = Settings()
    return _settings_singleton


def get_active_contracts(settings: Settings | None = None) -> list[str]:
    """Return active contract symbol strings (e.g. ['ESH6', 'NQH6', ...])."""
    s = settings or _default_settings()
    return [c.symbol for c in s.contracts]


def get_base_symbols(settings: Settings | None = None) -> list[str]:
    """Return unique base symbols (e.g. ['ES', 'NQ', ...])."""
    s = settings or _default_settings()
    seen: set[str] = set()
    result: list[str] = []
    for c in s.contracts:
        if c.base not in seen:
            seen.add(c.base)
            result.append(c.base)
    return result


def get_contract_info(symbol: str, settings: Settings | None = None) -> Instrument | None:
    """Lookup contract by symbol (e.g. 'ESH6') or base (e.g. 'ES')."""
    s = settings or _default_settings()
    for c in s.contracts:
        if c.symbol == symbol or c.base == symbol:
            return c
    return None


def get_point_value(symbol: str, settings: Settings | None = None) -> float | None:
    """Get point value for a contract symbol or base symbol."""
    c = get_contract_info(symbol, settings)
    return c.point_value if c else None


def get_tick_size(symbol: str, settings: Settings | None = None) -> float | None:
    """Get tick size for a contract symbol or base symbol."""
    c = get_contract_info(symbol, settings)
    return c.tick_size if c else None
