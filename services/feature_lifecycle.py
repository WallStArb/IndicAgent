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
import dataclasses
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
from services._batch_utils import load_apr_dict_async  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.agent.base_batch import BaseBatch  # noqa: E402
from src.core.integrity_monitor import emit_integrity_fact_async  # noqa: E402
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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleConfig:
    """APR snapshot: the four feature.* keys seeded by migration 387."""

    coverage_floor: float
    lookback_days: int
    demotion_min_consecutive: int
    recovery_min_passes: int

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> LifecycleConfig:
        return cls(
            coverage_floor=float(_cfg(cfg, "feature.coverage.min_symbol_fraction", 0.95)),
            lookback_days=int(_cfg(cfg, "feature.lifecycle.lookback_days", 90)),
            demotion_min_consecutive=int(
                _cfg(cfg, "feature.lifecycle.demotion_min_consecutive", 2)
            ),
            recovery_min_passes=int(_cfg(cfg, "feature.lifecycle.recovery_min_passes", 1)),
        )

    def rule_fingerprint(self) -> dict[str, Any]:
        """Every config field, so any rule change re-evaluates a window instead of colliding
        with its old row. Over-inclusive on purpose: a field that cannot move a verdict
        only adds a row with the same verdict, never a missed re-evaluation."""
        return dataclasses.asdict(self)


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


def evidence_key(status: str, rule: dict[str, Any], per_tf_rows: list[dict[str, Any]]) -> str:
    """sha256 over everything a verdict read: the evaluated status, the decision-rule
    parameters and the canonical sorted per-tf statistics."""
    payload = json.dumps(
        {"status": status, "rule": rule, "per_tf": per_tf_rows}, sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class Evaluation:
    """One concept_evaluation row, as derivation sees it."""

    window_end: datetime
    evaluated_status: str
    passed: bool
    n_observations: int
    guard_status: str
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
) -> Transition | None:
    """Pure: the transition the ledger calls for, or None.

    Evidence counted: evaluations made under the current status since the concept entered
    it (a transition resets the evidence bar in both directions), latest per window.
    Streaks are trailing runs over those windows ordered by window_end.

    active -> shadow_only: the trailing failing streak reaches demotion_min_consecutive.
    shadow_only -> active: the trailing passing streak reaches recovery_min_passes.
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
             WHERE t.concept_id = r.concept_id AND t.to_status = r.status) AS status_since
    FROM concept_registry r
    JOIN concept_gate g USING (concept_id)
    WHERE r.domain = $1
"""

_COLUMNS_SQL = """
    SELECT column_name, data_type FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'feature_vectors'
"""

_TFS_SQL = """
    SELECT DISTINCT tf FROM feature_vectors
    WHERE bar_ts >= $1 AND bar_ts < $2 AND tf IS NOT NULL
"""

# Re-seeing identical evidence refreshes evaluated_at, so it becomes the latest row for
# its window again (e.g. a rule changed and then changed back).
_UPSERT_EVALUATION_SQL = """
    INSERT INTO concept_evaluation
        (concept_id, domain, window_end, evidence_key, evaluated_status, passed, statistic,
         n_cells, n_observations, guard_status, detail, evaluated_at, run_ref)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
    ON CONFLICT (concept_id, window_end, evidence_key)
    DO UPDATE SET evaluated_at = EXCLUDED.evaluated_at, run_ref = EXCLUDED.run_ref
"""

