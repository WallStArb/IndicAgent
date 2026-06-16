"""ConfigService — transactional config read/write with outbox pattern.

Phase 109 config foundation.  OPS config ONLY.
- INFRA keys (DATABASE_URL, KAFKA_BROKERS) must be set via .env.
- STRUCT keys (plugin tiers, DAG order) must be changed via code deployment.

Key guarantees:
- set() validates key domain BEFORE any DB operation.
- set() writes config_history + config_state + config_outbox in ONE transaction.
- SELECT ... FOR UPDATE executes INSIDE the transaction (safe concurrency).
- Secret values are redacted in logs and in the returned ConfigChange.value.
- CONFIG_SET_TOTAL emit is best-effort (metric defined in 109-02; import may fail).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

import asyncpg
import structlog

from src.config.config_schema import (
    ConfigChange,
    ConfigSchemaEntry,
    ConfigValidationError,
    ConfigVersionConflict,
    validate_value,
)
from src.core.database_manager import create_pool

logger = structlog.get_logger(__name__)


class ConfigService:
    """Unified OPS config service with transactional outbox and key domain validation."""

    OPS_PREFIXES: ClassVar[tuple[str, ...]] = (
        "regime.",
        "swarm.",
        "alert.",
        "ai.",
        "feature.",
        "threshold.",
        "roll.",
        "cross_asset.",
        "macro.",
        "ui.",
        "weights.",
    )

    def __init__(self, database_url: str, pool: asyncpg.Pool | None = None) -> None:
        self._database_url = database_url
        self._db_pool: asyncpg.Pool | None = pool
        self._cache: dict[str, Any] = {}

    async def initialize(self) -> None:
        """Initialize the database pool (no-op if pool already provided)."""
        if self._db_pool is None:
            self._db_pool = await create_pool(self._database_url, pool_name="config_service")

    async def close(self) -> None:
        """Close the database pool, releasing all connections."""
        if self._db_pool is not None:
            await self._db_pool.close()
            self._db_pool = None

    def _validate_key_domain(self, key: str) -> None:
        """Raise ConfigValidationError if key is not in the OPS domain.

        INFRA keys (DATABASE_URL, KAFKA_BROKERS) must be set via .env.
        STRUCT keys (plugin tiers, DAG order) must be changed via code deployment.
        """
        if not any(key.startswith(prefix) for prefix in self.OPS_PREFIXES):
            raise ConfigValidationError(
                f"Key {key!r} is not an OPS config key. "
                "INFRA keys (DATABASE_URL, KAFKA_BROKERS) must be set via .env. "
                "STRUCT keys (plugin tiers, DAG order) must be changed via code deployment. "
                f"Valid OPS prefixes: {', '.join(self.OPS_PREFIXES)}"
            )

    def _parse_value(self, value: str, value_type: str) -> Any:
        """Parse a stored string value into the appropriate Python type."""
        vt = value_type.lower()
        if vt == "int":
            return int(value)
        if vt == "float":
            return float(value)
        if vt == "bool":
            return value.lower() in ("true", "1")
        if vt == "json":
            return json.loads(value)
        # str / string
        return value

    def get_sync(self, key: str, default: Any = None) -> Any:
        """Return a cached config value synchronously — no DB I/O.

        MUST be called only after the cache has been pre-warmed via get().
        Safe to call from synchronous hot-path code (e.g., plugin compute_full).
        """
        return self._cache.get(key, default)

    def invalidate(self, key: str) -> None:
        """Evict a key from the in-memory cache, forcing the next get() to re-fetch from DB."""
        self._cache.pop(key, None)

    async def get(self, key: str, default: Any = None) -> Any:
        """Get a config value, using in-memory cache if available.

        Falls back to DB on cache miss, populates cache on success.
        """
        if key in self._cache:
            return self._cache[key]

        assert self._db_pool is not None, "ConfigService.initialize() not called"
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT cs.config_value, csc.value_type "
                "FROM config_state cs "
                "JOIN config_schema csc USING (config_key) "
                "WHERE cs.config_key = $1",
                key,
            )
        if row is None:
            return default
        parsed = self._parse_value(row["config_value"], row["value_type"])
        self._cache[key] = parsed
        return parsed

    async def get_at(self, key: str, t: datetime) -> Any:
        """Get the config value that was live at time t (point-in-time query)."""
        assert self._db_pool is not None, "ConfigService.initialize() not called"
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT ch.config_value, csc.value_type "
                "FROM config_history ch "
                "JOIN config_schema csc ON csc.config_key = ch.config_key "
                "WHERE ch.config_key = $1 AND ch.timestamp < $2 "
                "ORDER BY ch.timestamp DESC LIMIT 1",
                key,
                t,
            )
        if row is None:
            return None
        return self._parse_value(row["config_value"], row["value_type"])

    async def list(self) -> dict[str, Any]:
        """Return all current OPS config values as a parsed dict."""
        assert self._db_pool is not None, "ConfigService.initialize() not called"
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT cs.config_key, cs.config_value, csc.value_type "
                "FROM config_state cs "
                "JOIN config_schema csc USING (config_key)"
            )
        return {
            row["config_key"]: self._parse_value(row["config_value"], row["value_type"])
            for row in rows
        }

    async def set(
        self,
        key: str,
        value: Any,
        changed_by: str = "system",
        expected_version: int | None = None,
        reason: str | None = None,
    ) -> ConfigChange:
        """Write a config value transactionally to config_history, config_state, config_outbox.

        Raises:
            ConfigValidationError: if key is not OPS, key is unknown, or value fails validation.
            ConfigVersionConflict: if expected_version is set and does not match current version.
        """
        # Step 1: key domain validation (BEFORE any DB op)
        self._validate_key_domain(key)

        assert self._db_pool is not None, "ConfigService.initialize() not called"
        async with self._db_pool.acquire() as conn:
            # Step 2: load schema entry
            schema_row = await conn.fetchrow(
                "SELECT * FROM config_schema WHERE config_key = $1", key
            )
            if schema_row is None:
                raise ConfigValidationError(
                    f"Unknown config key {key!r}. Register it in config_schema first."
                )
            schema = ConfigSchemaEntry(**dict(schema_row))

            # Step 3: validate value against schema
            str_value = str(value).lower() if schema.value_type.lower() == "bool" else str(value)
            result = validate_value(value, schema)
            if not result.valid:
                raise ConfigValidationError(f"Validation failed for {key!r}: {result.reason}")

            now = datetime.now(UTC)
            new_version: int

            # Step 4: transactional write (all or nothing)
            async with conn.transaction():
                # SELECT FOR UPDATE inside transaction for concurrency safety
                state_row = await conn.fetchrow(
                    "SELECT config_key, config_value, version "
                    "FROM config_state WHERE config_key = $1 FOR UPDATE",
                    key,
                )

                if state_row and expected_version is not None:
                    if state_row["version"] != expected_version:
                        raise ConfigVersionConflict(
                            expected_version=expected_version,
                            actual_version=state_row["version"],
                        )

                new_version = (state_row["version"] + 1) if state_row else 1

                # Write audit history
                await conn.execute(
                    "INSERT INTO config_history "
                    "(timestamp, config_key, version, config_value, changed_by, reason) "
                    "VALUES ($1, $2, $3, $4, $5, $6)",
                    now,
                    key,
                    new_version,
                    str_value,
                    changed_by,
                    reason,
                )

                # Upsert current state
                await conn.execute(
                    "INSERT INTO config_state (config_key, config_value, version) "
                    "VALUES ($1, $2, $3) "
                    "ON CONFLICT (config_key) DO UPDATE "
                    "SET config_value = EXCLUDED.config_value, "
                    "    version = EXCLUDED.version, "
                    "    updated_at = NOW()",
                    key,
                    str_value,
                    new_version,
                )

                # Write outbox row for Kafka propagation (OutboxDispatcher, 109-02)
                await conn.execute(
                    "INSERT INTO config_outbox "
                    "(config_key, config_value, version, status, retry_count, next_attempt_at) "
                    "VALUES ($1, $2, $3, 'pending', 0, NOW())",
                    key,
                    str_value,
                    new_version,
                )

        # Update cache
        parsed_value = self._parse_value(str_value, schema.value_type)
        self._cache[key] = parsed_value

        # Emit metric (best-effort; CONFIG_SET_TOTAL defined in 109-02)
        try:
            from src.observability.metrics import CONFIG_SET_TOTAL  # noqa: PLC0415

            CONFIG_SET_TOTAL.add(1, {"key": key, "changed_by": changed_by, "outcome": "success"})
        except (ImportError, AttributeError):
            pass

        # Secret redaction in logs and return value
        log_value = "**REDACTED**" if schema.is_secret else str_value
        logger.info(
            "config.set",
            config_key=key,
            config_value=log_value,
            version=new_version,
            changed_by=changed_by,
            reason=reason,
        )

        return_value: Any = "**REDACTED**" if schema.is_secret else parsed_value
        return ConfigChange(
            key=key,
            value=return_value,
            version=new_version,
            changed_at=now,
            changed_by=changed_by,
            reason=reason,
        )

    async def revert_key(
        self,
        key: str,
        version: int,
        changed_by: str,
        reason: str | None = None,
    ) -> ConfigChange:
        """Revert a config key to a specific historical version."""
        assert self._db_pool is not None, "ConfigService.initialize() not called"
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT config_value FROM config_history "
                "WHERE config_key = $1 AND version = $2 LIMIT 1",
                key,
                version,
            )
        if row is None:
            raise ConfigValidationError(f"No history for {key!r}@v{version}")
        return await self.set(
            key,
            row["config_value"],
            changed_by=changed_by,
            reason=f"revert to v{version}: {reason}",
        )
