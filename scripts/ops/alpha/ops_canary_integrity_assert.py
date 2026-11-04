#!/usr/bin/env python3
"""
ops_canary_integrity_assert.py -- Component D corpus-run integrity gate (todo 068,
Phase 143.1-02).

Expectation-aware, false-halt-aware assertion over the 5 canary/control predictors
(concept_registry domain='feature', is_control=true rows; migrations 283/284). Queries
feature_ic_scores (ic_measure's table since migration 575; the ic_engine-era table it
replaced is dropped) for
every canary x stratum cell in each tf's latest training_window_end vintage and evaluates
each against its control_expectation ('negative_control' | 'positive_control').

HARD-halt (loud, non-zero exit / raised error) if:
  - Negative-control canary clears in the POOLED family (symbol='POOLED',
    is_pooled=true) exceed a pre-committed Binomial tail bound (todo 230, 2026-08-02
    addendum to E7 -- see below). POOLED is the eligibility-relevant family for any
    downstream promotion gate -- a POOLED clear alone still does not reach one
    (canaries are permanently `status='candidate'` in concept_registry), but is
    tracked far more conservatively than per-symbol clears.
  - The acausal-placebo positive control does NOT clear that same gate in POOLED --
    proves this pipeline fails to detect look-ahead leakage when genuinely present
    (the whole point of carrying a positive control at all).
  - No canary rows exist for the latest vintage at all -- the corpus run had no
    canary coverage, so this gate cannot validate anything (a silent pass here would
    be worse than a loud failure).

NOT a hard-halt: a single per-symbol (non-POOLED) or POOLED negative-control clear on
its own. BH-FDR at alpha=0.05 admits ~5% false discoveries by design (Fable review
SHOULD-FIX 6) -- a literal "any stratum clears -> halt" rule fires on expected
statistical noise a meaningful fraction of runs, and FDR correction is corpus-wide
(not per-cell), so its budgeted false discoveries mathematically cluster near
whatever cells carry the most genuine signal -- exactly the cells most likely to also
carry a negative-control canary's occasional false clear. Both per-symbol and POOLED
clears are instead COUNTED and compared against pre-committed Binomial tail bounds
(see _binomial_tail_bound); only exceeding a bound hard-fails. POOLED uses a stricter
(smaller) tail_alpha than per-symbol, reflecting its eligibility relevance, but is not
zero-tolerance -- see the 2026-08-02 E7 addendum for the evidence this was revised on.

The chosen quantitative rule (POOLED hard-halt scope + Binomial bound) is recorded
in docs/plans/methodology-change-ledger.md (entry E7, and its 2026-08-02 addendum)
per this project's pre-commitment convention for gate-affecting decisions.

Wired into scripts/ops/corpus/ops_corpus_pipeline_run.sh immediately after Step 4
(ic_measure) -- feature_ic_scores must exist before this gate has anything to read.

Usage:
    python scripts/ops/alpha/ops_canary_integrity_assert.py
    python scripts/ops/alpha/ops_canary_integrity_assert.py --tail-alpha 0.01
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
from scipy.stats import binom

from src.config.settings import Settings

_FDR_ALPHA_DEFAULT = 0.05
_BINOMIAL_TAIL_ALPHA_DEFAULT = 0.01
# POOLED is the eligibility-relevant family (ensemble_trainer.py reads it, gated further
# by concept_registry status='active', which canaries never reach) -- held to a stricter
# bound than per-symbol, but not zero-tolerance. See 2026-08-02 E7 addendum.
_POOLED_TAIL_ALPHA_DEFAULT = 0.001

# The gate scores the vintage ic_measure (writer of feature_ic_scores) just wrote.
# regime_scope = 'unstratified' is the migration 413 translation of the old "<> 'earnings_season'"
# filter: the proposer's family measurement, not a stratified overlay scope.
# Only proposer cells are testable: ic_measure fills ic_ci_* and passes_fdr at each tf's proposer
# horizon alone (proposer_rows), so passes_fdr IS NOT NULL selects exactly them; untestable
# horizons would inflate the negative-control cell count and loosen the Binomial bound. The
# vintage is per (tf, horizon): training_window_end is that cell's last target exit bar before
# oos_start (migration 413), so one MAX across tfs would leave the other tfs unevaluated. The
# gate is not tied to one ic_measure run id; it reads each cell's latest vintage.

_CANARY_ROWS_SQL = """
    SELECT
        s.feature_name, s.symbol, s.tf, s.regime, s.is_pooled,
        s.ic_ci_lower, s.ic_ci_upper, s.passes_fdr,
        s.cumulative_e_value,
        r.control_expectation
    FROM feature_ic_scores s
    JOIN concept_registry r ON r.name = s.feature_name AND r.domain = 'feature'
    JOIN concept_gate cg ON cg.concept_id = r.concept_id
    WHERE r.is_control = true
      AND s.regime_scope = 'unstratified'
      AND s.passes_fdr IS NOT NULL
      AND s.training_window_end = (
          SELECT max(v.training_window_end) FROM feature_ic_scores v
          WHERE v.tf = s.tf AND v.lookahead_bars = s.lookahead_bars
            AND v.regime_scope = 'unstratified'
      )
