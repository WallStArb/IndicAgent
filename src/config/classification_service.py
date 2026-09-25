"""ClassificationService -- cached, library-embedded read layer over the Layer 1 security
classification tables (`classification_scheme` / `classification_node` /
`instrument_classification`).

Phase 182 (Security classification hierarchy, todo 384). Mirrors `VocabularyService`
exactly: cached at init like `ConfigService`/`VocabularyService`, zero hot-path DB calls,
embedded as a library by any consumer -- not a network service and not a new DAG node. The
classification tables are written only at migration time (schema here in migration 364;
scheme, node list and assignments are seeded in a later, human-reviewed migration) plus
any future reclassification write path this schema enables (out of this phase's scope).

"Contract asset class" (`instruments.contract_details->>'asset_class'` -- how IBKR settles
the contract: equity/futures/fx) is a DIFFERENT concept from this scheme's level-1
"asset class" node (equity/fixed_income/commodity/currency/crypto/volatility/multi_asset --
what economic exposure the instrument represents, per D-04). Never conflate the two.

This scheme (`indicagent_v1`) is project-owned. It is NOT GICS: GICS assignments are
licensed data; indicagent_v1's equity levels 2-4 only reuse public GICS sector/
industry-group names (D-03).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import structlog

from src.core.database_manager import create_pool

logger = structlog.get_logger(__name__)

DEFAULT_SCHEME = "indicagent_v1"
# indicagent_v1's sector level -- a scheme-definition constant, APR-exempt as a schema
# identifier per CLAUDE.md's exempt list (defines the statistic/structure, not a tunable).
SECTOR_LEVEL = 2

SOURCE_REF_IBKR_REVIEWED = "ibkr_contract_details+review"
SOURCE_REF_FUND_MANDATE = "fund_mandate"
SOURCE_REF_CONTRACT_SPEC = "contract_spec"
ALLOWED_SOURCE_REFS: frozenset[str] = frozenset(
    {SOURCE_REF_IBKR_REVIEWED, SOURCE_REF_FUND_MANDATE, SOURCE_REF_CONTRACT_SPEC}
)

_ALIAS_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")
_SCHEME_PATTERN = re.compile(r"^[a-z0-9_]+$")


def check_scheme_identifier(scheme: str) -> None:
    """Raise ValueError unless `scheme` is safe to embed in SQL text (^[a-z0-9_]+$)."""
    if not _SCHEME_PATTERN.match(scheme):
        raise ValueError(f"scheme {scheme!r} is not a safe SQL identifier (^[a-z0-9_]+$)")


def unclassified_code(scheme: str = DEFAULT_SCHEME) -> str:
    """The scheme-qualified label a lookup returns instead of NULL/None (D-08)."""
    return f"{scheme}:unclassified"


def label_or_unclassified(name: str | None, scheme: str = DEFAULT_SCHEME) -> str:
    """Returns `name` when non-empty, else the scheme-qualified unclassified label."""
    return name if name else unclassified_code(scheme)


def current_level_name_sql(
    instrument_alias: str, level: int = SECTOR_LEVEL, scheme: str = DEFAULT_SCHEME
) -> str:
    """A parenthesized correlated scalar subquery yielding the name of the level-`level`
    ancestor of `instrument_alias`'s symbol's CURRENT (valid_to IS NULL) assignment in
    `scheme`, or NULL when there is no current assignment or it does not reach that level.

    `instrument_alias` and `scheme` must be identifier-safe and `level` an int >= 1 --
    anything else raises ValueError. Only module-validated identifiers ever reach the
    embedded SQL text; caller-controlled data must never be passed here directly.
    """
    if not _ALIAS_PATTERN.match(instrument_alias):
        raise ValueError(
            f"current_level_name_sql: instrument_alias={instrument_alias!r} is not a "
            "safe SQL identifier (must match ^[a-z_][a-z0-9_]*$)."
        )
    check_scheme_identifier(scheme)
    if not isinstance(level, int) or level < 1:
        raise ValueError(f"current_level_name_sql: level={level!r} must be an int >= 1.")
    return (
        "(SELECT anc.name FROM instrument_classification ic "
        "JOIN classification_node n ON (n.scheme, n.code) = (ic.scheme, ic.code) "
        f"JOIN classification_node anc ON anc.scheme = ic.scheme AND anc.code = n.path[{level}] "
        f"WHERE ic.symbol = {instrument_alias}.symbol AND ic.scheme = '{scheme}' "
        "AND ic.valid_to IS NULL)"
    )


@dataclass(frozen=True)
class ClassificationAssignment:
    """A candidate (code, source_ref) pair for onboarding (Plan 04) -- validated eagerly
    so a bad source_ref or empty code fails at construction, not at INSERT time."""

    code: str
    source_ref: str

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("ClassificationAssignment: code must not be empty.")
        if self.source_ref not in ALLOWED_SOURCE_REFS:
            raise ValueError(
                f"ClassificationAssignment: source_ref={self.source_ref!r} not in "
                f"ALLOWED_SOURCE_REFS ({sorted(ALLOWED_SOURCE_REFS)})."
            )


@dataclass(frozen=True)
class ClassificationNode:
    """One row of `classification_node`."""

    scheme: str
    code: str
    parent_code: str | None
    level: int
    name: str
    path: tuple[str, ...]


@dataclass(frozen=True)
class AssignmentRow:
    """One row of `instrument_classification`."""

    symbol: str
    scheme: str
    code: str
    valid_from: date
    valid_to: date | None
    source_ref: str


def _build_caches(node_rows: Any, assignment_rows: Any) -> tuple[
    dict[tuple[str, str], ClassificationNode],
    dict[tuple[str, str], list[AssignmentRow]],
]:
    """Pure row-to-cache builder, no DB access -- exercised directly by unit tests with
    literal rows (dicts or asyncpg Records, both support `row["key"]`). Enforces two
    integrity invariants as RuntimeError (loud crash, not a warning): every assignment's
    code must reference a loaded node, and no two rows for the same (symbol, scheme) may
    have overlapping [valid_from, valid_to) windows.
    """
    nodes: dict[tuple[str, str], ClassificationNode] = {}
    for row in node_rows:
        key = (row["scheme"], row["code"])
        nodes[key] = ClassificationNode(
            scheme=row["scheme"],
            code=row["code"],
            parent_code=row["parent_code"],
            level=row["level"],
            name=row["name"],
            path=tuple(row["path"]),
        )

    by_symbol: dict[tuple[str, str], list[AssignmentRow]] = {}
    for row in assignment_rows:
        node_key = (row["scheme"], row["code"])
        if node_key not in nodes:
            raise RuntimeError(
                f"ClassificationService: assignment for symbol={row['symbol']!r} "
                f"scheme={row['scheme']!r} references code={row['code']!r}, which is not "
                "a loaded classification_node -- referential integrity violation."
            )
        assignment = AssignmentRow(
            symbol=row["symbol"],
            scheme=row["scheme"],
            code=row["code"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            source_ref=row["source_ref"],
        )
        by_symbol.setdefault((row["scheme"], row["symbol"]), []).append(assignment)

    assignments: dict[tuple[str, str], list[AssignmentRow]] = {}
    for key, rows in by_symbol.items():
        ordered = sorted(rows, key=lambda a: a.valid_from)
        for current, following in zip(ordered, ordered[1:]):
            if current.valid_to is None or current.valid_to > following.valid_from:
                raise RuntimeError(
                    f"ClassificationService: overlapping assignment windows for "
                    f"symbol={key[1]!r} scheme={key[0]!r} -- "
                    f"[{current.valid_from}, {current.valid_to}) overlaps "
                    f"[{following.valid_from}, {following.valid_to})."
                )
        assignments[key] = ordered

    return nodes, assignments


class ClassificationService:
    """Cached, library-embedded read layer over Layer 1 classification tables.

    Cache is fully populated in `initialize()` (one prewarm pass over two tables). Hot-path
    readers (`node`, `assignment_as_of`, `node_at_level`, `name_at_level`, `max_level`) are
    synchronous dict lookups against the prewarmed cache -- no lazy miss-then-fetch DB
    fallback, per D-08's zero-hot-path-DB-calls mandate. `node_at_level`/`name_at_level`
    never return None: an assignment that does not exist, or does not reach the requested
    level as of the given date, yields the scheme-qualified unclassified label instead.
    """

    def __init__(self, database_url: str, pool: asyncpg.Pool | None = None) -> None:
        self._database_url = database_url
        self._db_pool: asyncpg.Pool | None = pool
        # Only close a pool this instance created itself -- closing a caller-injected
        # pool (e.g. the coverage auditor's BaseBatch pool) would break that caller's
        # own connection lifecycle.
        self._owns_pool = pool is None
        self._nodes: dict[tuple[str, str], ClassificationNode] = {}
        self._assignments: dict[tuple[str, str], list[AssignmentRow]] = {}

    async def initialize(self) -> None:
        """Initialize the database pool (no-op if pool already provided) and prewarm
        the in-memory caches from classification_node/instrument_classification."""
        if self._db_pool is None:
            self._db_pool = await create_pool(
                self._database_url, pool_name="classification_service"
            )
        await self._load_all()

    async def close(self) -> None:
        """Close the database pool, but only if this instance created it itself."""
        if self._db_pool is not None and self._owns_pool:
            await self._db_pool.close()
            self._db_pool = None

    async def _load_all(self) -> None:
        """Prewarm `_nodes`/`_assignments` from the two classification tables in one
        acquired-connection pass, then hand the raw rows to the pure `_build_caches`
        builder, which enforces referential/overlap integrity as RuntimeError."""
        assert self._db_pool is not None, "ClassificationService.initialize() not called"

        async with self._db_pool.acquire() as conn:
            node_rows = await conn.fetch(
                "SELECT scheme, code, parent_code, level, name, path FROM classification_node"
            )
            assignment_rows = await conn.fetch(
                "SELECT symbol, scheme, code, valid_from, valid_to, source_ref "
                "FROM instrument_classification "
                "ORDER BY symbol, scheme, valid_from"
            )

        self._nodes, self._assignments = _build_caches(node_rows, assignment_rows)

    # ------------------------------------------------------------------
    # Hot-path readers — synchronous, DB-free, cache-only.
    # ------------------------------------------------------------------

    def node(self, code: str, scheme: str = DEFAULT_SCHEME) -> ClassificationNode | None:
        """Return the loaded node for (scheme, code); None if unknown."""
        return self._nodes.get((scheme, code))

    def assignment_as_of(
        self, symbol: str, *, scheme: str = DEFAULT_SCHEME, as_of: date | None = None
    ) -> AssignmentRow | None:
        """Return the assignment row whose [valid_from, valid_to) window contains
        `as_of` (default today, UTC); None if no assignment exists or none applies as of
        that date (D-07 -- no history before an instrument's own build date)."""
        if as_of is None:
            as_of = datetime.now(UTC).date()
        for row in self._assignments.get((scheme, symbol), []):
            if row.valid_from <= as_of and (row.valid_to is None or as_of < row.valid_to):
                return row
        return None

    def node_at_level(
        self,
        symbol: str,
        level: int,
        *,
        scheme: str = DEFAULT_SCHEME,
        as_of: date | None = None,
    ) -> str:
        """Return the code of the level-`level` ancestor of `symbol`'s as-of assignment,
        or the scheme-qualified unclassified label -- never None -- when no assignment
        applies as of that date or the assignment does not reach that level (D-05/D-08)."""
        ancestor = self._ancestor(symbol, level, scheme=scheme, as_of=as_of)
        return ancestor.code if ancestor is not None else unclassified_code(scheme)

    def name_at_level(
        self,
        symbol: str,
        level: int,
        *,
        scheme: str = DEFAULT_SCHEME,
        as_of: date | None = None,
    ) -> str:
        """Return the name of the level-`level` ancestor, or the scheme-qualified
        unclassified label -- never None."""
        ancestor = self._ancestor(symbol, level, scheme=scheme, as_of=as_of)
        return ancestor.name if ancestor is not None else unclassified_code(scheme)

    def _ancestor(
        self, symbol: str, level: int, *, scheme: str, as_of: date | None
    ) -> ClassificationNode | None:
        """The level-`level` ancestor node of `symbol`'s as-of assignment, or None when no
        assignment applies or it does not reach that level."""
        row = self.assignment_as_of(symbol, scheme=scheme, as_of=as_of)
        if row is None:
            return None
        node = self._nodes.get((scheme, row.code))
        if node is None or node.level < level:
            return None
        return self._nodes.get((scheme, node.path[level - 1]))

    def max_level(self, scheme: str = DEFAULT_SCHEME) -> int:
        """Deepest level loaded for `scheme`; 0 if none."""
        levels = [node.level for (s, _), node in self._nodes.items() if s == scheme]
        return max(levels, default=0)
