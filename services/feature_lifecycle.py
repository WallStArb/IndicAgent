#!/usr/bin/env python3
"""Feature Lifecycle -- oneshot that governs concept_registry (domain='feature') status from
persisted IC evidence (todo 402).

DAG position:

    ic_engine -> feature_ic_scores -> feature_lifecycle -> concept_evaluation,
                                                           concept_registry -> ensemble_trainer

Reads only persisted rows, so any training window can be re-evaluated without an IC
recompute, and a change to lifecycle logic never moves ic_engine's code_content_key.
Design: docs/plans/2026-09-24-feature-lifecycle-evidence-ledger-design.md.

One run evaluates one training window:

1. Load the window's POOLED cells at each tf's mid lookahead, joined to the champion
   ensemble weights pinned in APR (alpha.ensemble.weight_version). Those weights come from
   an earlier ensemble_trainer run, an input artifact rather than this run's output, so
   each run's DAG stays acyclic; the feedback is a time-lagged recurrence.
2. Flag material failures per cell: a failing cell (CI on its own side includes zero, or
   fails FDR) whose standing weight times its nearest CI bound exceeds
   alpha.decay.materiality_threshold.
3. Regime-shift guard, stratified per (tf, regime_group) over active concepts' cells. A
   stratum holds only against its own calibrated history (todo 407: no level-based rail;
   `uncalibrated` strata never hold). The window's verdict is 'hold_high' if any stratum
   holds. History counts one observation per earlier window, never the current window.
4. One concept_evaluation row per evaluated feature: active concepts are judged on the
   material-fail fraction, shadow_only concepts on the FDR pass fraction. The primary key
   (concept, window, evidence_key) makes a rerun on identical evidence a no-op.
5. Derive each concept's status from the ledger with derive_feature_transition (pure) and
   apply any transition through ConceptRegistryService.record_transition.

The decision rules are the ones the retired ic_engine post-run hook used (todo 144 guard,
todo 323 demotion hysteresis, Component E sign awareness). What changed is how evidence is
counted: streaks run over distinct windows, so recomputing a window's IC after a code
change never counts as new evidence, and a window evaluated before a feature existed is
evaluated again once it does.

Usage:
    python services/feature_lifecycle.py --training-window-end 2025-12-24T05:15:00+00:00
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_apr_dict_async, lookahead_by_scale_from_apr  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.agent.base_batch import BaseBatch  # noqa: E402
from src.core.integrity_monitor import emit_integrity_fact_async  # noqa: E402
from src.core.service_utils import parse_iso_ts, parse_training_window_end  # noqa: E402
from src.intelligence.concept_registry_service import (  # noqa: E402
    ConceptRegistryService,
    TransitionResult,
)
from src.intelligence.statistics.ic_math import evaluate_guard_fraction  # noqa: E402
from src.observability.corpus_manifest import CorpusManifest  # noqa: E402
from src.observability.metrics import (  # noqa: E402
    ALPHA_DECAY_CELLS_FLAGGED,
    ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL,
    IC_ENGINE_LAST_RUN_AGE_DAYS,
)
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402

_logger = structlog.get_logger()

_DOMAIN = "feature"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleConfig:
    """APR snapshot. Keys are the ones ic_engine's retired hook read, unchanged."""

    lookahead_mid: dict[str, int]
    materiality_threshold: float
    guard_band_z: float
    guard_min_cells: int
    guard_min_history: int
    guard_history_window: int
    recovery_min_observations: int
    recovery_min_passes: int
    demotion_min_consecutive: int
    meta_fdr_min_fraction: float
    staleness_alert_days: int
    weight_version: str
    sign_symmetric: bool

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> LifecycleConfig:
        lookaheads = lookahead_by_scale_from_apr(lambda key, default: int(_cfg(cfg, key, default)))
        return cls(
            lookahead_mid=lookaheads["mid"],
            materiality_threshold=_cfg(cfg, "alpha.decay.materiality_threshold", 0.005),
            guard_band_z=_cfg(cfg, "alpha.decay.guard_band_z", 3.0),
            guard_min_cells=_cfg(cfg, "alpha.decay.guard_min_cells", 100),
            guard_min_history=_cfg(cfg, "alpha.decay.guard_min_history", 8),
            guard_history_window=_cfg(cfg, "alpha.decay.guard_history_window", 20),
            recovery_min_observations=_cfg(cfg, "alpha.decay.recovery_min_observations", 2000),
            recovery_min_passes=_cfg(cfg, "alpha.decay.recovery_min_passes", 2),
            demotion_min_consecutive=_cfg(cfg, "alpha.decay.demotion_min_consecutive", 2),
            meta_fdr_min_fraction=_cfg(cfg, "alpha.ensemble.meta_fdr_min_fraction", 0.50),
            staleness_alert_days=_cfg(cfg, "alpha.ic.staleness_alert_days", 5),
            weight_version=_cfg(cfg, "alpha.ensemble.weight_version", "v1"),
            sign_symmetric=_cfg(cfg, "alpha.ensemble.sign_symmetric", False),
        )

    def rule_fingerprint(self) -> dict[str, Any]:
        """Every config field, so any rule change re-evaluates a window instead of colliding
        with its old row. Over-inclusive on purpose: a field that cannot move a verdict
        only adds a row with the same verdict, never a missed re-evaluation."""
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Pure decision logic
# ---------------------------------------------------------------------------


