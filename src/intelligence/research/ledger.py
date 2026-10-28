"""S6 ledger: the sole writer of research run records and construction identity rows.

This module is the only code that writes `research_run` rows (migration 366), rows of
`concept_registry` in the research domains (family, member, combiner, construction_rule, book;
migration 530), their `concept_recipe` versions, and the `concept_parent` edges between them
(phase 183, D-05; enforced by tests/unit/research/test_ledger_sole_writer.py).

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from src.core.database_manager import connect_with_codecs
from src.intelligence.research.recipe import RecipeContent

# Fixed advisory-lock key covering research_run, construction identity rows and their
# concept_parent edges. A schema identifier, APR-exempt.
LEDGER_LOCK_KEY: int = 183366

TERMINAL_STATUSES: tuple[str, ...] = ("completed", "guard_failed", "refused", "failed")
UNCHARGED_STATUSES: tuple[str, ...] = ("refused", "guard_failed")

# A run that computed a statistic counts even when it then failed (design 7.1).
SERIES_STATUSES: tuple[str, ...] = ("completed", "failed")

# Typed research domains (migration 530). A pod is a book; its metadata kind says pod.
_RESEARCH_DOMAINS = ("family", "member", "combiner", "construction_rule", "book")
_ADDED_PHASE = "183"


class LedgerRefusal(Exception):
    """A run the ledger will not start: a prior real run exists for the spec hash (D-02),
    or the vintage's book-test budget is exhausted (D-08)."""


@dataclass(frozen=True)
class Identity:
    """A research-domain concept_registry row. `parents` are identity names; edges run
    child -> parent in concept_parent. A pod lands in the book domain."""

    name: str
    kind: Literal["family", "member", "combiner", "construction_rule", "book", "pod"]
    description: str
    metadata: dict = field(default_factory=dict)
    parents: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunRequest:
    kind: Literal["evidence", "book_test", "pod_book"]
    spec_path: str
    spec_hash: str
    spec_blob: str
    code_commit: str
    vintage: str
    budget_m: int | None = None
    screen_alpha: float | None = None
    # E18 (phase 187): exploration is counted like any real-data attempt but may repeat a spec.
    mode: Literal["real", "exploration"] = "real"
    # Plan 187-11: the recipe of each concept the run touches (written as a new version when its
    # hash is new), the attempt that prompted this one, and the author the recipe records.
    recipes: Mapping[str, RecipeContent] = field(default_factory=dict)
    informed_by: str | None = None
    author: str | None = None


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


@dataclass(frozen=True)
class PinnedRun:
    """A recorded attempt read by run_id, as a pod pins it (plan 187-10)."""

    run_id: str
    kind: str
    status: str
    spec_hash: str
    vintage: str
    evidence: dict
    series: AttemptSeries | None  # None when no series was stored


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


