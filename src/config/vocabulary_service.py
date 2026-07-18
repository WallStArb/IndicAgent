"""VocabularyService — cached, library-embedded read-only projection over the
Controlled Vocabulary tables (`controlled_vocabulary` / `vocabulary_group` /
`vocabulary_group_member`).

Phase 161 (Controlled Vocabulary System). Mirrors `ConfigService` exactly: cached at
startup, zero DB calls on the hot path, embedded as a library by any consumer — not a
network service and not a new DAG node (D-05, `.planning/phases/161-controlled-vocabulary-
system-planned/161-CONTEXT.md`). The three vocabulary tables are written only at migration
time; this service is a pure read-side projection over them.

D-06 — the standing rule for adding future namespaces (established in
`docs/research/concept-governance-registries.md`'s "When to Add a New Registry" section,
restated here so the next candidate vocabulary is checked against a written rule, not a
vibe): a namespace earns its place when

    (1) membership is mutable,
    (2) external consumers need enumeration without importing Python, and
    (3) metadata enrichment (labels/descriptions/groups) has real, concrete consumers.

Not worth it for fixed sets no consumer enumerates.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg
import structlog

from src.core.database_manager import create_pool

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class VocabEntry:
    """One row of `controlled_vocabulary` — a single code within a namespace."""

    code: str
    label: str
    description: str | None
    sort_order: int
    is_deprecated: bool


@dataclass(frozen=True)
class GroupEntry:
    """One row of `vocabulary_group` — metadata for a named grouping within a namespace."""

    group_name: str
    label: str
    description: str | None
    sort_order: int


class VocabularyService:
    """Cached, library-embedded projection over the Controlled Vocabulary tables.

    Cache is fully populated in `initialize()` (one prewarm SELECT per table, ~100 rows
    total across all namespaces). Hot-path readers (`codes`, `label`, `group_codes`,
    `namespace`) are synchronous dict lookups against the prewarmed cache — no lazy
    miss-then-fetch DB fallback, per D-05's zero-hot-path-DB-calls mandate.
    """

    def __init__(self, database_url: str, pool: asyncpg.Pool | None = None) -> None:
        self._database_url = database_url
        self._db_pool: asyncpg.Pool | None = pool
        # namespace -> code -> entry
        self._entries: dict[str, dict[str, VocabEntry]] = {}
        # (namespace, group_name) -> frozenset of member codes
        self._groups: dict[tuple[str, str], frozenset[str]] = {}
        # (namespace, group_name) -> group metadata (label/description/sort_order)
        self._group_meta: dict[tuple[str, str], GroupEntry] = {}

    async def initialize(self) -> None:
        """Initialize the database pool (no-op if pool already provided) and prewarm
        the in-memory caches from the three vocabulary tables."""
        if self._db_pool is None:
            self._db_pool = await create_pool(self._database_url, pool_name="vocabulary_service")
        await self._load_all()

    async def close(self) -> None:
        """Close the database pool, releasing all connections."""
        if self._db_pool is not None:
            await self._db_pool.close()
            self._db_pool = None

    async def _load_all(self) -> None:
        """Prewarm `_entries` and `_groups` from the three vocabulary tables in one pass.

        No lazy/miss-then-fetch fallback — the corpus is ~100 rows total, and D-05 mandates
        zero hot-path DB calls, so a cache "miss" must never trigger a DB read.
        """
        assert self._db_pool is not None, "VocabularyService.initialize() not called"

        async with self._db_pool.acquire() as conn:
            entry_rows = await conn.fetch(
                "SELECT namespace, code, label, description, sort_order, is_deprecated "
                "FROM controlled_vocabulary "
                "ORDER BY namespace, sort_order, code"
            )
            group_rows = await conn.fetch(
                "SELECT namespace, group_name, label, description, sort_order "
                "FROM vocabulary_group"
            )
            member_rows = await conn.fetch(
                "SELECT namespace, group_name, code FROM vocabulary_group_member"
            )

        entries: dict[str, dict[str, VocabEntry]] = {}
        for row in entry_rows:
            namespace = row["namespace"]
            entries.setdefault(namespace, {})[row["code"]] = VocabEntry(
                code=row["code"],
                label=row["label"],
                description=row["description"],
                sort_order=row["sort_order"],
                is_deprecated=row["is_deprecated"],
            )

        group_meta: dict[tuple[str, str], GroupEntry] = {}
        # Every registered group starts as an empty set so group_codes() returns
        # frozenset() for a real-but-empty group the same way it does for an unknown one.
        group_members: dict[tuple[str, str], set[str]] = {}
        for row in group_rows:
            key = (row["namespace"], row["group_name"])
            group_members[key] = set()
            group_meta[key] = GroupEntry(
                group_name=row["group_name"],
                label=row["label"],
                description=row["description"],
                sort_order=row["sort_order"],
            )
        for row in member_rows:
            key = (row["namespace"], row["group_name"])
            # Sequential reads on one connection, not one transactional snapshot -- a
            # group inserted between the group_rows and member_rows fetches would be
            # missing here. Convention (migration-time-only writes), not an FK/DB
            # guarantee, so guard defensively rather than assume the key exists.
            group_members.setdefault(key, set()).add(row["code"])

        self._entries = entries
        self._groups = {key: frozenset(codes) for key, codes in group_members.items()}
        self._group_meta = group_meta

    # ------------------------------------------------------------------
    # Hot-path readers — synchronous, DB-free, cache-only.
    # ------------------------------------------------------------------

    def codes(self, namespace: str) -> list[str]:
        """Return all codes for a namespace, in cached (sort_order, code) order."""
        return list(self._entries.get(namespace, {}).keys())

    def active_codes(self, namespace: str) -> list[str]:
        """Return non-deprecated codes for a namespace, in cached (sort_order, code) order."""
        return [
            entry.code
            for entry in self._entries.get(namespace, {}).values()
            if not entry.is_deprecated
        ]

    def label(self, namespace: str, code: str) -> str:
        """Return the entry's label; falls back to the code itself if unknown."""
        entry = self._entries.get(namespace, {}).get(code)
        return entry.label if entry is not None else code

    def group_codes(self, namespace: str, group_name: str) -> frozenset[str]:
        """Return the frozenset of member codes for a group; frozenset() if unknown."""
        return self._groups.get((namespace, group_name), frozenset())

    def group_label(self, namespace: str, group_name: str) -> str:
        """Return the group's label; falls back to the group_name itself if unknown."""
        entry = self._group_meta.get((namespace, group_name))
        return entry.label if entry is not None else group_name

    def group_description(self, namespace: str, group_name: str) -> str | None:
        """Return the group's description; None if unknown."""
        entry = self._group_meta.get((namespace, group_name))
        return entry.description if entry is not None else None

    def namespace(self, namespace: str) -> list[VocabEntry]:
        """Return all VocabEntry rows for a namespace; [] if unknown."""
        return list(self._entries.get(namespace, {}).values())
