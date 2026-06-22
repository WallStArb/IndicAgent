"""Shared utilities for batch oneshot services (psycopg2-based)."""

from __future__ import annotations

from typing import Any

import structlog

from src.config.config_service import ConfigService

_logger = structlog.get_logger()

_CONFIG_QUERY = (
    "SELECT cs.config_key, cs.config_value, csc.value_type "
    "FROM config_state cs "
    "JOIN config_schema csc USING (config_key)"
)


def load_config_service_sync(conn: Any) -> ConfigService:
    """Load all APR keys from config_state into a cache-only ConfigService.

    conn: open psycopg2 connection. No DB reference is stored in the returned
    ConfigService — only the in-memory cache is populated.
    """
    cfg = ConfigService(database_url="")
    with conn.cursor() as cur:
        cur.execute(_CONFIG_QUERY)
        rows = cur.fetchall()
    for config_key, config_value, value_type in rows:
        cfg._cache[config_key] = cfg._parse_value(config_value, value_type)
    _logger.info("config_service_loaded", key_count=len(cfg._cache))
    return cfg