def flag_cell(cell: dict[str, Any], config: LifecycleConfig) -> None:
    """Set _failed, _material_fail and _signed_margin on one cell in place.

    Sign-aware under config.sign_symmetric (Component E, todo 094): a cell fails only if
    its CI on its OWN side includes zero, or it fails FDR -- the unconditional
    `ic_ci_lower <= 0` predicate is always true for a contrarian (ic_sign=-1) and would
    demote every one of them. _signed_margin is the distance from zero on the cell's own
    side, so one min() ranks a feature's mixed-sign cells consistently.
    """
    lower, upper, sign = cell["ic_ci_lower"], cell["ic_ci_upper"], cell["ic_sign"]
    if config.sign_symmetric:
        failed = (
            (sign == 1 and lower is not None and lower <= 0)
            or (sign == -1 and upper is not None and upper >= 0)
            or not cell["passes_fdr"]
        )
        nearest_bound = lower if sign == 1 else upper
        signed_margin = sign * nearest_bound if nearest_bound is not None else None
    else:
        failed = (lower is not None and lower <= 0) or not cell["passes_fdr"]
        nearest_bound = lower
        signed_margin = lower
    cell["_failed"] = failed
    cell["_material_fail"] = failed and (
        cell["standing_weight"] * abs(nearest_bound or 0.0) > config.materiality_threshold
    )
    cell["_signed_margin"] = signed_margin


def guard_cells(cells: Iterable[dict[str, Any]], status_by_feature: dict[str, str]) -> list[dict]:
    """Cells the regime-shift guard evaluates: active concepts only, and never the
    earnings-season measurement scope (Phase 176 Plan 04, T-176-04-03) -- a calendar
    stratum has no market_regimes row by construction and would raise a permanent false
    regime_label_unmapped warning. Keyed on the regime_scope value, not label strings."""
    return [
        c
        for c in cells
        if status_by_feature.get(c["feature_name"]) == "active"
        and c["regime_scope"] != "earnings_season"
    ]


@dataclass(frozen=True)
class StratumGuard:
    status: str  # ok / hold_high / alert_low / insufficient_cells / uncalibrated
    band_lo: float | None
    band_hi: float | None
    n_history: int


