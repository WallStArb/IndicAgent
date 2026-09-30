#!/usr/bin/env python3
"""Feature Lifecycle -- oneshot that governs concept_registry (domain='feature') status from
data quality (phase 186 plan 09, D-30; design 11).

DAG position:

    feature_vectors -> feature_lifecycle -> concept_evaluation, concept_registry

A governed feature (status active or shadow_only) is computed, valid and covered:

1. computed: at least one non-NULL value at some tf over the span;
2. valid: no NaN or infinite value at any tf;
3. covered: at each tf where it is populated, the share of symbols (with rows at that tf)
   carrying a value reaches feature.coverage.min_symbol_fraction.

The span is [window_end - lookback_days, window_end). The statistic is defined once in
src/intelligence/statistics/feature_coverage.py. Weak standalone IC never changes status
(design 11, E15: data that could contain signal stays computed).

One run evaluates one window and writes one concept_evaluation row per governed feature;
the primary key (concept, window, evidence_key) makes a rerun on identical evidence a
no-op. Status is derived from the ledger with derive_feature_transition (pure) and applied
through ConceptRegistryService.record_transition: active -> shadow_only after
demotion_min_consecutive failing windows (data_quality_fail), shadow_only -> active after
recovery_min_passes passing windows (data_quality_restored).

Usage:
    python services/feature_lifecycle.py --training-window-end 2025-12-24T05:15:00+00:00
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import hashlib
import json
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import fetch_table_columns, load_apr_dict_async  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.agent.base_batch import BaseBatch  # noqa: E402
from src.core.integrity_monitor import emit_integrity_facts_async  # noqa: E402
from src.core.service_utils import parse_training_window_end  # noqa: E402
from src.intelligence.concept_registry_service import (  # noqa: E402
    ConceptRegistryService,
    TransitionResult,
)
from src.intelligence.statistics.feature_coverage import (  # noqa: E402
    FeatureTfQuality,
    QualityVerdict,
    SymbolCounts,
    feature_quality_verdict,
    feature_tf_quality,
)
from src.observability.metrics import (  # noqa: E402
    FEATURE_LIFECYCLE_TRANSITIONS,
    FEATURE_QUALITY_FAILURES,
)
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402

_logger = structlog.get_logger()

_DOMAIN = "feature"
_GOVERNED_STATUSES = ("active", "shadow_only")

# Postgres caps a SELECT target list at 1664 entries; each feature takes two aggregates
# (populated count, non-finite count) plus symbol and total rows. An engine limit, not a
# tunable.
_MAX_FEATURES_PER_QUERY = 800

_FLOAT_TYPES = ("real", "double precision")

# concept_evaluation.evidence_kind of the rows this rule writes; the IC-era rows carry
# 'feature_ic' and are never evidence here.
_EVIDENCE_KIND = "data_quality"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleConfig:
    """APR snapshot: the four feature.* keys seeded by migration 387 and the infra key
    seeded by migration 389."""

    coverage_floor: float
    lookback_days: int
    demotion_min_consecutive: int
    recovery_min_passes: int
    # Timeframes measured at once; each holds one pool connection for aggregate queries over
    # the feature_vectors hypertable (BaseBatch's pool has ten). Cannot move a verdict.
    max_concurrent_tfs: int = 3

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> LifecycleConfig:
        return cls(
            coverage_floor=float(_cfg(cfg, "feature.coverage.min_symbol_fraction", 0.95)),
            lookback_days=int(_cfg(cfg, "feature.lifecycle.lookback_days", 90)),
            demotion_min_consecutive=int(
                _cfg(cfg, "feature.lifecycle.demotion_min_consecutive", 2)
            ),
            recovery_min_passes=int(_cfg(cfg, "feature.lifecycle.recovery_min_passes", 1)),
            max_concurrent_tfs=int(_cfg(cfg, "infra.feature_lifecycle.max_concurrent_tfs", 3)),
        )

    def rule_fingerprint(self) -> dict[str, Any]:
        """The decision-rule fields (RULE_FIELDS), so any rule change re-evaluates a window
        instead of colliding with its old row. Named explicitly: a field added to this class
        joins the fingerprint only by being listed, so an infra-only knob (INFRA_FIELDS)
        cannot leak in and re-evaluate every window when tuned."""
        return {name: getattr(self, name) for name in RULE_FIELDS}


# Decision-rule fields: what a verdict or a transition reads. Everything else on LifecycleConfig
# is infrastructure that cannot move a verdict. A test requires every field to sit in exactly
# one of the two tuples, so a new field must be classified.
RULE_FIELDS = (
    "coverage_floor",
    "lookback_days",
    "demotion_min_consecutive",
    "recovery_min_passes",
)
INFRA_FIELDS = ("max_concurrent_tfs",)


# ---------------------------------------------------------------------------
# Pure decision logic
# ---------------------------------------------------------------------------


def feature_evidence(
    per_tf: Sequence[FeatureTfQuality], verdict: QualityVerdict
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The sorted per-tf statistics a verdict read, and the ledger detail built from them."""
    rows = [
        {
            "tf": q.tf,
            "n_symbols_with_rows": q.n_symbols_with_rows,
            "n_symbols_populated": q.n_symbols_populated,
            "symbol_coverage": q.symbol_coverage,
            "non_null_share": q.non_null_share,
            "n_rows": q.n_rows,
            "n_non_finite": q.n_non_finite,
            "check": verdict.per_tf.get(q.tf),
        }
        for q in sorted(per_tf, key=lambda q: q.tf)
    ]
    return rows, {"failures": list(verdict.failures), "per_tf": rows}


