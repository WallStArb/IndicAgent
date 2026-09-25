"""S6 ledger: the sole writer of research run records and construction identity rows.

This module is the only code that writes `research_run` rows (migration 366), rows of
`concept_registry` with `domain = 'construction'`, and the `concept_parent` edges between
them (phase 183, D-05; enforced by tests/unit/research/test_ledger_sole_writer.py).

Writer contract (migrations 283 and 366): every write transaction here takes
`pg_advisory_xact_lock(LEDGER_LOCK_KEY)` as its first statement, then counts and inserts in
the same transaction. That makes the spec-once check (D-02) and the vintage budget count
(D-08) race-free between concurrent runners, and satisfies concept_parent's cycle-guard
contract for a non-seed writer.

This module never updates `concept_registry.status`: identity rows are inserted as
`candidate` and left alone (UCR Invariant 1, only ConceptRegistryService flips status).

The database enforces the append-only rules itself (migration 366 triggers): a row is
inserted as `started`, moves exactly once to a terminal status, and is never deleted. Budget
parameters (M, alpha) always come from the RunRequest; the runner reads them from APR.

Every connection comes from `connect_with_codecs`, so jsonb columns round-trip as dicts. Each
method opens its own connection and closes it, so a long run never holds an idle one.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from src.core.database_manager import connect_with_codecs

# Fixed advisory-lock key covering research_run, construction identity rows and their
# concept_parent edges. A schema identifier, APR-exempt.
LEDGER_LOCK_KEY: int = 183366

TERMINAL_STATUSES: tuple[str, ...] = ("completed", "guard_failed", "refused", "failed")
UNCHARGED_STATUSES: tuple[str, ...] = ("refused", "guard_failed")

_DOMAIN = "construction"
_ADDED_PHASE = "183"


class LedgerRefusal(Exception):
    """A run the ledger will not start: a prior real run exists for the spec hash (D-02),
    or the vintage's book-test budget is exhausted (D-08)."""


@dataclass(frozen=True)
class Identity:
    """A construction-domain concept_registry row. `parents` are identity names; edges run
    child -> parent in concept_parent."""

    name: str
    kind: Literal["family", "member", "book_version"]
    description: str
    metadata: dict = field(default_factory=dict)
    parents: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunRequest:
    kind: Literal["evidence", "book_test"]
    spec_path: str
    spec_hash: str
    spec_blob: str
    code_commit: str
    vintage: str
    budget_m: int | None = None
    screen_alpha: float | None = None