def stratum_guard(
    fail_fraction: float, n_cells: int, history: Sequence[float], config: LifecycleConfig
) -> StratumGuard:
    """One (tf, regime_group) stratum's regime-shift verdict (todo 407).

    A dislocation is a CHANGE, so a stratum is judged only against its own history:
    the empirical band (median +/- band_z robust sigma of its earlier windows). Until a
    stratum has guard_min_history earlier windows it is `uncalibrated`: recorded as
    calibration history, never hold-authoritative. There is deliberately no level-based
    rail. The fail fraction is dominated by statistical power (a few-instrument
    cross-asset slice fails ~99% of cells in a normal window, equity ~95%), so a fixed
    ceiling reads low power as dislocation. Without calibration a single bad window is
    still covered by demotion hysteresis (demotion_min_consecutive windows)."""
    if n_cells < config.guard_min_cells:
        return StratumGuard("insufficient_cells", None, None, len(history))
    if len(history) < config.guard_min_history:
        return StratumGuard("uncalibrated", None, None, len(history))
    # rails at [0, 1] are no constraint: the band is the stratum's own history alone. A
    # zero-spread history returns the full [0, 1] band, i.e. no claim either way.
    verdict = evaluate_guard_fraction(
        fail_fraction,
        n_cells,
        history,
        min_cells=config.guard_min_cells,
        min_history=config.guard_min_history,
        band_z=config.guard_band_z,
        rail_lo=0.0,
        rail_hi=1.0,
    )
    return StratumGuard(verdict.status, verdict.band_lo, verdict.band_hi, verdict.n_history)


def window_guard_status(stratum_statuses: Sequence[str]) -> str:
    """Collapse per-stratum verdicts to the window's: any hold holds the whole window
    (one dislocated market/horizon is reason to distrust every decision from it).
    Strata that make no claim (insufficient_cells, uncalibrated) never hold."""
    if "hold_high" in stratum_statuses:
        return "hold_high"
    if "alert_low" in stratum_statuses:
        return "alert_low"
    if "ok" in stratum_statuses:
        return "ok"
    if "uncalibrated" in stratum_statuses:
        return "uncalibrated"
    return "insufficient_cells"


@dataclass(frozen=True)
class Verdict:
    passed: bool
    statistic: float
    n_cells: int
    n_observations: int
    detail: dict[str, Any]


def feature_verdict(status: str, cells: list[dict], config: LifecycleConfig) -> Verdict | None:
    """One feature's verdict for one window, or None for a status the lifecycle does not
    govern (candidate, deprecated).

    active: passes while the material-fail fraction stays below 1 - meta_fdr_min_fraction.
    shadow_only: passes when the FDR pass fraction reaches meta_fdr_min_fraction.
    Cells arrive already flagged by flag_cell.
    """
    if not cells:
        return None
    n_observations = sum(c["n_independent"] or 0 for c in cells)
    if status == "active":
        n_material = sum(1 for c in cells if c["_material_fail"])
        demote_fraction = n_material / len(cells)
        worst = min(
            cells,
            key=lambda c: c["_signed_margin"] if c["_signed_margin"] is not None else 0.0,
        )
        # Report the bound that decided "worst": ic_ci_upper for a contrarian under the flag.
        worst_bound = (
            worst["ic_ci_upper"]
            if config.sign_symmetric and worst["ic_sign"] == -1
            else worst["ic_ci_lower"]
        )
        return Verdict(
            passed=demote_fraction < 1.0 - config.meta_fdr_min_fraction,
            statistic=demote_fraction,
            n_cells=len(cells),
            n_observations=n_observations,
            detail={
                "n_material": n_material,
                "worst_tf": worst["tf"],
                "worst_regime": worst["regime"],
                "worst_ic_sharpe_hac": worst["ic_sharpe_hac"],
                "worst_ci_bound": worst_bound,
            },
        )
    if status == "shadow_only":
        pass_fraction = sum(1 for c in cells if c["passes_fdr"]) / len(cells)
        return Verdict(
            passed=pass_fraction >= config.meta_fdr_min_fraction,
            statistic=pass_fraction,
            n_cells=len(cells),
            n_observations=n_observations,
            detail={},
        )
    return None


_EVIDENCE_CELL_FIELDS = (
    "tf",
    "regime",
    "regime_scope",
    "lookahead_bars",
    "ic_ci_lower",
    "ic_ci_upper",
    "ic_sign",
    "passes_fdr",
    "n_independent",
    "ic_sharpe_hac",
    "standing_weight",
)