def _canonical_json(obj: dict[str, Any]) -> str:
    """The evidence key's serialization: sorted keys, fixed separators, non-ASCII kept, and
    NaN or infinity refused (allow_nan=False raises ValueError), so a non-finite statistic
    fails loudly instead of hashing as a token. No default= hook: an unserializable value
    raises TypeError instead of being coerced to a string.

    Frozen by the ledger: every stored evidence_key is a hash of this output, so a change here
    moves keys. Version any change through a version field in the evidence_key payload."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def evidence_key(status: str, rule: dict[str, Any], per_tf_rows: list[dict[str, Any]]) -> str:
    """sha256 over everything a verdict read: the evaluated status, the decision-rule
    parameters and the canonical sorted per-tf statistics (see _canonical_json).

    Versioning rule: the serialization and the payload fields define the key. A change that
    could give an old row's evidence a different key needs a version field in the payload, so
    old and new keys never collide. No data_quality row existed when this serialization was
    fixed (migration 389 counted zero), so the payload carries none yet."""
    payload = _canonical_json({"status": status, "rule": rule, "per_tf": per_tf_rows})
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class Evaluation:
    """One concept_evaluation row, as derivation sees it."""

    window_end: datetime
    evaluated_status: str
    passed: bool
    n_observations: int
    evaluated_at: datetime
    statistic: float | None = None
    detail: dict[str, Any] | None = None


@dataclass(frozen=True)
class Transition:
    to_status: str
    reason: str
    evidence: Evaluation
    n_windows: int


def latest_per_window(evaluations: Iterable[Evaluation]) -> list[Evaluation]:
    """The latest evaluation of each window, ordered by window_end. A window counts once
    however many times it was re-evaluated, and its newest evidence supersedes the rest."""
    latest: dict[datetime, Evaluation] = {}
    for e in evaluations:
        kept = latest.get(e.window_end)
        if kept is None or e.evaluated_at > kept.evaluated_at:
            latest[e.window_end] = e
    return [latest[w] for w in sorted(latest)]


def _trailing_run(windows: Sequence[Evaluation], passed: bool) -> int:
    n = 0
    for e in reversed(windows):
        if e.passed != passed:
            break
        n += 1
    return n


def derive_feature_transition(
    current_status: str,
    status_since: datetime | None,
    evaluations: Iterable[Evaluation],
    config: LifecycleConfig,
    *,
    last_transition_reason: str | None = None,
) -> Transition | None:
    """Pure: the transition the ledger calls for, or None.

    Evidence counted: evaluations made under the current status since the concept entered
    it (a transition resets the evidence bar in both directions), latest per window.
    Streaks are trailing runs over those windows ordered by window_end.

    active -> shadow_only: the trailing failing streak reaches demotion_min_consecutive.
    shadow_only -> active: the trailing passing streak reaches recovery_min_passes, and only
    when the concept's most recent transition was this node's data_quality_fail demotion. A
    feature that is shadow_only for any other reason (seeded pending validation, performance
    demotion, operator decision) is never promoted by data quality, however good its coverage.
    """
    if current_status not in _GOVERNED_STATUSES:
        return None
    relevant = [
        e
        for e in evaluations
        if e.evaluated_status == current_status
        and (status_since is None or e.evaluated_at >= status_since)
    ]
    windows = latest_per_window(relevant)
    if not windows:
        return None
    if current_status == "active":
        fails = _trailing_run(windows, passed=False)
        if fails >= config.demotion_min_consecutive:
            return Transition("shadow_only", "data_quality_fail", windows[-1], fails)
        return None
    if last_transition_reason != "data_quality_fail":
        return None
    passes = _trailing_run(windows, passed=True)
    if passes >= config.recovery_min_passes:
        return Transition("active", "data_quality_restored", windows[-1], passes)
    return None


def quote_feature_column(name: str, known_columns: dict[str, str]) -> str:
    """A double-quoted identifier for a column that information_schema reported; anything
    else raises, so no concept name ever reaches SQL unchecked."""
    if name not in known_columns:
        raise ValueError(f"{name!r} is not a feature_vectors column")
    return '"' + name.replace('"', '""') + '"'


def build_tf_query(columns: Sequence[str], known_columns: dict[str, str]) -> str:
    """One aggregate query for one tf: per symbol, the total rows and, per feature column,
    the populated count (cN) and the NaN or infinite count (xN, float columns only)."""
    parts = ["symbol", "count(*) AS n_rows"]
    for i, name in enumerate(columns):
        col = quote_feature_column(name, known_columns)
        parts.append(f"count({col}) AS c{i}")
        float_type = known_columns[name]
        if float_type not in _FLOAT_TYPES:
            parts.append(f"0::bigint AS x{i}")
        else:
            parts.append(
                f"count(*) FILTER (WHERE {col} IN "
                f"('NaN'::{float_type}, 'Infinity'::{float_type}, '-Infinity'::{float_type})) "
                f"AS x{i}"
            )
    return (
        f"SELECT {', '.join(parts)} FROM feature_vectors "
        "WHERE tf = $1 AND bar_ts >= $2 AND bar_ts < $3 AND symbol IS NOT NULL GROUP BY symbol"
    )


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

# JOIN concept_gate: excludes migration 284's gate-less tombstone rows.
_CONCEPTS_SQL = """
    SELECT r.concept_id, r.name, r.status,
           (SELECT max(t.triggered_at) FROM concept_transition_log t
             WHERE t.concept_id = r.concept_id AND t.to_status = r.status) AS status_since,
           (SELECT t.trigger_reason FROM concept_transition_log t
             WHERE t.concept_id = r.concept_id
             ORDER BY t.triggered_at DESC LIMIT 1) AS last_transition_reason
    FROM concept_registry r
    JOIN concept_gate g USING (concept_id)
    WHERE r.domain = $1
