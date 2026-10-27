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

# A run that computed a statistic counts even when it then failed (design 7.1).
SERIES_STATUSES: tuple[str, ...] = ("completed", "failed")

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
    # E18 (phase 187): exploration is counted like any real-data attempt but may repeat a spec.
    mode: Literal["real", "exploration"] = "real"


@dataclass(frozen=True)
class AttemptSeries:
    """An attempt's tested sessions and their E17 D_s (finite only, session order)."""

    sessions: np.ndarray  # datetime64[D]
    values: np.ndarray  # float64

    @classmethod
    def from_timing(cls, sessions: np.ndarray, d_s: np.ndarray) -> AttemptSeries | None:
        """Keep the tested sessions (finite D_s); None when no session was tested."""
        tested = np.isfinite(d_s)
        if not tested.any():
            return None
        return cls(
            sessions=np.asarray(sessions, dtype="datetime64[D]")[tested],
            values=np.asarray(d_s, dtype=np.float64)[tested],
        )

    def sessions_as_dates(self) -> list:
        return self.sessions.astype(object).tolist()


def _headline(payload: dict, series: AttemptSeries | None) -> tuple:
    """(t, p, gross Sharpe, mean session P&L, turnover, n sessions, span start, span end)."""
    decision = payload.get("decision") or {}

    def num(value: Any) -> float | None:
        return None if value is None else float(value)

    span = (None, None) if series is None else tuple(series.sessions_as_dates()[i] for i in (0, -1))
    n = decision.get("n_sessions")
    return (
        num(decision.get("t")),
        num(decision.get("p")),
        num(decision.get("annualized_sharpe")),
        num(decision.get("mean_session_pnl")),
        num(payload.get("turnover_per_session")),
        None if n is None else int(n),
        *span,
    )


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
        """Whether the spec has any real-data run, real or exploration: a spec searched in
        exploration cannot then take its one real run as if it were unlooked."""
        conn = await connect_with_codecs(self._dsn)
        try:
            return bool(
                await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM research_run " "WHERE spec_hash = $1)",
                    spec_hash,
                )
            )
        finally:
            await conn.close()

    async def charged_book_tests(self, vintage: str) -> int:
        conn = await connect_with_codecs(self._dsn)
        try:
            return int(
                await conn.fetchval(
                    "SELECT count(*) FROM research_run "
                    "WHERE kind = 'book_test' AND vintage = $1 AND NOT (status = ANY($2::text[]))",
                    vintage,
                    list(UNCHARGED_STATUSES),
                )
            )
        finally:
            await conn.close()

    async def start_runs(
        self,
        request: RunRequest,
        identities: Sequence[Identity],
        run_concepts: Sequence[str],
    ) -> dict[str, str]:
        """Write identity rows, lineage edges and one `started` research_run row per name in
        `run_concepts`, all sharing one new run_group, in one locked transaction. Returns
        {concept name: run_id}. Raises LedgerRefusal on a prior real-data run (real or exploration)
        of the spec hash, in real mode only. Since E18 the book-test budget no longer refuses: every attempt is recorded
        and selection prices them all (StepM, design 7.3); budget_m stays on book_test rows as
        the power bar's M and as disclosure."""
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

                if request.mode == "real":
                    prior = await conn.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM research_run " "WHERE spec_hash = $1)",
                        request.spec_hash,
                    )
                    if prior:
                        raise LedgerRefusal(f"spec already run: {request.spec_hash}")

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
                        "VALUES ($1, $2, $3, $11, $4, $5, $6, $7, $8, $9, $10) "
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
                        request.mode,
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

    async def backfill_series(self, run_id: str, series: AttemptSeries) -> None:
        """Write the series of a run recorded before migration 515 (phase 187 plan 03). Only the
        series table is written: the run row is terminal and stays as recorded, so its headline
        columns stay NULL. The caller proves the replay reproduced the recorded decision."""
        conn = await connect_with_codecs(self._dsn)
        try:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", LEDGER_LOCK_KEY)
                await conn.execute(
                    "INSERT INTO research_run_series (run_id, sessions, d_s) VALUES ($1, $2, $3)",
                    uuid.UUID(run_id),
                    series.sessions_as_dates(),
                    series.values.tolist(),
                )
        finally:
            await conn.close()

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        snapshot_hash: str | None,
        evidence: dict,
        series: AttemptSeries | None = None,
    ) -> None:
        """Move a started run to its terminal status, once. Evidence is converted and
        serialized strictly before the write; if that fails, the row is written as 'failed'
        with the error and the error re-raised, so no row stays started because the final
        write crashed (pitfall 8).

        The headline numbers come from the evidence's decision block. A completed or failed
        run that carries its D_s series writes it to research_run_series in the same
        transaction (migration 515): the series is the attempt's entry in the StepM selection
        universe (E18), so it is never written apart from the terminal row."""
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

        headline = _headline(payload, series)
        conn = await connect_with_codecs(self._dsn)
        try:
            async with conn.transaction():
                result = await conn.execute(
                    "UPDATE research_run SET status = $2, snapshot_hash = $3, evidence = $4, "
                    "finished_at = now(), decision_t = $5, decision_p = $6, gross_sharpe = $7, "
                    "mean_session_pnl = $8, turnover_per_session = $9, n_sessions = $10, "
                    "span_start = $11, span_end = $12 WHERE run_id = $1",
                    uuid.UUID(run_id),
                    status,
                    snapshot_hash,
                    payload,
                    *headline,
                )
                if result == "UPDATE 1" and series is not None and status in SERIES_STATUSES:
                    await conn.execute(
                        "INSERT INTO research_run_series (run_id, sessions, d_s) "
                        "VALUES ($1, $2, $3)",
                        uuid.UUID(run_id),
                        series.sessions_as_dates(),
                        series.values.tolist(),
                    )
        finally:
            await conn.close()
        if result != "UPDATE 1":
            raise LookupError(f"research_run {run_id} not found")

        if serialization_error is not None:
            raise serialization_error