def evidence_key(status: str, guard_status: str, cells: list[dict], rule: dict[str, Any]) -> str:
    """sha256 over everything a verdict read: the evaluated status, the window's guard
    verdict, the decision-rule parameters and the canonical sorted cell rows."""
    rows = sorted(
        [c[f] for f in _EVIDENCE_CELL_FIELDS] for c in cells
    )  # tf/regime/scope/lookahead lead each row, so the sort is total
    payload = json.dumps(
        {"status": status, "guard": guard_status, "rule": rule, "cells": rows},
        sort_keys=True,
        default=str,
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
class LifecycleGate:
    demotion_min_consecutive: int
    recovery_min_passes: int
    recovery_min_observations: int


@dataclass(frozen=True)
class Transition:
    to_status: str
    reason: str
    evidence: Evaluation
    n_windows: int
    n_observations: int


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
    gate: LifecycleGate,
) -> Transition | None:
    """Pure: the transition the ledger calls for, or None.

    Evidence counted: evaluations made under the current status since the concept entered
    it (a transition resets the evidence bar in both directions -- todo 323 and Fable N1),
    latest per window, held windows excluded (a regime-shift hold is not evidence either
    way). Streaks are trailing runs over those windows ordered by window_end.

    active -> shadow_only: the trailing failing streak reaches demotion_min_consecutive.
    shadow_only -> active: the trailing passing streak reaches recovery_min_passes AND the
    observations summed over the counted windows reach recovery_min_observations.
    """
    if current_status not in ("active", "shadow_only"):
        return None
    relevant = [
        e
        for e in evaluations
        if e.evaluated_status == current_status
        and (status_since is None or e.evaluated_at >= status_since)
    ]
    windows = [w for w in latest_per_window(relevant) if w.guard_status != "hold_high"]
    if not windows:
        return None
    n_observations = sum(w.n_observations for w in windows)
    if current_status == "active":
        fails = _trailing_run(windows, passed=False)
        if fails >= gate.demotion_min_consecutive:
            return Transition(
                "shadow_only", "demotion_performance", windows[-1], fails, n_observations
            )
        return None
    passes = _trailing_run(windows, passed=True)
    if passes >= gate.recovery_min_passes and n_observations >= gate.recovery_min_observations:
        return Transition("active", "promotion", windows[-1], passes, n_observations)
    return None


def staleness(
    prior_run: datetime | None, this_run: datetime | None, alert_days: int
) -> tuple[int, bool]:
    """Gap in days between the previous IC run and this one, and whether it exceeds
    alpha.ic.staleness_alert_days (LIFECYCLE-05). Alert-only: never triggers a recompute.
    Detects a too-long gap retroactively, at the next run. (0, False) when either end is
    unknown (first run, missing manifest)."""
    if prior_run is None or this_run is None:
        return 0, False
    age_days = (this_run - prior_run).days
    return age_days, age_days > alert_days


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

# Pinned to each tf's mid lookahead in SQL ($3/$4 are parallel tf / lookahead arrays),
# so one (feature, tf, regime) yields exactly one cell.
_CELLS_SQL = """
    SELECT fis.feature_name, fis.tf, fis.regime, fis.regime_scope, fis.lookahead_bars,
           fis.ic_ci_lower, fis.ic_ci_upper, fis.ic_sign, fis.passes_fdr,
           fis.n_independent, fis.ic_sharpe_hac,
           COALESCE(ew.weight, 0.0) AS standing_weight
    FROM feature_ic_scores fis
    JOIN unnest($3::text[], $4::int[]) AS mid(tf, lookahead_bars)
      ON mid.tf = fis.tf AND mid.lookahead_bars = fis.lookahead_bars
    LEFT JOIN ensemble_weights ew
           ON ew.symbol = 'UNIVERSE'
          AND ew.tf = fis.tf
          AND ew.regime = fis.regime
          AND ew.feature_name = fis.feature_name
          AND ew.weight_version = $1
    WHERE fis.symbol = 'POOLED'
      AND fis.is_pooled = true
      AND fis.regime != '_pooled'
      AND fis.training_window_end = $2
"""

# JOIN concept_gate: excludes migration 284's gate-less tombstone rows, the same
# population ic_engine's alignment gate and _watermark_concept_registry use.
_CONCEPTS_SQL = """
    SELECT r.concept_id, r.name, r.status, g.min_demotion_consecutive,
           (SELECT max(t.triggered_at) FROM concept_transition_log t
             WHERE t.concept_id = r.concept_id AND t.to_status = r.status) AS status_since
    FROM concept_registry r
    JOIN concept_gate g USING (concept_id)
    WHERE r.domain = $1
"""