def jsonable(value: Any) -> Any:
    """Convert `value` to strict-JSON-safe Python: numpy scalars to Python scalars, numpy
    arrays via tolist, NaN and +-inf to None, tuples to lists, dict keys to str. Raises
    TypeError on any other non-JSON type (183-RESEARCH pitfall 8)."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        as_float = float(value)
        return as_float if math.isfinite(as_float) else None
    if isinstance(value, np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    raise TypeError(f"not JSON-serializable: {type(value).__name__}")


class PostgresLedger:
    """Ledger over the live (or test) database at `dsn`."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def has_real_run(self, spec_hash: str) -> bool:
        conn = await connect_with_codecs(self._dsn)
        try:
            return bool(
                await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM research_run "
                    "WHERE spec_hash = $1 AND mode = 'real')",
                    spec_hash,
                )
            )
        finally:
            await conn.close()

    async def charged_book_tests(self, vintage: str) -> int:
        conn = await connect_with_codecs(self._dsn)
        try:
            return await self._count_charged(conn, vintage)
        finally:
            await conn.close()

    @staticmethod
    async def _count_charged(conn: Any, vintage: str) -> int:
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM research_run "
                "WHERE kind = 'book_test' AND vintage = $1 AND NOT (status = ANY($2::text[]))",
                vintage,
                list(UNCHARGED_STATUSES),
            )
        )

    async def start_runs(
        self,
        request: RunRequest,
        identities: Sequence[Identity],
        run_concepts: Sequence[str],
    ) -> dict[str, str]:
        """Write identity rows, lineage edges and one `started` research_run row per name in
        `run_concepts`, all sharing one new run_group, in one locked transaction. Returns
        {concept name: run_id}. Raises LedgerRefusal on a prior real run for the spec hash or
        an exhausted book-test budget."""
        if request.kind == "book_test" and (
            request.budget_m is None or request.screen_alpha is None
        ):
            raise ValueError("a book_test run needs budget_m and screen_alpha")
        if not run_concepts:
            raise ValueError("start_runs needs at least one run concept")

        conn = await connect_with_codecs(self._dsn)
        try:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", LEDGER_LOCK_KEY)

                prior = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM research_run "
                    "WHERE spec_hash = $1 AND mode = 'real')",
                    request.spec_hash,
                )
                if prior:
                    raise LedgerRefusal(f"spec already run: {request.spec_hash}")

                if request.kind == "book_test":
                    charged = await self._count_charged(conn, request.vintage)
                    if charged >= request.budget_m:
                        raise LedgerRefusal(
                            f"budget exhausted for vintage {request.vintage}: "
                            f"{charged} of {request.budget_m} book tests charged"
                        )

                concept_ids: dict[str, Any] = {}
                for identity in identities:
                    metadata = {**identity.metadata, "kind": identity.kind}
                    await conn.execute(
                        "INSERT INTO concept_registry "
                        "(domain, name, description, status, enabled, metadata, added_phase) "
                        "VALUES ('construction', $1, $2, 'candidate', false, $3, $4) "
                        "ON CONFLICT (domain, name) DO NOTHING",
                        identity.name,
                        identity.description,
                        jsonable(metadata),
                        _ADDED_PHASE,
                    )
                    concept_ids[identity.name] = await self._concept_id(conn, identity.name)

                for identity in identities:
                    for parent in identity.parents:
                        parent_id = concept_ids.get(parent)
                        if parent_id is None:
                            parent_id = await self._concept_id(conn, parent)
                        await conn.execute(
                            "INSERT INTO concept_parent (child_concept_id, parent_concept_id) "
                            "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                            concept_ids[identity.name],
                            parent_id,
                        )

                run_group = uuid.uuid4()
                run_ids: dict[str, str] = {}
                for name in run_concepts:
                    concept_id = concept_ids.get(name)
                    if concept_id is None:
                        concept_id = await self._concept_id(conn, name)
                    run_id = await conn.fetchval(
                        "INSERT INTO research_run (run_group, concept_id, kind, mode, "
                        "spec_path, spec_hash, spec_blob, code_commit, vintage, budget_m, "
                        "screen_alpha) "
                        "VALUES ($1, $2, $3, 'real', $4, $5, $6, $7, $8, $9, $10) "
                        "RETURNING run_id",
                        run_group,
                        concept_id,
                        request.kind,
                        request.spec_path,
                        request.spec_hash,
                        request.spec_blob,
                        request.code_commit,
                        request.vintage,
                        request.budget_m,
                        request.screen_alpha,
                    )
                    run_ids[name] = str(run_id)
                return run_ids
        finally:
            await conn.close()

    @staticmethod
    async def _concept_id(conn: Any, name: str) -> Any:
        concept_id = await conn.fetchval(
            "SELECT concept_id FROM concept_registry WHERE domain = $1 AND name = $2",
            _DOMAIN,
            name,
        )
        if concept_id is None:
            raise LedgerRefusal(f"unknown construction identity: {name}")
        return concept_id

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        snapshot_hash: str | None,
        evidence: dict,
    ) -> None:
        """Move a started run to its terminal status, once. Evidence is converted and
        serialized strictly before the write; if that fails, the row is written as 'failed'
        with the error and the error re-raised, so no row stays started because the final
        write crashed (pitfall 8)."""
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"not a terminal status: {status}")

        serialization_error: Exception | None = None
        try:
            payload = jsonable(evidence)
            json.dumps(payload, allow_nan=False)
        except (TypeError, ValueError) as error:
            serialization_error = error
            status = "failed"
            payload = {"error": f"evidence not serializable: {error}"}

        conn = await connect_with_codecs(self._dsn)
        try:
            result = await conn.execute(
                "UPDATE research_run SET status = $2, snapshot_hash = $3, evidence = $4, "
                "finished_at = now() WHERE run_id = $1",
                uuid.UUID(run_id),
                status,
                snapshot_hash,
                payload,
            )
        finally:
            await conn.close()
        if result != "UPDATE 1":
            raise LookupError(f"research_run {run_id} not found")

        if serialization_error is not None:
            raise serialization_error
