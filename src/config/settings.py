"""
Application Settings for IndicAgent

Version: 1.0.0
Last Updated: 2025-08-09
Status: Current ✅

Centralizes configuration using pydantic-settings. Provides typed access to IBKR,
Kafka, and daemon flags with sensible defaults and environment variable
overrides.
"""

from __future__ import annotations

import time
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.models import AssetClass, Instrument

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # General
    env_name: str = Field(default="", validation_alias="INDICAGENT_ENV")
    metrics_port: int = Field(default=9108, validation_alias="INDICAGENT_METRICS_PORT")
    intelligence_thread_pool_workers: int = Field(
        default=0,
        validation_alias="INTELLIGENCE_THREAD_POOL_WORKERS",
        description="Thread pool worker count for intelligence pipeline. 0 = cpu_count * 2 (auto).",
    )
    pipeline_metrics_port: int = Field(
        default=9125,
        validation_alias="METRICS_PORT",
        description="Prometheus metrics port for intelligence pipeline instances.",
    )
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/indicagent",
        validation_alias="DATABASE_URL",
    )

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
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openrouter_models: str = Field(
        default=(
            "openrouter/free,"
            "nvidia/nemotron-super-49b-v1:free,"
            "arcee-ai/trinity-large-preview:free,"
            "minimax/minimax-m2.5:free,"
            "google/gemma-4-31b-it:free,"
            "z-ai/glm-4.5-air:free"
        ),
        validation_alias="OPENROUTER_MODELS",
        description=(
            "Comma-separated OpenRouter model slugs in priority order. "
            "Default 'openrouter/auto' routes to best available free model automatically. "
            "Set OPENROUTER_MODELS in .env to pin specific models."
        ),
    )
    ollama_model: str = Field(
        default="gemma4:e4b",
        validation_alias="OLLAMA_MODEL",
        description="Local Ollama model tag — set OLLAMA_MODEL in .env to change",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
        description="Ollama server URL",
    )
    llm_timeout_sec: float = Field(
        default=60.0,
        validation_alias=AliasChoices("llm_timeout_sec", "LLM_TIMEOUT_SEC"),
        description="Timeout in seconds for LLM provider API calls",
    )

    # Alerting webhooks (empty = channel disabled) — Phase 67 Task 2
    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", validation_alias="TELEGRAM_CHAT_ID")
    discord_webhook_url: str = Field(default="", validation_alias="DISCORD_WEBHOOK_URL")

    # IBKR subscription cap (market data lines)
    ibkr_max_subscriptions: int = Field(default=80, validation_alias="IBKR_MAX_SUBSCRIPTIONS")

    # Computed contracts list
    contracts: list[Instrument] = Field(default_factory=list)

    # Roll monitoring runtime config (tuning knobs — not feature flags)
    roll_monitor_window_size: int = Field(default=100, validation_alias="ROLL_MONITOR_WINDOW_SIZE")
    roll_monitor_threshold_default: float = Field(
        default=1.2, validation_alias="ROLL_MONITOR_THRESHOLD_DEFAULT"
    )
    roll_monitor_postroll_bars: int = Field(
        default=10, validation_alias="ROLL_MONITOR_POSTROLL_BARS"
    )
    roll_monitor_cooldown_min: int = Field(
        default=30, validation_alias="ROLL_MONITOR_COOLDOWN_MIN"
    )
    roll_confirmation_bars: int = Field(default=3, validation_alias="ROLL_CONFIRMATION_BARS")
    roll_time_of_day_gated: bool = Field(
        default=True, validation_alias="ROLL_TIME_OF_DAY_GATED"
    )

    # Cross-asset intelligence (always active — feature flag removed Phase 47-04)
    cross_asset_window_bars: int = Field(default=20, validation_alias="CROSS_ASSET_WINDOW_BARS")
    cross_asset_metrics_port: int = Field(default=9118, validation_alias="CROSS_ASSET_METRICS_PORT")

    # Regime gate safety floors (D-01: configurable via env vars — SHADOW-01)
    # Default 0.30 / 1 are safety floors, not quality filters. Lowered from 0.55 / 3 to
    # maximize labeled training data for Phase 49 ML. Phase 49 learns optimal thresholds
    # from accumulated regime-suppressed outcomes.
    regime_prob_min: float = Field(default=0.30, validation_alias="REGIME_PROB_MIN")
    regime_dur_min: int = Field(default=1, validation_alias="REGIME_DUR_MIN")

    # Winner selector configuration (Phase 68-01)
    winner_long_bias: bool = Field(default=True, validation_alias="WINNER_LONG_BIAS")

    # Provider Merger Agent (Phase 54-04)
    # provider_raw_topics: list of provider names whose raw topics to subscribe to
    # provider_routing_config: asset_class -> authoritative provider name
    # provider_silence_bars_threshold: bars of silence before failover is triggered
    provider_raw_topics: list[str] = Field(default_factory=lambda: ["ibkr"])
    provider_routing_config: dict[str, str] = Field(
        default_factory=lambda: {
            "futures": "ibkr",
            "equity": "ibkr",
            "crypto": "ibkr",
            "fx": "ibkr",
        }
    )
    provider_silence_bars_threshold: int = Field(default=5)

    # ---------------------------------------------------------------------------
    # ML/AI Foundation constants (Phase 56)
    # ---------------------------------------------------------------------------
    LLM_SEMANTIC_CACHE_SIZE: int = Field(default=500, description="SemanticCache LRU max entries")
    LLM_RATE_LIMIT_RPM: int = Field(default=60, description="Default LLM requests per minute")
    LLM_RATE_LIMIT_TPM: int = Field(default=100_000, description="Default LLM tokens per minute")

    SHADOW_CORRELATION_THRESHOLD: float = Field(default=0.4, description="Min Pearson rho for promotion")
    SHADOW_MIN_SAMPLES: int = Field(default=100, description="Min N for promotion consideration")

    DATA_QUALITY_MIN_SCORE: float = Field(default=0.85, description="Min quality score to gate discovery")
    ML_DISCOVERY_LOOKBACK_DAYS: int = Field(default=90, description="tsfresh rolling lookback window")
    ML_DISCOVERY_IC_THRESHOLD: float = Field(default=0.05, description="Min IC to include in report")

    MLFLOW_TRACKING_URI: str = Field(default="http://localhost:5000", description="MLflow server URI")
    LANGFUSE_HOST: str = Field(default="http://localhost:3010", description="LangFuse server URI")

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
        # Defaults: base-symbol templates for futures (live contract codes resolved
        # from contract_metadata). Non-futures (crypto, equities, FX) use their actual symbol.
        return [
            # Equity Index Futures
            Instrument(
                symbol="ES",
                base="ES",
                exchange="CME",
                name="E-mini S&P 500",
                point_value=50,
                tick_size=0.25,
                sector="equity_index",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="NQ",
                base="NQ",
                exchange="CME",
                name="E-mini Nasdaq",
                point_value=20,
                tick_size=0.25,
                sector="equity_index",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="RTY",
                base="RTY",
                exchange="CME",
                name="E-mini Russell 2000",
                point_value=50,
                tick_size=0.10,
                sector="equity_index",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="YM",
                base="YM",
                exchange="CBOT",
                name="E-mini Dow",
                point_value=5,
                tick_size=1.0,
                sector="equity_index",
                session_id="futures_24_5",
            ),
            # Energy Futures
            Instrument(
                symbol="CL",
                base="CL",
                exchange="NYMEX",
                name="Crude Oil WTI",
                point_value=1000,
                tick_size=0.01,
                sector="energy",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="NG",
                base="NG",
                exchange="NYMEX",
                name="Natural Gas",
                point_value=10000,
                tick_size=0.001,
                sector="energy",
                session_id="futures_24_5",
            ),
            # Precious & Industrial Metals
            Instrument(
                symbol="GC",
                base="GC",
                exchange="COMEX",
                name="Gold",
                point_value=100,
                tick_size=0.10,
                sector="metals",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="SI",
                base="SI",
                exchange="COMEX",
                name="Silver",
                point_value=5000,
                tick_size=0.005,
                sector="metals",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="HG",
                base="HG",
                exchange="COMEX",
                name="Copper",
                point_value=25000,
                tick_size=0.0005,
                sector="metals",
                session_id="futures_24_5",
            ),
            # Volatility
            Instrument(
                symbol="VIX",
                base="VIX",
                exchange="CFE",
                name="CBOE VIX Futures",
                point_value=1000,
                tick_size=0.05,
                sector="volatility",
                session_id="futures_24_5",
                provider_meta={"ibkr": {"trading_class": "VX"}},
            ),
            # Interest Rate Futures
            Instrument(
                symbol="ZN",
                base="ZN",
                exchange="CBOT",
                name="10-Year T-Note",
                point_value=1000,
                tick_size=0.015625,
                sector="interest_rates",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="ZF",
                base="ZF",
                exchange="CBOT",
                name="5-Year T-Note",
                point_value=1000,
                tick_size=0.0078125,
                sector="interest_rates",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="ZB",
                base="ZB",
                exchange="CBOT",
                name="30-Year T-Bond",
                point_value=1000,
                tick_size=0.03125,
                sector="interest_rates",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="ZT",
                base="ZT",
                exchange="CBOT",
                name="2-Year T-Note",
                point_value=2000,
                tick_size=0.0078125,
                sector="interest_rates",
                session_id="futures_24_5",
            ),
            # Agriculture Futures
            Instrument(
                symbol="ZS",
                base="ZS",
                exchange="CBOT",
                name="Soybeans",
                point_value=50,
                tick_size=0.25,
                sector="agriculture",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="ZC",
                base="ZC",
                exchange="CBOT",
                name="Corn",
                point_value=50,
                tick_size=0.25,
                sector="agriculture",
                session_id="futures_24_5",
            ),
            Instrument(
                symbol="ZW",
                base="ZW",
                exchange="CBOT",
                name="Wheat",
                point_value=50,
                tick_size=0.25,
                sector="agriculture",
                session_id="futures_24_5",
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
            # Spot Crypto (PAXOS) — DEACTIVATED 2026-04-13
            # IBKR PAXOS feed has poor data quality (thin volume, unreliable bars).
            # Poisoned training data. Re-enable with a better feed when available.
            # Instrument(
            #     symbol="BTCUSD",
            #     base="BTC",
            #     exchange="PAXOS",
            #     sector="crypto",
            #     asset_class=AssetClass.CRYPTO,
            #     session_id="crypto_24_7",
            #     name="Bitcoin/US Dollar",
            #     point_value=1.0,
            #     tick_size=0.01,
            # ),
            # Instrument(
            #     symbol="ETHUSD",
            #     base="ETH",
            #     exchange="PAXOS",
            #     sector="crypto",
            #     asset_class=AssetClass.CRYPTO,
            #     session_id="crypto_24_7",
            #     name="Ether/US Dollar",
            #     point_value=1.0,
            #     tick_size=0.01,
            # ),
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

# Cache for DB-backed active contracts
_active_contracts_cache: list[Instrument] | None = None
_active_contracts_last_refresh: float = 0.0
_ACTIVE_CONTRACTS_TTL = 60.0  # seconds


def invalidate_active_contracts_cache() -> None:
    """Force next get_active_contracts() call to re-query the database.

    Called by services that receive ContractUpdateEvent to reduce contract-switch
    latency from ~60s (TTL expiry) to ~1s (next audit cycle).
    """
    global _active_contracts_last_refresh  # noqa: PLW0603
    _active_contracts_last_refresh = 0.0


def _default_settings() -> Settings:
    """Lazily create a module-level Settings instance."""
    global _settings_singleton  # noqa: PLW0603
    if _settings_singleton is None:
        _settings_singleton = Settings()
    return _settings_singleton


def get_settings() -> Settings:
    """Public accessor for the Settings singleton.

    This is the preferred way to access configuration across the codebase.
    Returns the cached module-level Settings instance, creating it on first use.
    """
    return _default_settings()


# CME/CBOT futures month codes → YYYYMM suffix for IBKR lastTradeDateOrContractMonth
_FUTURES_MONTH_CODES: dict[str, int] = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}


def _derive_expiry_from_symbol(symbol: str, base_symbol: str) -> str:
    """Derive IBKR lastTradeDateOrContractMonth (YYYYMM) from a futures symbol.

    E.g. 'ESM6' with base 'ES' → suffix 'M6' → month=6, year=2026 → '202606'.
    Returns '' if the suffix cannot be parsed.
    """
    suffix = symbol[len(base_symbol):]
    if len(suffix) == 2 and suffix[0] in _FUTURES_MONTH_CODES and suffix[1].isdigit():
        month = _FUTURES_MONTH_CODES[suffix[0]]
        year = 2020 + int(suffix[1])
        return f"{year}{month:02d}"
    return ""


def _build_instrument_from_db_row(
    row: tuple,
    config_by_base: dict[str, Instrument],
    config_by_symbol: dict[str, Instrument],
) -> Instrument:
    """Build an Instrument from a DB row, inheriting config-file defaults.

    Args:
        row: (symbol, base_symbol, exchange) tuple from contract_metadata query
        config_by_base: config-file Instruments keyed by base symbol
        config_by_symbol: config-file Instruments keyed by symbol
    """
    symbol, base_symbol, exchange = row[0], row[1], row[2] if len(row) > 2 else ""

    # Look up config-file template to inherit non-DB fields
    template = config_by_symbol.get(symbol) or config_by_base.get(base_symbol)

    # Derive expiry from symbol suffix (e.g. 'ESM6' → '202606') so IBKR
    # qualifies the right contract. The base-symbol template has expiry=''
    # since phase 58.1-05 removed hardcoded contract codes.
    derived_expiry = _derive_expiry_from_symbol(symbol, base_symbol)

    if template is not None:
        updates: dict = {"symbol": symbol}
        if derived_expiry and not template.expiry:
            updates["expiry"] = derived_expiry
        return template.model_copy(update=updates)

    # No config template — build with available DB data and sensible defaults
    return Instrument(
        symbol=symbol,
        base=base_symbol,
        exchange=exchange or "",
        asset_class=AssetClass.FUTURES,
        expiry=derived_expiry,
    )


def get_active_contracts(settings: Settings | None = None) -> list[Instrument]:
    """Return active contract Instruments (e.g. [Instrument(symbol='ESM6'), ...]).

    Queries contract_metadata WHERE is_front_month = true AND asset_class = 'futures',
    reconstructs Instrument objects inheriting config-file defaults (point_value,
    tick_size, session_id, exchange, sector, name, provider_meta) by base_symbol,
    merges DB-sourced futures Instruments + config-file non-futures Instruments,
    caches result for 60 seconds, and falls back to config-file contracts on DB error.
    """
    global _active_contracts_cache, _active_contracts_last_refresh  # noqa: PLW0603

    s = settings or _default_settings()

    # Check cache
    now = time.monotonic()
    cache_age = now - _active_contracts_last_refresh
    if _active_contracts_cache is not None and cache_age < _ACTIVE_CONTRACTS_TTL:
        return _active_contracts_cache

    # Build config-file lookup tables
    config_by_base: dict[str, Instrument] = {}
    config_by_symbol: dict[str, Instrument] = {}
    for c in s.contracts:
        config_by_symbol[c.symbol] = c
        if c.base:
            config_by_base[c.base] = c

    try:
        import psycopg2

        with psycopg2.connect(s.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, base_symbol, exchange "
                    "FROM contract_metadata "
                    "WHERE is_front_month = true AND asset_class = 'futures'"
                )
                rows = cur.fetchall()

        # Build DB-sourced futures Instruments
        db_instruments: list[Instrument] = [
            _build_instrument_from_db_row(row, config_by_base, config_by_symbol)
            for row in rows
        ]

        # Add config-file non-futures Instruments (FX, equity, crypto)
        non_futures = [c for c in s.contracts if c.asset_class != AssetClass.FUTURES]

        result = db_instruments + non_futures
        _active_contracts_cache = result
        _active_contracts_last_refresh = now
        return result

    except Exception as exc:
        import structlog as _structlog
        _structlog.get_logger(__name__).warning(
            "get_active_contracts DB query failed — falling back to config-file contracts",
            error=str(exc),
        )
        return list(s.contracts)


def get_active_symbols(settings: Settings | None = None) -> list[str]:
    """Return active contract symbol strings (e.g. ['ESM6', 'NQM6', ...]).

    Convenience wrapper for call sites that only need symbol strings.
    Delegates to get_active_contracts() for DB-backed resolution.
    """
    return [c.symbol for c in get_active_contracts(settings)]


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
