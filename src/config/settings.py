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

import threading
import time
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.models import AssetClass, Instrument

# Sentinel used by Settings.get_config_value() to distinguish "no default provided"
# from "caller explicitly passed None".
_UNSET = object()

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # General
    env_name: str = Field(default="", validation_alias="INDICAGENT_ENV")
    intelligence_thread_pool_workers: int = Field(
        default=0,
        validation_alias="INTELLIGENCE_THREAD_POOL_WORKERS",
        description="Thread pool worker count for intelligence pipeline. 0 = cpu_count * 2 (auto).",
    )
    feature_vector_pipeline_symbol_filter: list[str] = Field(
        default_factory=list,
        alias="FEATURE_VECTOR_PIPELINE_SYMBOL_FILTER",
        description="Symbol filter for feature vector pipeline sharding. Empty = all active contracts.",
    )
    intelligence_output_drain_batch_size: int = Field(
        default=20,
        alias="INTELLIGENCE_OUTPUT_DRAIN_BATCH_SIZE",
        description="Max items drained per OutputQueue iteration (PERF-06, Plan 03). Increased from 10→20 (Phase 107) to reduce output_queue.full_blocking warnings during high throughput.",
    )
    output_queue_drain_ratio: int = Field(
        default=5,
        alias="OUTPUT_QUEUE_DRAIN_RATIO",
        description="Weighted-fair drain ratio: drain up to RATIO high-priority items per 1 low-priority item (Phase 112 task 4-3). Default 5 prevents journal traffic from starving signals.",
    )
    tier_budget_ms: dict[str, float] = Field(
        default_factory=lambda: {
            "i1": 50.0,  # I1 indicators: 28 plugins, mostly fast numpy; 50ms budget
            "i2": 30.0,  # I2 composite events: 10 plugins; 30ms budget
            "i3": 30.0,  # I3 structure: 8 plugins; 30ms budget
            "i4": 60.0,  # I4 context: 12 plugins (GARCH/Kalman are stateful); 60ms budget
            "i5": 40.0,  # I5 patterns: 16 plugins; 40ms budget
            "smc": 50.0,  # SMC: 16 plugins (HMM regime is stateful); 50ms budget
            "i6": 20.0,  # I6 confluence: 6 plugins; 20ms budget
        },
        alias="TIER_BUDGET_MS",
        description=(
            "Per-tier millisecond deadline budgets (Phase 112 task 5-1, D-12). "
            "On a deadline miss: non-stateful plugins carry forward previous-bar output; "
            "stateful plugins (supports_incremental=True) run anyway with a WARNING log."
        ),
    )
    feature_vector_pipeline_queue_maxsize: int = Field(
        default=100,
        alias="FEATURE_VECTOR_PIPELINE_QUEUE_MAXSIZE",
        description="Per-key worker queue depth; controls back-pressure on the bar ingestion path (PERF-07, Plan 06).",
    )
    replay_batch_size: int = Field(
        default=100,
        validation_alias="REPLAY_BATCH_SIZE",
        description="Max signals per replay auditor cycle. Canary default 100; set higher only during incident triage.",
    )
    replay_interval_seconds: int = Field(
        default=300,
        validation_alias="REPLAY_INTERVAL_SECONDS",
        description="Seconds between replay auditor cycles. Canary default 300 (5 min); 30 was triage-only.",
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

    # LLM providers
    llm_models: str = Field(
        default="",
        validation_alias="LLM_MODELS",
        description=(
            "Comma-separated LiteLLM model strings. When set, overrides Ollama + OpenRouter "
            "provider list entirely. Examples: 'deepseek/deepseek-chat', "
            "'anthropic/claude-3-5-sonnet-latest', 'openrouter/deepseek/deepseek-chat'. "
            "Provider API keys (DEEPSEEK_API_KEY, ANTHROPIC_API_KEY, etc.) are read from env."
        ),
    )
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
    ollama_enabled: bool = Field(
        default=True,
        validation_alias="OLLAMA_ENABLED",
        description="Set false to skip local Ollama and use OpenRouter as primary provider.",
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
    ollama_num_ctx: int = Field(
        default=16384,
        validation_alias="OLLAMA_NUM_CTX",
        description=(
            "Ollama context window (tokens). qwen3.5:4b supports 32K; "
            "16384 gives 14K headroom over the largest full-context prompts."
        ),
    )
    agent_memory_enabled: bool = Field(
        default=False,
        validation_alias="AGENT_MEMORY_ENABLED",
        description=(
            "Enable the pgvector-backed agent memory subsystem (Phase 097). "
            "Gated on MEM-03 shadow validation: recall@10 must show statistically "
            "higher outcome similarity than random baseline (D-12) after N>=200 "
            "labeled episodes. Leave False until shadow gate passes."
        ),
    )
    embedding_model: str = Field(
        default="ollama/nomic-embed-text",
        validation_alias="EMBEDDING_MODEL",
        description=(
            "LiteLLM model string for agent-memory embeddings (Phase 097). "
            "Routed via litellm.aembedding(). Default ollama/nomic-embed-text "
            "(768-dim, local Ollama, no new infra). Swap via EMBEDDING_MODEL in .env."
        ),
    )
    memory_recall_limit: int = Field(
        default=10,
        validation_alias="MEMORY_RECALL_LIMIT",
        description=(
            "Maximum episodic episodes returned per recall() call (Phase 097). "
            "Increase to retrieve more historical analogues at higher recall latency cost."
        ),
    )
    memory_embed_timeout_ms: int = Field(
        default=30,
        validation_alias="MEMORY_EMBED_TIMEOUT_MS",
        description=(
            "Millisecond timeout for the embedding step inside MemoryClient.recall() "
            "(Phase 097). Caps the Ollama HTTP latency contribution to the total "
            "50ms recall budget. On timeout: recall returns []."
        ),
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

    # Roll monitoring runtime config (tuning knobs — not feature flags)
    roll_monitor_window_size: int = Field(default=100, validation_alias="ROLL_MONITOR_WINDOW_SIZE")
    roll_monitor_threshold_default: float = Field(
        default=1.2, validation_alias="ROLL_MONITOR_THRESHOLD_DEFAULT"
    )
    roll_monitor_postroll_bars: int = Field(
        default=10, validation_alias="ROLL_MONITOR_POSTROLL_BARS"
    )
    roll_monitor_cooldown_min: int = Field(default=30, validation_alias="ROLL_MONITOR_COOLDOWN_MIN")
    roll_confirmation_bars: int = Field(default=3, validation_alias="ROLL_CONFIRMATION_BARS")
    roll_time_of_day_gated: bool = Field(default=True, validation_alias="ROLL_TIME_OF_DAY_GATED")

    # Cross-asset intelligence (always active — feature flag removed Phase 47-04)
    cross_asset_window_bars: int = Field(default=20, validation_alias="CROSS_ASSET_WINDOW_BARS")

    # Macro factors service (Phase 64-03A)
    macro_window_bars: int = Field(default=10, validation_alias="MACRO_WINDOW_BARS")

    # Swarm intelligence configuration (Phase 80)
    SWARM_MIN_TF_MINUTES: int = Field(
        default=5,
        validation_alias="SWARM_MIN_TF_MINUTES",
        description="Minimum timeframe in minutes for swarm enrichment (gate: skip 1m bars)",
    )
    SWARM_MIN_CONFIDENCE: float = Field(
        default=0.6,
        validation_alias="SWARM_MIN_CONFIDENCE",
        description="Minimum winner_confidence for swarm enrichment (gate: skip low-quality signals)",
    )
    SWARM_WEIGHT_MIN_SAMPLES: int = Field(
        default=30,
        validation_alias="SWARM_WEIGHT_MIN_SAMPLES",
        description="Minimum resolved predictions before weight learning activates",
    )
    SWARM_WEIGHT_FLOOR: float = Field(
        default=0.05,
        validation_alias="SWARM_WEIGHT_FLOOR",
        description="Minimum agent weight before formal demotion",
    )
    SWARM_MAX_CONCURRENT_CALLS: int = Field(
        default=8,
        validation_alias="SWARM_MAX_CONCURRENT_CALLS",
        description="Max concurrent LLM calls (asyncio.Semaphore capacity)",
    )
    # Regime gate safety floors (D-01: configurable via env vars — SHADOW-01)
    # Default 0.30 / 1 are safety floors, not quality filters. Lowered from 0.55 / 3 to
    # maximize labeled training data for Phase 49 ML. Phase 49 learns optimal thresholds
    # from accumulated regime-suppressed outcomes.
    regime_prob_min: float = Field(default=0.30, validation_alias="REGIME_PROB_MIN")
    regime_dur_min: int = Field(default=1, validation_alias="REGIME_DUR_MIN")

    # Regime gate soft-band upper boundary (Phase 82 D-04).
    # Signals with prob in [REGIME_PROB_MIN, REGIME_PROB_SOFT_MAX) keep regime_eligible=True
    # but have calibrated_confidence linearly attenuated toward SOFT_BAND_FLOOR at the low end.
    # Signals with prob >= REGIME_PROB_SOFT_MAX are unmodified (full confidence).
    # Set REGIME_PROB_SOFT_MAX in .env to tune without deployment.
    REGIME_PROB_SOFT_MAX: float = Field(default=0.55, validation_alias="REGIME_PROB_SOFT_MAX")

    # Winner selector configuration (Phase 68-01)
    # Phase 112 1-F: default changed to False (D-06) — confidence tiebreak, not direction bias.
    winner_long_bias: bool = Field(default=False, validation_alias="WINNER_LONG_BIAS")

    # Signal quality floor (Phase 112 D-05).
    # Minimum publishable confidence after quality multipliers applied.
    # Signals below this floor are rejected and counted by
    # intelligence_pipeline_quality_floor_rejections_total.
    # The empirical value is loaded at startup by quality_gate.load_quality_floor()
    # from .pipeline_quality_floor (written by services/quality_floor_bootstrap.py).
    # This setting serves as the config-level floor and as the default when the
    # bootstrap file is absent.
    SIGNAL_MIN_PUBLISHABLE_CONFIDENCE: float = Field(
        default=0.12,
        validation_alias="SIGNAL_MIN_PUBLISHABLE_CONFIDENCE",
        description="Minimum signal confidence after quality multipliers. Default 0.12 per D-05.",
    )

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

    DATA_QUALITY_MIN_SCORE: float = Field(
        default=0.85, description="Min quality score to gate discovery"
    )
    ML_DISCOVERY_LOOKBACK_DAYS: int = Field(
        default=90, description="tsfresh rolling lookback window"
    )
    ML_DISCOVERY_IC_THRESHOLD: float = Field(
        default=0.05, description="Min IC to include in report"
    )

    @classmethod
    def get_config_value(cls, key: str, default: Any = _UNSET) -> Any:
        """
        Backward-compatible accessor for OPS config values migrated to the config DB.

        Resolution order:
          1. Typed default from src.config.runtime_defaults.RUNTIME_DEFAULTS (Phase 109 fallback).
          2. Caller-provided default if explicitly passed.
          3. None (only if caller explicitly passed default=None or omitted with no RUNTIME_DEFAULTS entry).

        This addresses the cross-AI review consensus finding that returning None for
        numeric thresholds (e.g., REGIME_PROB_MIN=0.30) is unsafe. The RUNTIME_DEFAULTS
        module preserves typed pre-migration values until Phase 110 finishes call-site
        migration AND removes the corresponding Settings fields.

        NOTE: Existing self.settings.SWARM_*, self.settings.REGIME_*, etc. attributes
        continue to work as before; this shim is opt-in for callers that want the
        dotted-key API. The shim is the migration entry point.
        """
        import warnings

        warnings.warn(
            "Settings.get_config_value() is a temporary shim. Migrate to BaseDaemon.get_config() at call site.",
            DeprecationWarning,
            stacklevel=2,
        )
        from src.config.runtime_defaults import RUNTIME_DEFAULTS

        if key in RUNTIME_DEFAULTS:
            return RUNTIME_DEFAULTS[key]
        if default is _UNSET:
            return None
        return default

    model_config = SettingsConfigDict(env_prefix="", extra="ignore", env_file=str(_ENV_FILE))


# ---------------------------------------------------------------------------
# Module-level helpers — drop-in replacements for config.symbol_config
# ---------------------------------------------------------------------------

_settings_lock = threading.RLock()
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
    with _settings_lock:
        _active_contracts_last_refresh = 0.0


def _default_settings() -> Settings:
    """Lazily create a module-level Settings instance.

    Lock held only for the singleton check + Settings() instantiation;
    Settings() does not call _default_settings(), so no re-entrant deadlock.
    """
    global _settings_singleton  # noqa: PLW0603
    with _settings_lock:
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
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


def _derive_expiry_from_symbol(symbol: str, base_symbol: str) -> str:
    """Derive IBKR lastTradeDateOrContractMonth (YYYYMM) from a futures symbol.

    E.g. 'ESM6' with base 'ES' → suffix 'M6' → month=6, year=2026 → '202606'.
    Returns '' if the suffix cannot be parsed.
    """
    suffix = symbol[len(base_symbol) :]
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
    reconstructs Instrument objects inheriting DB-template defaults (point_value,
    tick_size, session_id, exchange, sector, name, provider_meta) by base_symbol
    from the instruments table, then queries instruments table WHERE is_active = true
    AND asset_class != 'futures' for non-futures (equities, FX, crypto).
    Merges both lists, caches result for 60 seconds.
    Fallback on DB error: returns last valid cache, or empty list if cache is cold.
    Settings.contracts does not exist and is never consulted.
    """
    import json as _json

    global _active_contracts_cache, _active_contracts_last_refresh  # noqa: PLW0603

    s = settings or _default_settings()

    # Check cache under lock (atomic read); compute now before entering lock
    now = time.monotonic()
    with _settings_lock:
        cache_age = now - _active_contracts_last_refresh
        if _active_contracts_cache is not None and cache_age < _ACTIVE_CONTRACTS_TTL:
            return _active_contracts_cache
    # Lock released here — DB query runs without holding the lock (Pitfall 2)

    try:
        import psycopg2

        # All three queries share one connection (one-third the overhead of 3 separate connects).
        with psycopg2.connect(s.database_url) as conn:
            with conn.cursor() as cur:
                # 1. Futures templates — provide point_value, tick_size, session_id etc.
                cur.execute(
                    "SELECT symbol, base, contract_details "
                    "FROM instruments "
                    "WHERE contract_details->>'asset_class' = 'futures'"
                )
                tmpl_rows = cur.fetchall()

                # 2. Front-month futures contracts from contract_metadata
                cur.execute(
                    "SELECT symbol, base_symbol, exchange "
                    "FROM contract_metadata "
                    "WHERE is_front_month = true AND asset_class = 'futures'"
                )
                rows = cur.fetchall()

                # 3. Non-futures (equities, FX, crypto) from instruments table
                cur.execute(
                    "SELECT symbol, base, contract_details "
                    "FROM instruments "
                    "WHERE is_active = true AND contract_details->>'asset_class' != 'futures'"
                )
                nf_rows = cur.fetchall()

        config_by_base: dict[str, Instrument] = {}
        config_by_symbol: dict[str, Instrument] = {}
        for tmpl_row in tmpl_rows:
            cd = _json.loads(tmpl_row[2]) if isinstance(tmpl_row[2], str) else tmpl_row[2]
            if cd is None:
                continue
            try:
                inst = Instrument(**cd)
                config_by_symbol[inst.symbol] = inst
                if inst.base:
                    config_by_base[inst.base] = inst
            except Exception:
                pass

        # Build DB-sourced futures Instruments
        db_instruments: list[Instrument] = [
            _build_instrument_from_db_row(row, config_by_base, config_by_symbol) for row in rows
        ]

        non_futures: list[Instrument] = []
        for row in nf_rows:
            cd = _json.loads(row[2]) if isinstance(row[2], str) else row[2]
            if cd is None:
                continue
            try:
                non_futures.append(Instrument(**cd))
            except Exception:
                # Fallback: build with available columns if contract_details is partial
                non_futures.append(
                    Instrument(
                        symbol=cd.get("symbol") or row[0],
                        base=cd.get("base") or row[1] or "",
                        name=cd.get("name", ""),
                        asset_class=cd.get("asset_class", "equity"),
                        exchange=cd.get("exchange", ""),
                        sector=cd.get("sector", ""),
                        tick_size=cd.get("tick_size", 0),
                        point_value=cd.get("point_value", 0),
                        session_id=cd.get("session_id", "equity_rth"),
                        provider_meta=cd.get("provider_meta", {}),
                        expiry=cd.get("expiry", ""),
                    )
                )

        result = db_instruments + non_futures

        # Write cache under lock (atomic write)
        with _settings_lock:
            _active_contracts_cache = result
            _active_contracts_last_refresh = now
        return result

    except Exception as error:
        import structlog as _structlog

        _structlog.get_logger(__name__).warning(
            "get_active_contracts.db_query_failed",
            error=str(error),
        )
        # Fallback: return last valid cache if warm; never consult s.contracts
        with _settings_lock:
            if _active_contracts_cache is not None:
                return _active_contracts_cache
        _structlog.get_logger(__name__).critical(
            "get_active_contracts.cold_start_db_unavailable",
            error=str(error),
        )
        return []


def get_all_futures_contracts(settings: Settings | None = None) -> list[Instrument]:
    """Return Instruments for ALL futures contracts in contract_metadata (including rolled/expired).

    Same as get_active_contracts() but queries without the is_front_month filter.
    Use for replay/backtest passes that should cover rolled contract history.
    Non-futures (equities, FX, crypto) are NOT included — call get_active_contracts() and
    merge if needed.
    """
    import json as _json

    s = settings or _default_settings()
    try:
        import psycopg2

        with psycopg2.connect(s.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, base, contract_details "
                    "FROM instruments "
                    "WHERE contract_details->>'asset_class' = 'futures'"
                )
                tmpl_rows = cur.fetchall()
                cur.execute(
                    "SELECT symbol, base_symbol, exchange "
                    "FROM contract_metadata "
                    "WHERE asset_class = 'futures'"
                )
                rows = cur.fetchall()

        config_by_base: dict[str, Instrument] = {}
        config_by_symbol: dict[str, Instrument] = {}
        for tmpl_row in tmpl_rows:
            cd = _json.loads(tmpl_row[2]) if isinstance(tmpl_row[2], str) else tmpl_row[2]
            if cd is None:
                continue
            try:
                inst = Instrument(**cd)
                config_by_symbol[inst.symbol] = inst
                if inst.base:
                    config_by_base[inst.base] = inst
            except Exception:
                pass

        return [
            _build_instrument_from_db_row(row, config_by_base, config_by_symbol) for row in rows
        ]

    except Exception as error:
        import structlog as _structlog

        _structlog.get_logger(__name__).warning(
            "get_all_futures_contracts.db_query_failed",
            error=str(error),
        )
        return []


def get_active_symbols(settings: Settings | None = None) -> list[str]:
    """Return active contract symbol strings (e.g. ['ESM6', 'NQM6', ...]).

    Convenience wrapper for call sites that only need symbol strings.
    Delegates to get_active_contracts() for DB-backed resolution.
    """
    return [c.symbol for c in get_active_contracts(settings)]


def get_point_value(symbol: str, settings: Settings | None = None) -> float | None:
    """Get point value for a contract symbol or base symbol.

    Looks up the instrument in the active contracts cache. Returns None if not found.
    """
    for c in get_active_contracts(settings):
        if c.symbol == symbol or c.base == symbol:
            return c.point_value
    return None


def get_tick_size(symbol: str, settings: Settings | None = None) -> float | None:
    """Get tick size for a contract symbol or base symbol.

    Looks up the instrument in the active contracts cache. Returns None if not found.
    """
    for c in get_active_contracts(settings):
        if c.symbol == symbol or c.base == symbol:
            return c.tick_size
    return None
