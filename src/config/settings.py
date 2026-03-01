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

    # Redis
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_max_connections: int = Field(default=100)

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

    # Computed contracts list
    contracts: list[Instrument] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_prefix="", extra="ignore", env_file=str(_ENV_FILE))

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
            # Equity Index Futures — March 2026 (H6)
            Instrument(
                symbol="ESH6", base="ES", exchange="CME", expiry="20260320",
                name="E-mini S&P 500", point_value=50, tick_size=0.25, sector="equity_index",
            ),
            Instrument(
                symbol="NQH6", base="NQ", exchange="CME", expiry="20260320",
                name="E-mini Nasdaq", point_value=20, tick_size=0.25, sector="equity_index",
            ),
            Instrument(
                symbol="RTYH6", base="RTY", exchange="CME", expiry="20260320",
                name="E-mini Russell 2000", point_value=50, tick_size=0.10, sector="equity_index",
            ),
            Instrument(
                symbol="YMH6", base="YM", exchange="CBOT", expiry="20260320",
                name="E-mini Dow", point_value=5, tick_size=1.0, sector="equity_index",
            ),
            # Energy Futures — April 2026 (CL J6; BZ/NG not available in paper trading)
            Instrument(
                symbol="CLJ6", base="CL", exchange="NYMEX", expiry="20260320",
                name="Crude Oil WTI", point_value=1000, tick_size=0.01, sector="energy",
            ),
            # Precious & Industrial Metals — April 2026
            Instrument(
                symbol="GCJ6", base="GC", exchange="COMEX", expiry="20260428",
                name="Gold", point_value=100, tick_size=0.10, sector="metals",
            ),
            Instrument(
                symbol="SIH6", base="SI", exchange="COMEX", expiry="20260327",
                name="Silver", point_value=5000, tick_size=0.005, sector="metals",
            ),
            Instrument(
                symbol="HGH6", base="HG", exchange="COMEX", expiry="20260327",
                name="Copper", point_value=25000, tick_size=0.0005, sector="metals",
            ),
            Instrument(
                symbol="PLJ6", base="PL", exchange="NYMEX", expiry="20260428",
                name="Platinum", point_value=50, tick_size=0.10, sector="metals",
            ),
            # Volatility — June 2026 (M6) - May contract not yet available
            Instrument(
                symbol="VXM6", base="VX", exchange="CFE", expiry="20260617",
                name="CBOE VIX Futures", point_value=1000, tick_size=0.05, sector="volatility",
            ),
            # Interest Rate Futures — March 2026
            Instrument(
                symbol="ZNH6", base="ZN", exchange="CBOT", expiry="20260320",
                name="10-Year T-Note", point_value=1000,
                tick_size=0.015625, sector="interest_rates",
            ),
            Instrument(
                symbol="ZFH6", base="ZF", exchange="CBOT", expiry="20260331",
                name="5-Year T-Note", point_value=1000,
                tick_size=0.0078125, sector="interest_rates",
            ),
            Instrument(
                symbol="ZBH6", base="ZB", exchange="CBOT", expiry="20260320",
                name="30-Year T-Bond", point_value=1000, tick_size=0.03125, sector="interest_rates",
            ),
            Instrument(
                symbol="ZTH6", base="ZT", exchange="CBOT", expiry="20260331",
                name="2-Year T-Note", point_value=2000,
                tick_size=0.0078125, sector="interest_rates",
            ),
            # Agriculture — March 2026 (CBOT)
            Instrument(
                symbol="ZSH6", base="ZS", exchange="CBOT", expiry="20260313",
                name="Soybeans", point_value=50, tick_size=0.25, sector="agriculture",
            ),
            Instrument(
                symbol="ZCH6", base="ZC", exchange="CBOT", expiry="20260313",
                name="Corn", point_value=50, tick_size=0.25, sector="agriculture",
            ),
            Instrument(
                symbol="ZWH6", base="ZW", exchange="CBOT", expiry="20260313",
                name="Wheat", point_value=50, tick_size=0.25, sector="agriculture",
            ),
            # FX — Spot (IDEALPRO); point_value = USD per pip (0.0001) on 100k lot
            Instrument(
                symbol="EURUSD", base="EUR", exchange="IDEALPRO", sector="fx",
                asset_class=AssetClass.FX,
                name="Euro/US Dollar", point_value=10.0, tick_size=0.00001,
            ),
            Instrument(
                symbol="GBPUSD", base="GBP", exchange="IDEALPRO", sector="fx",
                asset_class=AssetClass.FX,
                name="British Pound/US Dollar", point_value=10.0, tick_size=0.00001,
            ),
            Instrument(
                symbol="USDJPY", base="USD", exchange="IDEALPRO", sector="fx",
                asset_class=AssetClass.FX,
                name="US Dollar/Japanese Yen", point_value=9.0, tick_size=0.001,
            ),
            Instrument(
                symbol="USDCHF", base="USD", exchange="IDEALPRO", sector="fx",
                asset_class=AssetClass.FX,
                name="US Dollar/Swiss Franc", point_value=10.0, tick_size=0.00001,
            ),
            # Spot Crypto (PAXOS) — no expiry, 24/7
            Instrument(
                symbol="BTCUSD", base="BTC", exchange="PAXOS", sector="crypto",
                asset_class=AssetClass.CRYPTO,
                name="Bitcoin/US Dollar", point_value=1.0, tick_size=0.01,
            ),
            Instrument(
                symbol="ETHUSD", base="ETH", exchange="PAXOS", sector="crypto",
                asset_class=AssetClass.CRYPTO,
                name="Ether/US Dollar", point_value=1.0, tick_size=0.01,
            ),
            Instrument(
                symbol="SOLUSD", base="SOL", exchange="PAXOS", sector="crypto",
                asset_class=AssetClass.CRYPTO,
                name="Solana/US Dollar", point_value=1.0, tick_size=0.001,
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
