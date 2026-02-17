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

import os

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IBKRContract(BaseModel):
    symbol: str
    base: str
    exchange: str
    expiry: str
    name: str = ""
    point_value: float = 0
    tick_size: float = 0
    sector: str = ""


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
    ib_host: str = Field(default="172.18.176.1", validation_alias="IB_HOST")
    ib_port: int = Field(default=7497, validation_alias="IB_PORT")
    ib_client_id: int = Field(default=35, validation_alias="IB_CLIENT_ID")

    # High-frequency daemon
    hf_async_publish: bool = Field(default=True, validation_alias="HF_ASYNC_PUBLISH")

    # Contracts (JSON string). Accept two aliases for convenience.
    contracts_json: str | None = Field(default=None, validation_alias="HF_CONTRACTS_JSON")
    ibkr_contracts_json: str | None = Field(default=None, validation_alias="IBKR_CONTRACTS_JSON")

    # Computed contracts list
    contracts: list[IBKRContract] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_prefix="", extra="ignore", env_file=".env")

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
                return [IBKRContract(**item) for item in parsed if isinstance(item, dict)]
            except Exception:
                # Fall through to defaults
                pass
        # Defaults: All configured futures contracts (14 total)
        # Front-month contracts as of Feb 2026
        return [
            # Equity Index Futures — March 2026 (H6)
            IBKRContract(
                symbol="ESH6", base="ES", exchange="CME", expiry="20260320",
                name="E-mini S&P 500", point_value=50, tick_size=0.25, sector="equity_index",
            ),
            IBKRContract(
                symbol="NQH6", base="NQ", exchange="CME", expiry="20260320",
                name="E-mini Nasdaq", point_value=20, tick_size=0.25, sector="equity_index",
            ),
            IBKRContract(
                symbol="RTYH6", base="RTY", exchange="CME", expiry="20260320",
                name="E-mini Russell 2000", point_value=50, tick_size=0.10, sector="equity_index",
            ),
            # Energy Futures — March/April 2026
            IBKRContract(
                symbol="CLH6", base="CL", exchange="NYMEX", expiry="20260220",
                name="Crude Oil WTI", point_value=1000, tick_size=0.01, sector="energy",
            ),
            IBKRContract(
                symbol="NGH6", base="NG", exchange="NYMEX", expiry="20260225",
                name="Natural Gas", point_value=10000, tick_size=0.001, sector="energy",
            ),
            # Precious & Industrial Metals — April 2026
            IBKRContract(
                symbol="GCJ6", base="GC", exchange="COMEX", expiry="20260428",
                name="Gold", point_value=100, tick_size=0.10, sector="metals",
            ),
            IBKRContract(
                symbol="SIH6", base="SI", exchange="COMEX", expiry="20260327",
                name="Silver", point_value=5000, tick_size=0.005, sector="metals",
            ),
            IBKRContract(
                symbol="HGH6", base="HG", exchange="COMEX", expiry="20260327",
                name="Copper", point_value=25000, tick_size=0.0005, sector="metals",
            ),
            IBKRContract(
                symbol="PLJ6", base="PL", exchange="NYMEX", expiry="20260428",
                name="Platinum", point_value=50, tick_size=0.10, sector="metals",
            ),
            # Volatility — March 2026 (IBKR uses "VIX" not "VX")
            IBKRContract(
                symbol="VXH6", base="VIX", exchange="CFE", expiry="20260318",
                name="CBOE VIX Futures", point_value=1000, tick_size=0.05, sector="volatility",
            ),
            # Interest Rate Futures — March 2026
            IBKRContract(
                symbol="ZNH6", base="ZN", exchange="CBOT", expiry="20260320",
                name="10-Year T-Note", point_value=1000,
                tick_size=0.015625, sector="interest_rates",
            ),
            IBKRContract(
                symbol="ZFH6", base="ZF", exchange="CBOT", expiry="20260331",
                name="5-Year T-Note", point_value=1000,
                tick_size=0.0078125, sector="interest_rates",
            ),
            IBKRContract(
                symbol="ZBH6", base="ZB", exchange="CBOT", expiry="20260320",
                name="30-Year T-Bond", point_value=1000, tick_size=0.03125, sector="interest_rates",
            ),
            IBKRContract(
                symbol="ZTH6", base="ZT", exchange="CBOT", expiry="20260331",
                name="2-Year T-Note", point_value=2000,
                tick_size=0.0078125, sector="interest_rates",
            ),
        ]

    @field_validator("ib_host", mode="before")
    @classmethod
    def ib_host_aliases(cls, v):  # type: ignore[override]
        # Accept both IB_HOST and IBKR_HOST for compatibility
        return v or os.getenv("IBKR_HOST") or os.getenv("IB_HOST")

    @field_validator("ib_port", mode="before")
    @classmethod
    def ib_port_aliases(cls, v):  # type: ignore[override]
        # Accept both IB_PORT and IBKR_PORT for compatibility
        if v is not None:
            return v
        port = os.getenv("IBKR_PORT") or os.getenv("IB_PORT")
        return int(port) if port else None


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


def get_contract_info(symbol: str, settings: Settings | None = None) -> IBKRContract | None:
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