"""

# Timeframes are discovered from the rows, not from the `timeframe` vocabulary: the vocabulary
# lists tfs with no feature_vectors rows (1m, 4h), and each would add an empty per-tf entry to
# every feature's evidence, n_cells and evidence_key; a tf present in the table but missing from
# the vocabulary would be dropped without a word. The index-only scan takes about 0.15 s.
_TFS_SQL = """
    SELECT DISTINCT tf FROM feature_vectors
    WHERE bar_ts >= $1 AND bar_ts < $2 AND tf IS NOT NULL
"""

# Re-seeing identical evidence refreshes evaluated_at, so it becomes the latest row for
# its window again (e.g. a rule changed and then changed back).
_UPSERT_EVALUATION_SQL = """
    INSERT INTO concept_evaluation
        (concept_id, domain, window_end, evidence_key, evaluated_status, passed, statistic,
         n_cells, n_observations, evidence_kind, detail, evaluated_at, run_ref)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
    ON CONFLICT (concept_id, window_end, evidence_key)
    DO UPDATE SET evaluated_at = EXCLUDED.evaluated_at, run_ref = EXCLUDED.run_ref
"""

# Only rows this rule wrote (evidence_kind): the IC-era rows share the table and the window
# keys but measured something else, so they are never evidence here.
#
# Derivation reads, per governed concept, the evaluations made under its current status since it
# entered it (derive_feature_transition's own filter), the latest of each window, and only the
# newest $5 windows: a trailing streak of at most max(demotion_min_consecutive,
# recovery_min_passes) windows decides a transition. $2, $3, $4 are the governed concepts'
# ids, statuses and status_since (NULL: no transition yet).
_LOAD_EVALUATIONS_SQL = """
    WITH latest AS (
        SELECT DISTINCT ON (e.concept_id, e.window_end)
               e.concept_id, e.window_end, e.evaluated_status, e.passed, e.n_observations,
               e.evaluated_at, e.statistic
        FROM concept_evaluation e
        JOIN unnest($2::uuid[], $3::text[], $4::timestamptz[])
             AS g(concept_id, status, status_since) ON g.concept_id = e.concept_id
        WHERE e.domain = $1
          AND e.evidence_kind = 'data_quality'
          AND e.evaluated_status = g.status
          AND (g.status_since IS NULL OR e.evaluated_at >= g.status_since)
        ORDER BY e.concept_id, e.window_end, e.evaluated_at DESC
    ), ranked AS (
        SELECT latest.*,
               row_number() OVER (PARTITION BY concept_id ORDER BY window_end DESC) AS recency
        FROM latest
    )
    SELECT concept_id, window_end, evaluated_status, passed, n_observations,
           evaluated_at, statistic
    FROM ranked
    WHERE recency <= $5
