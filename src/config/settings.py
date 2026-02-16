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

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

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
        # Defaults: All configured futures contracts (10 total)
        # Front-month contracts as of Feb 2026
        return [
            # Equity Index Futures — March 2026 (H6)
            IBKRContract(symbol="ESH6", base="ES", exchange="CME", expiry="20260320"),
            IBKRContract(symbol="NQH6", base="NQ", exchange="CME", expiry="20260320"),
            IBKRContract(symbol="RTYH6", base="RTY", exchange="CME", expiry="20260320"),
            # Energy Futures — March/April 2026
            IBKRContract(symbol="CLH6", base="CL", exchange="NYMEX", expiry="20260220"),
            IBKRContract(symbol="NGH6", base="NG", exchange="NYMEX", expiry="20260225"),
            # Precious & Industrial Metals — April 2026
            IBKRContract(symbol="GCJ6", base="GC", exchange="COMEX", expiry="20260428"),
            IBKRContract(symbol="SIH6", base="SI", exchange="COMEX", expiry="20260327"),
            IBKRContract(symbol="HGH6", base="HG", exchange="COMEX", expiry="20260327"),
            IBKRContract(symbol="PLJ6", base="PL", exchange="NYMEX", expiry="20260428"),
            # Volatility — March 2026 (IBKR uses "VIX" not "VX")
            IBKRContract(symbol="VXH6", base="VIX", exchange="CFE", expiry="20260318"),
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
