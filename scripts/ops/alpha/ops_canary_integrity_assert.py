#!/usr/bin/env python3
"""
ops_canary_integrity_assert.py -- Component D corpus-run integrity gate (todo 068,
Phase 143.1-02).

Expectation-aware, false-halt-aware assertion over the 5 canary/control predictors
(feature_registry.is_control=true rows, migration 223). Queries feature_ic_scores for
every canary x stratum cell in the latest training_window_end vintage and evaluates
each against its control_expectation ('negative_control' | 'positive_control').

HARD-halt (loud, non-zero exit / raised error) if:
  - Any negative-control canary (canary_noise_gaussian/uniform/constant/near_constant)
    clears `ic_ci_lower>0 AND passes_fdr` in the POOLED family (symbol='POOLED',
    is_pooled=true). POOLED is the ONLY family `_ELIGIBILITY_BASE_WHERE`
    (services/ensemble_trainer.py) reads -- a POOLED clear here means a broken
    measurement pipeline is one config flip away from weighting a control feature
    into the live ensemble.
  - The acausal-placebo positive control does NOT clear that same gate in POOLED --
    proves this pipeline fails to detect look-ahead leakage when genuinely present
    (the whole point of carrying a positive control at all).
  - No canary rows exist for the latest vintage at all -- the corpus run had no
    canary coverage, so this gate cannot validate anything (a silent pass here would
    be worse than a loud failure).

NOT a hard-halt: a single per-symbol (non-POOLED) negative-control clear. BH-FDR at
alpha=0.05 admits ~5% false discoveries by design (Fable review SHOULD-FIX 6) -- a
literal "any per-symbol stratum clears -> halt" rule fires on expected statistical
noise a meaningful fraction of runs. Per-symbol clears are instead COUNTED and
compared against a pre-committed Binomial tail bound (see _binomial_tail_bound);
only exceeding the bound hard-fails.

The chosen quantitative rule (POOLED hard-halt scope + Binomial bound) is recorded
in docs/plans/methodology-change-ledger.md (entry E7) BEFORE the first real corpus
run exercises this script, per this project's pre-commitment convention for
gate-affecting decisions.

Wired into scripts/ops/corpus/ops_corpus_pipeline_run.sh immediately after Step 5
(ic_engine) -- feature_ic_scores must exist before this gate has anything to read.

Usage:
    python scripts/ops/alpha/ops_canary_integrity_assert.py
    python scripts/ops/alpha/ops_canary_integrity_assert.py --tail-alpha 0.01
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
from scipy.stats import binom

from src.config.settings import Settings

_FDR_ALPHA_DEFAULT = 0.05
_BINOMIAL_TAIL_ALPHA_DEFAULT = 0.01

_LATEST_VINTAGE_SQL = "SELECT MAX(training_window_end) FROM feature_ic_scores"

_CANARY_ROWS_SQL = """
    SELECT
        s.feature_name, s.symbol, s.tf, s.regime, s.is_pooled,
        s.ic_ci_lower, s.ic_ci_upper, s.passes_fdr,
        r.control_expectation
    FROM feature_ic_scores s
    JOIN feature_registry r ON r.feature_name = s.feature_name
    WHERE r.is_control = true
      AND s.training_window_end = $1
"""


class CanaryIntegrityViolation(RuntimeError):
    """Raised on a hard-halt condition -- a proven broken measurement pipeline."""


def _clears_gate(row: dict[str, Any]) -> bool:
    """The exact eligibility predicate _ELIGIBILITY_BASE_WHERE (ensemble_trainer.py)
    reads: ic_ci_lower > 0 AND passes_fdr. A canary clearing this is exactly what
    would let it reach ensemble weighting if it weren't excluded via status='candidate'."""
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


def evaluate(
    rows: list[dict[str, Any]],
    fdr_alpha: float = _FDR_ALPHA_DEFAULT,
    tail_alpha: float = _BINOMIAL_TAIL_ALPHA_DEFAULT,
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

    pooled_violations: list[dict[str, Any]] = []
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
            if cleared:
                pooled_violations.append(row)
        else:
            per_symbol_negative_cells += 1
            if cleared:
                per_symbol_negative_clears.append(row)

    bound = _binomial_tail_bound(per_symbol_negative_cells, fdr_alpha, tail_alpha)
    n_clears = len(per_symbol_negative_clears)

    report = {
        "n_rows_evaluated": len(rows),
        "pooled_violations": pooled_violations,
        "placebo_pooled_seen": placebo_pooled_seen,
        "placebo_pooled_cleared": placebo_pooled_cleared,
        "per_symbol_negative_cells": per_symbol_negative_cells,
        "per_symbol_negative_clears": n_clears,
        "per_symbol_binomial_bound": bound,
        "per_symbol_bound_exceeded": n_clears > bound,
    }

    failures: list[str] = []

    if pooled_violations:
        offenders = ", ".join(
            f"{r['feature_name']}@{r['tf']}/{r['regime']}" for r in pooled_violations
        )
        failures.append(
            f"POOLED negative-control canary cleared the significance gate "
            f"(ic_ci_lower>0 AND passes_fdr): {offenders}"
        )

    if placebo_pooled_seen and not placebo_pooled_cleared:
        failures.append(
            "canary_acausal_placebo (positive control) did NOT clear the significance "
            "gate in the POOLED stratum -- this pipeline failed to detect a deliberate "
            "look-ahead leak, meaning it cannot be trusted to detect a real one either"
        )

    if n_clears > bound:
        offenders = ", ".join(
            f"{r['feature_name']}@{r['symbol']}/{r['tf']}/{r['regime']}"
            for r in per_symbol_negative_clears
        )
        failures.append(
            f"per-symbol negative-control clears ({n_clears}) exceed the pre-committed "
            f"Binomial tail bound ({bound}, n_cells={per_symbol_negative_cells}, "
            f"p={fdr_alpha}, tail_alpha={tail_alpha}): {offenders}"
        )

    if failures:
        raise CanaryIntegrityViolation("; ".join(failures))

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
    return parser.parse_args()


async def _fetch_rows(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    vintage = await pool.fetchval(_LATEST_VINTAGE_SQL)
    if vintage is None:
        return []
    rows = await pool.fetch(_CANARY_ROWS_SQL, vintage)
    return [dict(r) for r in rows]


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        rows = await _fetch_rows(pool)
        report = evaluate(rows, fdr_alpha=args.fdr_alpha, tail_alpha=args.tail_alpha)

        print("# Canary Integrity Report\n")
        print(f"Evaluated {report['n_rows_evaluated']} canary cells.")
        print(
            f"Positive-control (acausal placebo) POOLED cleared: "
            f"{report['placebo_pooled_cleared']} (seen={report['placebo_pooled_seen']})"
        )
        print(
            f"Per-symbol negative-control clears: {report['per_symbol_negative_clears']}"
            f"/{report['per_symbol_negative_cells']} cells "
            f"(bound={report['per_symbol_binomial_bound']})"
        )
        print("\nPASS -- canary integrity gate cleared.")
        return 0
    except CanaryIntegrityViolation as violation:
        print(f"\nFATAL: canary integrity violation -- {violation}", file=sys.stderr)
        return 1
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