def _domain_of(kind: str) -> str:
    return "book" if kind == "pod" else kind


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

    async def pinned_run(self, run_id: str) -> PinnedRun | None:
        """The attempt `run_id` with its stored series, or None when no such run exists."""
        conn = await connect_with_codecs(self._dsn)
        try:
            row = await conn.fetchrow(
                "SELECT r.run_id::text AS run_id, r.kind, r.status, r.spec_hash, r.vintage, "
                "r.evidence, s.sessions, s.d_s FROM research_run r "
                "LEFT JOIN research_run_series s USING (run_id) WHERE r.run_id = $1",
                uuid.UUID(run_id),
            )
        finally:
            await conn.close()
        if row is None:
            return None
        series = None
        if row["sessions"] is not None:
            series = AttemptSeries(
                sessions=np.array(row["sessions"], dtype="datetime64[D]"),
                values=np.array(row["d_s"], dtype=np.float64),
            )
        return PinnedRun(
            row["run_id"],
            row["kind"],
            row["status"],
            row["spec_hash"],
            row["vintage"],
            row["evidence"] or {},
            series,
        )

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
                await self._check_recipes(conn, request, identities, run_concepts)

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
                        "VALUES ($5, $1, $2, 'candidate', false, $3, $4) "
                        "ON CONFLICT (domain, name) DO NOTHING",
                        identity.name,
                        identity.description,
                        jsonable(metadata),
                        _ADDED_PHASE,
                        _domain_of(identity.kind),
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

                recipe_hashes = await self._write_recipes(conn, request, concept_ids)

                run_group = uuid.uuid4()
                run_ids: dict[str, str] = {}
                for name in run_concepts:
                    concept_id = concept_ids.get(name)
                    if concept_id is None:
                        concept_id = await self._concept_id(conn, name)
                    run_id = await conn.fetchval(
                        "INSERT INTO research_run (run_group, concept_id, kind, mode, "
                        "spec_path, spec_hash, spec_blob, code_commit, vintage, budget_m, "
                        "screen_alpha, recipe_hash, informed_by) "
                        "VALUES ($1, $2, $3, $11, $4, $5, $6, $7, $8, $9, $10, $12, $13) "
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
                        recipe_hashes.get(name),
                        None if request.informed_by is None else uuid.UUID(request.informed_by),
                    )
                    run_ids[name] = str(run_id)
                return run_ids
        finally:
            await conn.close()

    @staticmethod
    async def _check_recipes(
        conn: Any, request: RunRequest, identities: Sequence[Identity], run_concepts: Sequence[str]
    ) -> None:
        """Every refusal about a recipe or the informing attempt, before anything is written."""
        named = {i.name for i in identities}
        for name in request.recipes:
            if name not in named:
                raise LedgerRefusal(f"recipe for {name}, which is not an identity of this run")
        for name in run_concepts:
            if request.recipes and name not in request.recipes:
                raise LedgerRefusal(f"run concept {name} has no recipe")
        await PostgresLedger._check_cvr_codes(conn, request.recipes)
        if request.informed_by is not None:
            try:
                informing = uuid.UUID(request.informed_by)
            except ValueError as error:
                raise LedgerRefusal(
                    f"informed_by {request.informed_by!r} is not a run id"
                ) from error
            status = await conn.fetchval(
                "SELECT status FROM research_run WHERE run_id = $1", informing
            )
            if status not in TERMINAL_STATUSES:
                raise LedgerRefusal(
                    f"informed_by {request.informed_by} is not a terminal research_run"
                )

    @staticmethod
    async def _check_cvr_codes(conn: Any, recipes: Mapping[str, RecipeContent]) -> None:
        codes = {(ns, code) for r in recipes.values() for ns, code in r.cvr_codes.items()}
        if not codes:
            return
        known = {
            (r["namespace"], r["code"])
            for r in await conn.fetch(
                "SELECT namespace, code FROM controlled_vocabulary "
                "WHERE namespace = ANY($1::text[]) AND NOT is_deprecated",
                sorted({ns for ns, _ in codes}),
            )
        }
        unknown = sorted(codes - known)
        if unknown:
            raise LedgerRefusal(f"controlled-vocabulary codes not registered: {unknown}")

    @staticmethod
    async def _write_recipes(
        conn: Any, request: RunRequest, concept_ids: Mapping[str, Any]
    ) -> dict[str, str]:
        return await PostgresLedger._insert_recipes(
            conn, request.recipes, concept_ids, request.code_commit, request.author or "unknown"
        )

    @staticmethod
    async def _insert_recipes(
        conn: Any,
        recipes: Mapping[str, RecipeContent],
        concept_ids: Mapping[str, Any],
        code_commit: str,
        author: str,
    ) -> dict[str, str]:
        """Insert a recipe version for each concept whose recipe hash is new; return
        {concept name: recipe hash}. A known hash is reused, so a re-run of the same definition
        at a new commit adds no version (concept_recipe.code_commit is the commit that first
        recorded it; research_run.code_commit is the code behind each attempt)."""
        hashes: dict[str, str] = {}
        for name, recipe in recipes.items():
            concept_id = concept_ids[name]
            digest = recipe.recipe_hash
            hashes[name] = digest
            if await conn.fetchval("SELECT 1 FROM concept_recipe WHERE recipe_hash = $1", digest):
                continue
            version = await conn.fetchval(
                "SELECT coalesce(max(version), 0) + 1 FROM concept_recipe WHERE concept_id = $1",
                concept_id,
            )
            await conn.execute(
                "INSERT INTO concept_recipe (concept_id, version, recipe_hash, code_pointer, "
                "code_commit, params, apr_values, inputs, universe_selector, cvr_codes, "
                "mechanism, sources, author) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
                concept_id,
                version,
                digest,
                recipe.code_pointer,
                code_commit,
                jsonable(recipe.params),
                jsonable(recipe.apr_values),
                jsonable(list(recipe.inputs)),
                jsonable(recipe.universe_selector),
                jsonable(recipe.cvr_codes),
                recipe.mechanism,
                list(recipe.sources),
                author,
            )
        return hashes

    @staticmethod
    async def _concept_id(conn: Any, name: str) -> Any:
        concept_id = await conn.fetchval(
            "SELECT concept_id FROM concept_registry WHERE domain = ANY($1::text[]) AND name = $2",
            list(_RESEARCH_DOMAINS),
            name,
        )
        if concept_id is None:
            raise LedgerRefusal(f"unknown construction identity: {name}")
        return concept_id

    async def seed_recipes(
        self,
        domain: str,
        recipes: Mapping[str, RecipeContent],
        *,
        code_commit: str,
        author: str,
    ) -> dict[str, str]:
        """Write a recipe version for concepts registered outside a run (the HMM feature columns,
        187-12): the same insert as a run's, under the same lock, for existing concept_registry
        rows of `domain`. Refuses an unregistered concept or CVR code before any write. Returns
        {concept name: recipe hash}."""
        conn = await connect_with_codecs(self._dsn)
        try:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", LEDGER_LOCK_KEY)
                await self._check_cvr_codes(conn, recipes)
                concept_ids: dict[str, Any] = {}
                for name in recipes:
                    concept_id = await conn.fetchval(
                        "SELECT concept_id FROM concept_registry WHERE domain = $1 AND name = $2",
                        domain,
                        name,
                    )
                    if concept_id is None:
                        raise LedgerRefusal(f"recipe for unregistered {domain} concept: {name}")
                    concept_ids[name] = concept_id
                return await self._insert_recipes(conn, recipes, concept_ids, code_commit, author)
        finally:
            await conn.close()

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