# Calibration history for every stratum in one pass: one observation per EARLIER window
# (its latest fact), so replaying a window neither double-counts it nor lets it
# calibrate against later windows.
_GUARD_HISTORY_SQL = """
    SELECT subject, metric_value FROM (
        SELECT subject, metric_value,
               row_number() OVER (PARTITION BY subject ORDER BY training_window_end DESC) AS rn
        FROM (
            SELECT DISTINCT ON (subject, training_window_end)
                   subject, training_window_end, metric_value
            FROM integrity_monitor
            WHERE monitor_type = 'ic_lifecycle'
              AND metric_name = 'guard_fail_fraction'
              AND subject = ANY($1::text[])
              AND training_window_end < $2
            ORDER BY subject, training_window_end, evaluated_at DESC
        ) per_window
    ) ranked
    WHERE rn <= $3
    ORDER BY subject, rn
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

_PRIOR_EVALUATION_SQL = """
    SELECT max(evaluated_at) FROM concept_evaluation WHERE domain = $1 AND evaluated_at < $2
"""

_LOAD_EVALUATIONS_SQL = """
    SELECT concept_id, window_end, evaluated_status, passed, n_observations, guard_status,
           evaluated_at, statistic, detail
    FROM concept_evaluation
    WHERE domain = $1
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


@dataclass(frozen=True)
class PlannedTransition:
    name: str
    from_status: str
    transition: Transition


@dataclass
class WindowPlan:
    """Everything one window's evaluation decides, computed without writing anything.
    A dry run stops at the plan; a real run persists it with _apply."""

    cells: list[dict]
    guard_facts: list[tuple[str, float, float, bool]]  # subject, fraction, bound, passed
    guard_status: str
    rows: list[LedgerRow]
    transitions: list[PlannedTransition]