"""
# cumulative_e_value: migration 413 keeps the column but ic_measure never writes it (the e-value
# pilot, Component C, todo 079, was an ic_engine experiment), so evaluate_e_value_decay sees NULL
# coverage and reports it (its empty-scope path reports, never hard-fails) until it does.
# concept_gate is INNER JOINed for consistency with every other Phase 170-repointed
# ops_* script's tombstone defense (ops_broadcast_feature_audit.py et al.) -- a no-op
# today since migration 284 hardcodes is_control=false on both gate-less tombstone
# rows, but this keeps the exclusion structural rather than incidental to that value.

# e-value pilot scope (Component C, todo 079, Phase 143.1 Plan 06): tf=5m only, matching
# the deleted ic_engine's _e_value_pilot_active gate. With ic_measure writing no e-value
# (see the _CANARY_ROWS_SQL comment) this scope evaluates zero rows today; it stays so
# the check reactivates unchanged once ic_measure fills cumulative_e_value.
_E_VALUE_PILOT_TFS = frozenset({"5m"})


class CanaryIntegrityViolation(RuntimeError):
    """Raised on a hard-halt condition -- a proven broken measurement pipeline."""


def _clears_gate(row: dict[str, Any]) -> bool:
    """The significance-gate shape a downstream weighting path reads (the deleted
    ensemble_trainer's _ELIGIBILITY_BASE_WHERE was the original referent):
    ic_ci_lower > 0 AND passes_fdr. A canary clearing this is exactly what would let
    it reach a weighting path if it weren't excluded via status='candidate'."""
    ci_lower = row["ic_ci_lower"]
    return bool(ci_lower is not None and ci_lower > 0 and row["passes_fdr"])


def _binomial_tail_bound(n_cells: int, p: float, tail_alpha: float) -> int:
    """Smallest k such that P(Binomial(n_cells, p) > k) <= tail_alpha.

    scipy's binom.ppf(q, n, p) returns the smallest k with CDF(k) >= q; using
    q = 1 - tail_alpha gives the smallest k with P(X <= k) >= 1 - tail_alpha, i.e.
    P(X > k) <= tail_alpha -- exactly the upper-tail bound this gate needs. p is the
    BH-implied per-cell false-clear rate (alpha=0.05 by default, matching the
    project's standard FDR alpha); n_cells is the number of (canary, symbol)
    negative-control cells evaluated this run.
    """
    if n_cells <= 0:
        return 0
    return int(binom.ppf(1.0 - tail_alpha, n_cells, p))


def _family_bound_check(
    label: str,
    n_cells: int,
    clears: list[dict[str, Any]],
    fdr_alpha: float,
    tail_alpha: float,
    offender_fmt: Callable[[dict[str, Any]], str],
) -> tuple[int, bool, str | None]:
    """Binomial tail-bound check shared by the POOLED and per-symbol negative-
    control families -- same construction, differing only in n_cells, tail_alpha,
    and how an offending row is named in the failure message. Returns
    (bound, exceeded, failure_message_or_None)."""
    bound = _binomial_tail_bound(n_cells, fdr_alpha, tail_alpha)
    n_clears = len(clears)
    if n_clears <= bound:
        return bound, False, None
    offenders = ", ".join(offender_fmt(r) for r in clears)
    message = (
        f"{label} negative-control clears ({n_clears}) exceed the pre-committed "
        f"Binomial tail bound ({bound}, n_cells={n_cells}, p={fdr_alpha}, "
        f"tail_alpha={tail_alpha}): {offenders}"
    )
    return bound, True, message


def evaluate(
    rows: list[dict[str, Any]],
    fdr_alpha: float = _FDR_ALPHA_DEFAULT,
    tail_alpha: float = _BINOMIAL_TAIL_ALPHA_DEFAULT,
    pooled_tail_alpha: float = _POOLED_TAIL_ALPHA_DEFAULT,
) -> dict[str, Any]:
    """Pure evaluation function -- no IO, fully unit-testable without a DB.

    Returns a report dict on success; raises CanaryIntegrityViolation with a
    message naming every offending canary + stratum on any hard-halt condition.
    """
    if not rows:
        raise CanaryIntegrityViolation(
            "no canary rows found for the latest feature_ic_scores vintage -- the "
            "corpus run had no canary coverage; this gate cannot validate anything"
        )

    pooled_negative_clears: list[dict[str, Any]] = []
    pooled_negative_cells = 0
    placebo_pooled_seen = False
    placebo_pooled_cleared = False
    per_symbol_negative_clears: list[dict[str, Any]] = []
    per_symbol_negative_cells = 0

    for row in rows:
        expectation = row["control_expectation"]
        is_pooled_family = row["symbol"] == "POOLED" and bool(row["is_pooled"])
        cleared = _clears_gate(row)

        if expectation == "positive_control":
            if is_pooled_family:
                placebo_pooled_seen = True
                placebo_pooled_cleared = placebo_pooled_cleared or cleared
            continue

        # negative_control
        if is_pooled_family:
            pooled_negative_cells += 1
            if cleared:
                pooled_negative_clears.append(row)
        else:
            per_symbol_negative_cells += 1
            if cleared:
                per_symbol_negative_clears.append(row)

    pooled_bound, pooled_exceeded, pooled_failure = _family_bound_check(
        "POOLED",
        pooled_negative_cells,
        pooled_negative_clears,
        fdr_alpha,
        pooled_tail_alpha,
        offender_fmt=lambda r: f"{r['feature_name']}@{r['tf']}/{r['regime']}",
    )
    per_symbol_bound, per_symbol_exceeded, per_symbol_failure = _family_bound_check(
        "per-symbol",
        per_symbol_negative_cells,
        per_symbol_negative_clears,
        fdr_alpha,
        tail_alpha,
        offender_fmt=lambda r: f"{r['feature_name']}@{r['symbol']}/{r['tf']}/{r['regime']}",
    )

    report = {
        "n_rows_evaluated": len(rows),
        "pooled_negative_cells": pooled_negative_cells,
        "pooled_negative_clears": len(pooled_negative_clears),
        "pooled_binomial_bound": pooled_bound,
        "pooled_bound_exceeded": pooled_exceeded,
        "placebo_pooled_seen": placebo_pooled_seen,
        "placebo_pooled_cleared": placebo_pooled_cleared,
        "per_symbol_negative_cells": per_symbol_negative_cells,
        "per_symbol_negative_clears": len(per_symbol_negative_clears),
        "per_symbol_binomial_bound": per_symbol_bound,
        "per_symbol_bound_exceeded": per_symbol_exceeded,
    }

    failures: list[str] = []

    if pooled_failure:
        failures.append(pooled_failure)

    if placebo_pooled_seen and not placebo_pooled_cleared:
        failures.append(
            "canary_acausal_placebo (positive control) did NOT clear the significance "
            "gate in the POOLED stratum -- this pipeline failed to detect a deliberate "
            "look-ahead leak, meaning it cannot be trusted to detect a real one either"
        )

    if per_symbol_failure:
        failures.append(per_symbol_failure)

    if failures:
        raise CanaryIntegrityViolation("; ".join(failures))

    return report


class EValueDecayViolation(RuntimeError):
    """Raised when a negative-control canary's cumulative e-value crosses the
    promotion threshold -- proves the e-value kernel (Component C, todo 079) is
    mis-specified, accumulating false evidence for a feature known to carry no
    real signal."""


def evaluate_e_value_decay(
    rows: list[dict[str, Any]],
    fdr_alpha: float = _FDR_ALPHA_DEFAULT,
) -> dict[str, Any]:
    """Self-verification of the e-value pilot (Component C, todo 079) against
    Component D's canaries: the negative-control (noise/dead) canaries'
    cumulative e-value must decay toward zero across corpus reruns, never
    crossing the promotion threshold (1/alpha) -- if it does, the e-value
    kernel itself is broken (would let genuine noise "earn" promotion).

    Pure evaluation function -- no IO, fully unit-testable without a DB.

    Scope: only rows within the e-value pilot's tf scope (5m, matching
    the deleted ic_engine's _e_value_pilot_active) AND with a non-NULL
    cumulative_e_value are evaluated -- everything else (other timeframes, or
    rows with no e-value column at all) is silently
    excluded from n_rows_evaluated, not treated as a violation. Unlike
    evaluate()'s base canary integrity check, an empty result (no e-value
    coverage yet) is NOT a hard-halt condition here: feature_ic_scores (migration 413)
    keeps the cumulative_e_value column but ic_measure does not write it yet (see the
    _CANARY_ROWS_SQL comment), so this self-verification reports zero coverage until it does.

    The acausal-placebo positive control's cumulative e-value crossing the
    promotion threshold is the EXPECTED healthy behavior (it should grow --
    see 143.1-06-PLAN.md interfaces) and is reported (positive_control_crossed_
    promotion) but never raises.

    Raises EValueDecayViolation naming every offending negative-control canary
    + stratum if any crosses the promotion threshold.
    """
    promotion_threshold = 1.0 / fdr_alpha

    scoped_rows = [
        row
        for row in rows
        if row["tf"] in _E_VALUE_PILOT_TFS and row["cumulative_e_value"] is not None
    ]

    negative_control_violations: list[dict[str, Any]] = []
    positive_control_crossed = False

    for row in scoped_rows:
        crossed = row["cumulative_e_value"] > promotion_threshold
        if row["control_expectation"] == "negative_control":
            if crossed:
                negative_control_violations.append(row)
        elif row["control_expectation"] == "positive_control":
            positive_control_crossed = positive_control_crossed or crossed

    report = {
        "n_rows_evaluated": len(scoped_rows),
        "negative_control_violations": negative_control_violations,
        "positive_control_crossed_promotion": positive_control_crossed,
        "promotion_threshold": promotion_threshold,
    }

    if negative_control_violations:
        offenders = ", ".join(
            f"{r['feature_name']}@{r['symbol']}/{r['tf']}/{r['regime']}"
            f" (e={r['cumulative_e_value']:.3f})"
            for r in negative_control_violations
        )
        raise EValueDecayViolation(
            f"negative-control canary cumulative e-value crossed the promotion "
            f"threshold ({promotion_threshold:.1f}) -- the e-value kernel is "
            f"accumulating false evidence for a known-noise feature: {offenders}"
        )

    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fdr-alpha",
        type=float,
        default=_FDR_ALPHA_DEFAULT,
        help="BH-implied per-cell false-clear probability used as the Binomial "
        "tail bound's p parameter (matches the project's standard FDR alpha).",
    )
    parser.add_argument(
        "--tail-alpha",
        type=float,
        default=_BINOMIAL_TAIL_ALPHA_DEFAULT,
        help="Significance level for the per-symbol Binomial tail bound itself -- "
        "the probability this gate hard-fails on expected BH-FDR noise alone.",
    )
    parser.add_argument(
        "--pooled-tail-alpha",
        type=float,
        default=_POOLED_TAIL_ALPHA_DEFAULT,
        help="Significance level for the POOLED Binomial tail bound -- stricter than "
        "--tail-alpha by default since POOLED is the eligibility-relevant family.",
    )
    return parser.parse_args()


