"""
Simplified Database Manager for Clean Architecture

A focused database manager that provides core functionality without complexity.
"""

import json
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import structlog

logger = structlog.get_logger(__name__)


async def _setup_codecs(conn):
    """Setup JSONB codecs for new connections (init= callback for pool)."""
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


class DatabaseManager:
    """Simplified database manager for core operations."""

    def __init__(self, database_url: str):
        """Initialize database manager."""
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def initialize(self):
        """Initialize database connection pool."""
        if self.pool is not None:
            return
        try:
            self.pool = await asyncpg.create_pool(
                self.database_url, min_size=2, max_size=10, command_timeout=30, init=_setup_codecs
            )
            logger.info("✅ Database pool initialized")
        except Exception as e:
            logger.error("Failed to initialize database pool", error=str(e))
            raise

    async def close(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("✅ Database pool closed")

    @asynccontextmanager
    async def get_connection(self):
        """Get database connection context manager."""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            yield conn

    async def execute_query(self, query: str, *args) -> list[dict[str, Any]]:
        """Execute a query and return results."""
        async with self.get_connection() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def execute_command(self, command: str, *args) -> str:
        """Execute a command and return status."""
        async with self.get_connection() as conn:
            return await conn.execute(command, *args)

    async def execute_batch(self, statement: str, params: list[list[Any]] | list[tuple]) -> None:
        """Execute a batched statement within a single transaction.

        Args:
            statement: SQL statement with positional parameters
            params: Sequence of parameter tuples/lists
        """
        if not params:
            return
        async with self.get_connection() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                await conn.executemany(statement, params)
                await tr.commit()
            except Exception as exc:
                try:
                    await tr.rollback()
                except Exception:
                    pass  # rollback failed; re-raise original exception
                raise exc

    async def health_check(self) -> bool:
        """Check database health."""
        try:
            async with self.get_connection() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.error("Database health check failed", error=str(e))
            return False

    async def fetch(self, query: str, *args) -> list[Any]:
        """Compatibility method for API routes - returns raw rows."""
        async with self.get_connection() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> Any | None:
        """Compatibility method for API routes - returns single row or None."""
        async with self.get_connection() as conn:
            return await conn.fetchrow(query, *args)

    async def upsert_instruments(self, contracts: list) -> int:
        """Upsert instrument records from IBKRContract list into instruments table.

        Returns:
            Number of contracts upserted.
        """
        sql = """
            INSERT INTO instruments (symbol, contract_details, is_active, updated_at)
            VALUES ($1, $2::jsonb, $3, NOW())
            ON CONFLICT (symbol) DO UPDATE
                SET contract_details = EXCLUDED.contract_details,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
        """

        params = [(c.base, c.model_dump(), True) for c in contracts]
        await self.execute_batch(sql, params)
        logger.info("Upserted instruments", count=len(params))
        return len(params)