# Only rows this rule wrote (detail carries per_tf): the IC-era rows share the table and the
# window keys but measured something else, so they are never evidence here.
_LOAD_EVALUATIONS_SQL = """
    SELECT concept_id, window_end, evaluated_status, passed, n_observations, guard_status,
           evaluated_at, statistic
    FROM concept_evaluation
    WHERE domain = $1
      AND detail ? 'per_tf'
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
    n_cells: int
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
    def failures(self) -> list[tuple[LedgerRow, list[tuple[str, float | None, str]]]]:
        """Each failed row with its failing (tf, coverage, check) entries, computed once."""
        return [(r, _failing_tfs(r)) for r in self.rows if not r.verdict.passed]


def _failing_tfs(row: LedgerRow) -> list[tuple[str, float | None, str]]:
    """(tf, coverage, check) for each failing (feature, tf); a not_computed feature is
    one entry at tf 'all'."""
    if "not_computed" in row.verdict.failures:
        return [("all", 0.0, "not_computed")]
    return [
        (q.tf, q.symbol_coverage, row.verdict.per_tf[q.tf])
        for q in row.per_tf
        if row.verdict.per_tf.get(q.tf) in ("coverage", "non_finite")
    ]


class FeatureLifecycle(BaseBatch):
    job_name = "feature-lifecycle"
    compute_version = "2.0.0"

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
                    conn, extra_like_patterns=["feature.coverage.%", "feature.lifecycle.%"]
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
        known_columns = {r["column_name"]: r["data_type"] for r in await conn.fetch(_COLUMNS_SQL)}
        computable = [n for n in governed if n in known_columns]

        per_feature: dict[str, list[FeatureTfQuality]] = defaultdict(list)
        for tf in tfs:
            started = time.monotonic()
            counts: dict[str, list[SymbolCounts]] = defaultdict(list)
            for start in range(0, len(computable), _MAX_FEATURES_PER_QUERY):
                chunk = computable[start : start + _MAX_FEATURES_PER_QUERY]
                sql = build_tf_query(chunk, known_columns)
                for row in await conn.fetch(sql, tf, span_start, span_end):
                    for i, name in enumerate(chunk):
                        counts[name].append(
                            SymbolCounts(row["symbol"], row["n_rows"], row[f"c{i}"], row[f"x{i}"])
                        )
            for name in computable:
                per_feature[name].append(feature_tf_quality(name, tf, counts[name]))
            self.logger.info(
                "feature_lifecycle.tf_measured",
                tf=tf,
                n_features=len(computable),
                seconds=round(time.monotonic() - started, 2),
            )

        rows = self._plan_rows(governed, concepts, per_feature, tfs, config)

        # Derive over the whole ledger plus this window's rows (the newest evaluations),
        # so a replay of any window takes effect.
        evaluations: dict[Any, list[Evaluation]] = defaultdict(list)
        for r in await conn.fetch(_LOAD_EVALUATIONS_SQL, _DOMAIN):
            evaluations[r["concept_id"]].append(
                Evaluation(
                    window_end=r["window_end"],
                    evaluated_status=r["evaluated_status"],
                    passed=r["passed"],
                    n_observations=r["n_observations"],
                    guard_status=r["guard_status"],
                    evaluated_at=r["evaluated_at"],
                    statistic=r["statistic"],
                )
            )
        for row in rows:
            evaluations[row.concept_id].append(row.evaluation)

        transitions = []
        for name in governed:
            concept = concepts[name]
            transition = derive_feature_transition(
                concept["status"],
                concept["status_since"],
                evaluations.get(concept["concept_id"], []),
                config,
            )
            if transition is not None:
                transitions.append(PlannedTransition(name, concept["status"], transition))
        return WindowPlan(len(tfs), rows, transitions)

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
            if not per_tf:
                detail["column_missing"] = True
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
                        # the regime-shift guard is gone; 'ok' satisfies migration 357's CHECK
                        guard_status="ok",
                        evaluated_at=now,
                        statistic=verdict.statistic,
                        detail=detail,
                    ),
                    n_cells=len(tfs),
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
        for r, failing in plan.failures:
            for tf, coverage, check in failing:
                FEATURE_QUALITY_FAILURES.add(1, {"tf": tf, "check": check})
                await emit_integrity_fact_async(
                    conn,
                    "feature_quality",
                    f"{r.name}|tf={tf}",
                    "symbol_coverage",
                    coverage,
                    config.coverage_floor,
                    False,
                    self._window,
                )
        await emit_integrity_fact_async(
            conn,
            "feature_quality",
            None,
            "n_features_failed",
            float(n_failed),
            0.0,
            n_failed == 0,
            self._window,
        )
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
                    r.evaluation.guard_status,
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
                counts[f"{check}|tf={tf}"] += 1
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