"""

# The whole history of the concepts whose transition streak may reach past the trailing windows
# above (its n_windows is the full streak length), read in one query for all of them.
_LOAD_CONCEPT_EVALUATIONS_SQL = """
    SELECT concept_id, window_end, evaluated_status, passed, n_observations,
           evaluated_at, statistic
    FROM concept_evaluation
    WHERE domain = $1
      AND concept_id = ANY($2)
      AND evidence_kind = 'data_quality'
"""


# ---------------------------------------------------------------------------
# Batch node
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerRow:
    """One concept_evaluation row this run writes (or would write, in a dry run)."""

    concept_id: Any
    name: str
    evidence_key: str
    evaluation: Evaluation
    n_cells: int  # tfs the verdict read: 0 for a concept with no feature_vectors column
    per_tf: tuple[FeatureTfQuality, ...]
    verdict: QualityVerdict


@dataclass(frozen=True)
class PlannedTransition:
    name: str
    from_status: str
    transition: Transition


@dataclass
class WindowPlan:
    """Everything one window's evaluation decides, computed without writing anything.
    A dry run stops at the plan; a real run persists it with _apply."""

    n_tfs: int
    rows: list[LedgerRow]
    transitions: list[PlannedTransition]

    @functools.cached_property
    def failures(self) -> list[tuple[LedgerRow, list[tuple[str | None, float | None, str]]]]:
        """Each failed row with its failing (tf, coverage, check) entries, computed once."""
        return [(r, _failing_tfs(r)) for r in self.rows if not r.verdict.passed]


def _failing_tfs(row: LedgerRow) -> list[tuple[str | None, float | None, str]]:
    """(tf, coverage, check) for each failing (feature, tf); a not_computed feature (no value
    at any tf, or no column) is one whole-feature entry with tf None."""
    if "not_computed" in row.verdict.failures:
        return [(None, 0.0, "not_computed")]
    return [
        (q.tf, q.symbol_coverage, row.verdict.per_tf[q.tf])
        for q in row.per_tf
        if row.verdict.per_tf.get(q.tf) in ("coverage", "non_finite")
    ]


def _quality_fact(
    row: LedgerRow, tf: str | None, coverage: float | None, check: str, coverage_floor: float
) -> tuple[str, float | None, float]:
    """(metric_name, value, threshold) for a failing check, so a failing fact never carries
    a value that satisfies its own threshold (a non_finite failure at full coverage reads
    n_non_finite against 0, not coverage 1.0 against the floor)."""
    if check == "non_finite":
        n_bad = sum(q.n_non_finite for q in row.per_tf if q.tf == tf)
        return "n_non_finite", float(n_bad), 0.0
    return "symbol_coverage", coverage, coverage_floor


def _evaluation_from_row(r: Any) -> Evaluation:
    return Evaluation(
        window_end=r["window_end"],
        evaluated_status=r["evaluated_status"],
        passed=r["passed"],
        n_observations=r["n_observations"],
        evaluated_at=r["evaluated_at"],
        statistic=r["statistic"],
    )


class FeatureLifecycle(BaseBatch):
    job_name = "feature-lifecycle"
    compute_version = "2.1.0"

    def __init__(self, db_dsn: str, training_window_end: datetime, dry_run: bool = False) -> None:
        super().__init__(db_dsn)
        self._window = training_window_end
        # dry_run: build the plan exactly as a real run, persist nothing, log it instead.
        self._dry_run = dry_run

    def _span_attrs(self) -> dict[str, Any]:
        return {"training_window_end": str(self._window), "dry_run": self._dry_run}

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        async with pool.acquire() as conn:
            config = LifecycleConfig.from_apr(
                await load_apr_dict_async(
                    conn,
                    extra_like_patterns=[
                        "feature.coverage.%",
                        "feature.lifecycle.%",
                        "infra.feature_lifecycle.%",
                    ],
                )
            )
            plan = await self._plan(conn, config)
            if plan is None:
                # No feature_vectors rows in the span: nothing is measured or written, so a
                # later run with data evaluates the window normally.
                self.logger.info("feature_lifecycle.no_data", training_window_end=str(self._window))
                return
            if self._dry_run:
                for p in plan.transitions:
                    self.logger.warning(
                        "feature_lifecycle.dry_run_transition",
                        feature=p.name,
                        from_status=p.from_status,
                        to_status=p.transition.to_status,
                        reason=p.transition.reason,
                        n_windows=p.transition.n_windows,
                    )
                n_applied = len(plan.transitions)
            else:
                n_applied = await self._apply(conn, plan, config)
            self.logger.info(
                "feature_lifecycle.window_evaluated",
                training_window_end=str(self._window),
                dry_run=self._dry_run,
                n_tfs=plan.n_tfs,
                n_evaluated=len(plan.rows),
                n_failed=len(plan.failures),
                n_transitions=n_applied,
                failures=self._failure_counts(plan),
            )

    # -- plan (reads only) ----------------------------------------------------

    async def _plan(self, conn: asyncpg.Connection, config: LifecycleConfig) -> WindowPlan | None:
        span_end = self._window
        span_start = span_end - timedelta(days=config.lookback_days)
        tfs = sorted(r["tf"] for r in await conn.fetch(_TFS_SQL, span_start, span_end))
        if not tfs:
            return None

        concepts = {r["name"]: dict(r) for r in await conn.fetch(_CONCEPTS_SQL, _DOMAIN)}
        governed = sorted(n for n, c in concepts.items() if c["status"] in _GOVERNED_STATUSES)
        # dtype from the schema, never inferred from rows
        known_columns = await fetch_table_columns(conn, "feature_vectors")
        computable = [n for n in governed if n in known_columns]

        per_feature: dict[str, list[FeatureTfQuality]] = defaultdict(list)
        for qualities in await self._measure_tfs(
            conn, tfs, computable, known_columns, span_start, span_end, config.max_concurrent_tfs
        ):
            for name in computable:
                per_feature[name].append(qualities[name])

        rows = self._plan_rows(governed, concepts, per_feature, tfs, config)

        transitions = await self._transitions(conn, concepts, governed, config, rows)
        return WindowPlan(len(tfs), rows, transitions)

    async def _transitions(
        self,
        conn: asyncpg.Connection,
        concepts: dict[str, dict],
        governed: Sequence[str],
        config: LifecycleConfig,
        rows: Sequence[LedgerRow],
    ) -> list[PlannedTransition]:
        """Derive over the ledger plus this window's rows (the newest evaluations), so a replay
        of any window takes effect.

        The ledger read is the newest `window_limit` windows per concept. That decides every
        transition (a streak of at most window_limit windows triggers one), but a transition's
        n_windows is the whole streak, so one that may reach past the loaded windows is
        re-derived from the concept's whole history: the result is what the whole ledger gives.
        """
        evaluations = await self._load_evaluations(conn, concepts, governed, config)
        for row in rows:
            evaluations[row.concept_id].append(row.evaluation)

        window_limit = max(config.demotion_min_consecutive, config.recovery_min_passes)
        first: dict[str, Any] = {}
        for name in governed:
            concept = concepts[name]
            first[name] = derive_feature_transition(
                concept["status"],
                concept["status_since"],
                evaluations.get(concept["concept_id"], []),
                config,
                last_transition_reason=concept["last_transition_reason"],
            )
        # One read of the whole history for every concept whose streak may exceed the window.
        long_streak = [
            concepts[name]["concept_id"]
            for name, t in first.items()
            if t is not None and t.n_windows >= window_limit
        ]
        histories = await self._load_concept_histories(conn, long_streak) if long_streak else {}
        transitions = []
        for name in governed:
            concept = concepts[name]
            transition = first[name]
            if concept["concept_id"] in histories:
                transition = derive_feature_transition(
                    concept["status"],
                    concept["status_since"],
                    [
                        *histories[concept["concept_id"]],
                        *(r.evaluation for r in rows if r.concept_id == concept["concept_id"]),
                    ],
                    config,
                    last_transition_reason=concept["last_transition_reason"],
                )
            if transition is not None:
                transitions.append(PlannedTransition(name, concept["status"], transition))
        return transitions

    async def _measure_tfs(
        self,
        conn: asyncpg.Connection,
        tfs: Sequence[str],
        computable: Sequence[str],
        known_columns: dict[str, str],
        span_start: datetime,
        span_end: datetime,
        max_concurrent_tfs: int,
    ) -> list[dict[str, FeatureTfQuality]]:
        """Per tf (in `tfs` order), each computable feature's quality. Over a pool the tfs are
        measured concurrently, at most max_concurrent_tfs at a time, each on its own
        connection; without one (a caller that holds only `conn`) they run in turn on it."""
        gate = asyncio.Semaphore(max_concurrent_tfs)

        async def measure(tf: str) -> dict[str, FeatureTfQuality]:
            async with gate:
                if self._pool is None:
                    return await self._measure_tf(
                        conn, tf, computable, known_columns, span_start, span_end
                    )
                async with self._pool.acquire() as tf_conn:
                    return await self._measure_tf(
                        tf_conn, tf, computable, known_columns, span_start, span_end
                    )

        if self._pool is None:
            return [await measure(tf) for tf in tfs]
        return list(await asyncio.gather(*(measure(tf) for tf in tfs)))

    async def _measure_tf(
        self,
        conn: asyncpg.Connection,
        tf: str,
        computable: Sequence[str],
        known_columns: dict[str, str],
        span_start: datetime,
        span_end: datetime,
    ) -> dict[str, FeatureTfQuality]:
        started = time.monotonic()
        counts: dict[str, list[SymbolCounts]] = defaultdict(list)
        for start in range(0, len(computable), _MAX_FEATURES_PER_QUERY):
            chunk = computable[start : start + _MAX_FEATURES_PER_QUERY]
            sql = build_tf_query(chunk, known_columns)
            for row in await conn.fetch(sql, tf, span_start, span_end):
                # columns by position: symbol, n_rows, then (populated, non-finite) per feature
                symbol, n_rows, *pairs = tuple(row.values())
                for i, name in enumerate(chunk):
                    counts[name].append(
                        SymbolCounts(symbol, n_rows, pairs[2 * i], pairs[2 * i + 1])
                    )
        self.logger.info(
            "feature_lifecycle.tf_measured",
            tf=tf,
            n_features=len(computable),
            seconds=round(time.monotonic() - started, 2),
        )
        return {name: feature_tf_quality(name, tf, counts[name]) for name in computable}

    async def _load_evaluations(
        self,
        conn: asyncpg.Connection,
        concepts: dict[str, dict],
        governed: Sequence[str],
        config: LifecycleConfig,
    ) -> dict[Any, list[Evaluation]]:
        """The evaluations derivation can read, per concept: see _LOAD_EVALUATIONS_SQL."""
        chosen = [concepts[name] for name in governed]
        rows = await conn.fetch(
            _LOAD_EVALUATIONS_SQL,
            _DOMAIN,
            [c["concept_id"] for c in chosen],
            [c["status"] for c in chosen],
            [c["status_since"] for c in chosen],
            max(config.demotion_min_consecutive, config.recovery_min_passes),
        )
        evaluations: dict[Any, list[Evaluation]] = defaultdict(list)
        for r in rows:
            evaluations[r["concept_id"]].append(_evaluation_from_row(r))
        return evaluations

    async def _load_concept_histories(
        self, conn: asyncpg.Connection, concept_ids: Sequence[Any]
    ) -> dict[Any, list[Evaluation]]:
        """Each concept's whole data_quality history, in one query."""
        rows = await conn.fetch(_LOAD_CONCEPT_EVALUATIONS_SQL, _DOMAIN, list(concept_ids))
        histories: dict[Any, list[Evaluation]] = {cid: [] for cid in concept_ids}
        for r in rows:
            histories[r["concept_id"]].append(_evaluation_from_row(r))
        return histories

    def _plan_rows(
        self,
        governed: Sequence[str],
        concepts: dict[str, dict],
        per_feature: dict[str, list[FeatureTfQuality]],
        tfs: Sequence[str],
        config: LifecycleConfig,
    ) -> list[LedgerRow]:
        """One ledger row per governed feature; a concept with no feature_vectors column has
        no per-tf results and so fails not_computed."""
        rule = config.rule_fingerprint()
        now = datetime.now(UTC)
        rows = []
        for name in governed:
            concept = concepts[name]
            per_tf = tuple(per_feature.get(name, ()))
            verdict = feature_quality_verdict(per_tf, config.coverage_floor)
            per_tf_rows, detail = feature_evidence(per_tf, verdict)
            rows.append(
                LedgerRow(
                    concept_id=concept["concept_id"],
                    name=name,
                    evidence_key=evidence_key(concept["status"], rule, per_tf_rows),
                    evaluation=Evaluation(
                        window_end=self._window,
                        evaluated_status=concept["status"],
                        passed=verdict.passed,
                        n_observations=sum(q.n_rows for q in per_tf),
                        evaluated_at=now,
                        statistic=verdict.statistic,
                        detail=detail,
                    ),
                    n_cells=len(per_tf),
                    per_tf=per_tf,
                    verdict=verdict,
                )
            )
        return rows

    # -- apply (writes + metrics) ---------------------------------------------

    async def _apply(
        self, conn: asyncpg.Connection, plan: WindowPlan, config: LifecycleConfig
    ) -> int:
        """Persist a plan: quality facts, ledger rows, transitions, metrics. Returns the
        number of transitions applied."""
        n_failed = len(plan.failures)
        facts = []
        for r, failing in plan.failures:
            for tf, coverage, check in failing:
                FEATURE_QUALITY_FAILURES.add(
                    1, {"check": check} if tf is None else {"tf": tf, "check": check}
                )
                facts.append(
                    (
                        "feature_quality",
                        r.name if tf is None else f"{r.name}|tf={tf}",
                        *_quality_fact(r, tf, coverage, check, config.coverage_floor),
                        False,
                        self._window,
                    )
                )
        facts.append(
            (
                "feature_quality",
                None,
                "n_features_failed",
                float(n_failed),
                0.0,
                n_failed == 0,
                self._window,
            )
        )
        await emit_integrity_facts_async(conn, facts)
        run_ref = f"feature_lifecycle:{datetime.now(UTC).isoformat()}"
        await conn.executemany(
            _UPSERT_EVALUATION_SQL,
            [
                (
                    r.concept_id,
                    _DOMAIN,
                    r.evaluation.window_end,
                    r.evidence_key,
                    r.evaluation.evaluated_status,
                    r.evaluation.passed,
                    r.evaluation.statistic,
                    r.n_cells,
                    r.evaluation.n_observations,
                    _EVIDENCE_KIND,
                    r.evaluation.detail,
                    r.evaluation.evaluated_at,
                    run_ref,
                )
                for r in plan.rows
            ],
        )

        registry = ConceptRegistryService()
        n_applied = 0
        for p in plan.transitions:
            t = p.transition
            result = await registry.record_transition(
                conn,
                domain=_DOMAIN,
                name=p.name,
                from_status=p.from_status,
                to_status=t.to_status,
                reason=t.reason,
                gate_metric=t.evidence.statistic,
                gate_n=float(t.evidence.n_observations),
                corpus_build_ref=str(t.evidence.window_end),
                fdr_passed=None,
                notes=f"{t.n_windows} consecutive windows (feature_lifecycle)",
            )
            if result is TransitionResult.APPLIED:
                n_applied += 1
                FEATURE_LIFECYCLE_TRANSITIONS.add(1, {"to_status": t.to_status, "reason": t.reason})
        return n_applied

    @staticmethod
    def _failure_counts(plan: WindowPlan) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for _, failing in plan.failures:
            for tf, _, check in failing:
                counts[check if tf is None else f"{check}|tf={tf}"] += 1
        return dict(sorted(counts.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Feature Lifecycle -- data-quality feature governance"
    )
    parser.add_argument(
        "--training-window-end",
        required=True,
        help="Window to evaluate; the span ends here (ISO-8601, UTC).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the plan but write nothing; log the transitions a real run would make.",
    )
    args = parser.parse_args()

    try:
        init_otel_providers("indicagent-feature-lifecycle")
    except OTelInitError as error:
        _logger.warning("feature_lifecycle.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(
        FeatureLifecycle(
            db_dsn=db_dsn,
            training_window_end=parse_training_window_end(args.training_window_end),
            dry_run=args.dry_run,
        ).run()
    )