async def _fetch_rows(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    return [dict(r) for r in await pool.fetch(_CANARY_ROWS_SQL)]


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        rows = await _fetch_rows(pool)
        report = evaluate(
            rows,
            fdr_alpha=args.fdr_alpha,
            tail_alpha=args.tail_alpha,
            pooled_tail_alpha=args.pooled_tail_alpha,
        )

        print("# Canary Integrity Report\n")
        print(f"Evaluated {report['n_rows_evaluated']} canary cells.")
        print(
            f"Positive-control (acausal placebo) POOLED cleared: "
            f"{report['placebo_pooled_cleared']} (seen={report['placebo_pooled_seen']})"
        )
        print(
            f"POOLED negative-control clears: {report['pooled_negative_clears']}"
            f"/{report['pooled_negative_cells']} cells "
            f"(bound={report['pooled_binomial_bound']})"
        )
        print(
            f"Per-symbol negative-control clears: {report['per_symbol_negative_clears']}"
            f"/{report['per_symbol_negative_cells']} cells "
            f"(bound={report['per_symbol_binomial_bound']})"
        )

        # e-value pilot self-verification (Component C, todo 079): not a hard-halt
        # when there's no coverage yet (Plan 07's corpus rerun hasn't run this cell)
        # -- only raises if a negative-control canary's cumulative e-value has
        # actually crossed the promotion threshold.
        e_value_report = evaluate_e_value_decay(rows, fdr_alpha=args.fdr_alpha)
        print(
            f"\ne-value pilot (tf=5m): {e_value_report['n_rows_evaluated']} canary "
            f"cells with coverage; positive-control crossed promotion="
            f"{e_value_report['positive_control_crossed_promotion']}"
        )

        print("\nPASS -- canary integrity gate cleared.")
        return 0
    except (CanaryIntegrityViolation, EValueDecayViolation) as violation:
        print(f"\nFATAL: canary integrity violation -- {violation}", file=sys.stderr)
        return 1
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