class FeatureLifecycle(BaseBatch):
    job_name = "feature-lifecycle"
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, training_window_end: datetime, dry_run: bool = False) -> None:
        super().__init__(db_dsn)
        self._window = training_window_end
        # dry_run: build the plan exactly as a real run, persist nothing, log it instead.
        self._dry_run = dry_run

    def _span_attrs(self) -> dict[str, Any]:
        return {"training_window_end": str(self._window), "dry_run": self._dry_run}

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        async with pool.acquire() as conn:
            config = LifecycleConfig.from_apr(await load_apr_dict_async(conn))
            plan = await self._plan(conn, config)
            if plan is None:
                # No POOLED cells for this window (per-symbol-only run, equity model off).
                # Nothing is written, so a later run with cells evaluates it normally.
                self.logger.info(
                    "feature_lifecycle.no_cells", training_window_end=str(self._window)
                )
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
                n_cells=len(plan.cells),
                n_material=sum(1 for c in plan.cells if c["_material_fail"]),
                guard_status=plan.guard_status,
                n_evaluated=len(plan.rows),
                n_failed=sum(1 for r in plan.rows if not r.evaluation.passed),
                n_transitions=n_applied,
            )

    # -- plan (reads only) ----------------------------------------------------

    async def _plan(self, conn: asyncpg.Connection, config: LifecycleConfig) -> WindowPlan | None:
        tfs = sorted(config.lookahead_mid)
        cells = [
            dict(r)
            for r in await conn.fetch(
                _CELLS_SQL,
                config.weight_version,
                self._window,
                tfs,
                [config.lookahead_mid[tf] for tf in tfs],
            )
        ]
        if not cells:
            return None
        for cell in cells:
            flag_cell(cell, config)

        concepts = {r["name"]: dict(r) for r in await conn.fetch(_CONCEPTS_SQL, _DOMAIN)}
        guard_facts, guard_status = await self._plan_guard(
            conn, cells, {n: c["status"] for n, c in concepts.items()}, config
        )
        rows = self._plan_rows(cells, concepts, guard_status, config)

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
                    detail=r["detail"],
                )
            )
        for row in rows:
            evaluations[row.concept_id].append(row.evaluation)

        transitions = []
        for name, concept in sorted(concepts.items()):
            # A non-NULL concept_gate.min_demotion_consecutive overrides the APR default.
            gate = LifecycleGate(
                demotion_min_consecutive=(
                    concept["min_demotion_consecutive"]
                    if concept["min_demotion_consecutive"] is not None
                    else config.demotion_min_consecutive
                ),
                recovery_min_passes=config.recovery_min_passes,
                recovery_min_observations=config.recovery_min_observations,
            )
            transition = derive_feature_transition(
                concept["status"],
                concept["status_since"],
                evaluations.get(concept["concept_id"], []),
                gate,
            )
            if transition is not None:
                transitions.append(PlannedTransition(name, concept["status"], transition))
        return WindowPlan(cells, guard_facts, guard_status, rows, transitions)

    async def _plan_guard(
        self,
        conn: asyncpg.Connection,
        cells: list[dict],
        status_by_feature: dict[str, str],
        config: LifecycleConfig,
    ) -> tuple[list[tuple[str, float, float, bool]], str]:
        """Stratified per (tf, regime_group), self-calibrating, two-sided (todo 144).
        Returns one guard_fail_fraction fact per stratum -- the calibration history --
        and the window-level verdict."""
        active_cells = guard_cells(cells, status_by_feature)
        if not active_cells:
            return [], window_guard_status([])
        rows = await conn.fetch("SELECT DISTINCT regime_group, regime_label FROM market_regimes")
        group_by_label = {r["regime_label"]: r["regime_group"] for r in rows}

        strata: dict[str, list[dict]] = defaultdict(list)
        for cell in active_cells:
            group = group_by_label.get(cell["regime"], "_unmapped")
            strata[f"tf={cell['tf']}|group={group}"].append(cell)
        n_unmapped = sum(len(v) for k, v in strata.items() if k.endswith("|group=_unmapped"))
        if n_unmapped:
            # A regime label market_regimes does not know is a data-contract violation
            # (stale/renamed label), surfaced whether or not its stratum trips the guard.
            self.logger.warning(
                "feature_lifecycle.regime_label_unmapped",
                n_cells=n_unmapped,
                training_window_end=str(self._window),
            )

        history: dict[str, list[float]] = defaultdict(list)
        for r in await conn.fetch(
            _GUARD_HISTORY_SQL, list(strata), self._window, config.guard_history_window
        ):
            history[r["subject"]].append(r["metric_value"])

        facts, statuses = [], []
        for subject, stratum in sorted(strata.items()):
            fail_fraction = sum(1 for c in stratum if c["_failed"]) / len(stratum)
            verdict = stratum_guard(fail_fraction, len(stratum), history[subject], config)
            statuses.append(verdict.status)
            # threshold_value: whichever band bound is nearer (the one a small drift
            # violates next), NULL when the stratum makes no claim; passed is false only
            # for the two tails.
            nearer_bound = (
                None
                if verdict.band_hi is None
                else (
                    verdict.band_hi
                    if abs(fail_fraction - verdict.band_hi) <= abs(fail_fraction - verdict.band_lo)
                    else verdict.band_lo
                )
            )
            facts.append(
                (
                    subject,
                    fail_fraction,
                    nearer_bound,
                    verdict.status not in ("hold_high", "alert_low"),
                )
            )
            if verdict.status in ("hold_high", "alert_low"):
                self.logger.warning(
                    (
                        "feature_lifecycle.regime_shift_hold"
                        if verdict.status == "hold_high"
                        else "feature_lifecycle.guard_suspicious_pass_rate"
                    ),
                    subject=subject,
                    fraction=fail_fraction,
                    band_lo=verdict.band_lo,
                    band_hi=verdict.band_hi,
                    n_history=verdict.n_history,
                    training_window_end=str(self._window),
                )
        return facts, window_guard_status(statuses)

    def _plan_rows(
        self,
        cells: list[dict],
        concepts: dict[str, dict],
        guard_status: str,
        config: LifecycleConfig,
    ) -> list[LedgerRow]:
        """One ledger row per governed feature."""
        cells_by_feature: dict[str, list[dict]] = defaultdict(list)
        for cell in cells:
            cells_by_feature[cell["feature_name"]].append(cell)
        rule = config.rule_fingerprint()
        now = datetime.now(UTC)
        rows = []
        for name, feature_cells in sorted(cells_by_feature.items()):
            concept = concepts.get(name)
            if concept is None:
                continue
            verdict = feature_verdict(concept["status"], feature_cells, config)
            if verdict is None:
                continue
            rows.append(
                LedgerRow(
                    concept_id=concept["concept_id"],
                    name=name,
                    evidence_key=evidence_key(concept["status"], guard_status, feature_cells, rule),
                    evaluation=Evaluation(
                        window_end=self._window,
                        evaluated_status=concept["status"],
                        passed=verdict.passed,
                        n_observations=verdict.n_observations,
                        guard_status=guard_status,
                        evaluated_at=now,
                        statistic=verdict.statistic,
                        detail=verdict.detail,
                    ),
                    n_cells=verdict.n_cells,
                )
            )
        return rows

    # -- apply (writes + metrics) ---------------------------------------------

    async def _apply(
        self, conn: asyncpg.Connection, plan: WindowPlan, config: LifecycleConfig
    ) -> int:
        """Persist a plan: guard facts, the decay fact, ledger rows, transitions, metrics.
        Returns the number of transitions applied."""
        await self._emit_staleness(conn, config)
        for cell in plan.cells:
            if cell["_material_fail"]:
                ALPHA_DECAY_CELLS_FLAGGED.add(
                    1,
                    {
                        "feature_name": cell["feature_name"],
                        "tf": cell["tf"],
                        "regime": cell["regime"],
                    },
                )
        for subject, fraction, bound, passed in plan.guard_facts:
            await emit_integrity_fact_async(
                conn,
                "ic_lifecycle",
                subject,
                "guard_fail_fraction",
                fraction,
                bound,
                passed,
                self._window,
            )
        await emit_integrity_fact_async(
            conn,
            "ic_lifecycle",
            None,
            "decay_cells_flagged",
            float(sum(1 for c in plan.cells if c["_material_fail"])),
            config.materiality_threshold,
            True,
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
            detail = t.evidence.detail or {}
            result = await registry.record_transition(
                conn,
                domain=_DOMAIN,
                name=p.name,
                from_status=p.from_status,
                to_status=t.to_status,
                reason=t.reason,
                gate_metric=detail.get("worst_ic_sharpe_hac", t.evidence.statistic),
                gate_n=float(t.n_observations),
                ci_lower=detail.get("worst_ci_bound"),
                corpus_build_ref=str(t.evidence.window_end),
                # Promotion is earned by the FDR pass fraction over counted windows --
                # the executed multiplicity correction the L-6 guard asks callers to attest.
                fdr_passed=True if t.to_status == "active" else None,
                notes=f"{t.n_windows} consecutive windows (feature_lifecycle)",
            )
            if result is TransitionResult.APPLIED:
                n_applied += 1
                ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL.add(1, {"feature_name": p.name})
        return n_applied

    async def _emit_staleness(self, conn: asyncpg.Connection, config: LifecycleConfig) -> None:
        """The ic_engine manifest holds only the latest run, which in the pipeline is the
        run just finished. The previous run is found in the ledger instead: the newest
        evaluation stamped before this IC run completed."""
        try:
            ts = CorpusManifest.read(CorpusManifest.DEFAULT_MANIFEST_DIR, "ic_engine").get(
                "timestamp"
            )
        except FileNotFoundError:
            ts = None
        this_run = parse_iso_ts(ts)
        prior_run = (
            await conn.fetchval(_PRIOR_EVALUATION_SQL, _DOMAIN, this_run) if this_run else None
        )
        age_days, alert = staleness(prior_run, this_run, config.staleness_alert_days)
        IC_ENGINE_LAST_RUN_AGE_DAYS.set(age_days)
        if alert:
            self.logger.warning(
                "feature_lifecycle.ic_gap_exceeded",
                gap_days=age_days,
                threshold=config.staleness_alert_days,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Feature Lifecycle -- ledger-derived feature governance"
    )
    parser.add_argument(
        "--training-window-end",
        required=True,
        help="Training window to evaluate; same value ic_engine ran with (ISO-8601, UTC).",
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
