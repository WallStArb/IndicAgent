#!/usr/bin/env python3
"""Renaissance Primitive Discovery Report — skeleton (Phase 142.5 Plan 00).

Documents the query/report structure for ranking all 152 FeatureVector
primitives (61 baseline + 91 new Renaissance primitives) by IC Sharpe once a
corpus run has populated feature_ic_scores for them. Does NOT implement the
full query logic yet — that lands once Plans 01-05.5 implement the primitives,
Plan 06 seeds concept_registry (domain='feature') + applies migration 206, and a corpus backfill
+ IC engine run populates feature_ic_scores for the new columns.

IC-driven discovery pattern (services/ic_engine.py): the IC engine evaluates
every feature identically -- no feature-specific logic. This script reads
feature_ic_scores (already populated by ic_engine.py), ranks by IC Sharpe, and
applies the same pass/fail gate ic_engine.py itself uses (IC Sharpe > 0 AND
p < 0.05, corpus-level BH-FDR via passes_fdr) -- it does not recompute IC.

Usage:
    python scripts/analysis/ops_primitive_discovery_report.py --help
    python scripts/analysis/ops_primitive_discovery_report.py --training-window-end 2026-07-01
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_DEFAULT_REPORT_PATH = "docs/analysis/primitive-discovery-report.md"

# Renaissance principle: never drop a primitive from the report even if it
# fails every gate -- a documented null result is itself signal (avoids
# re-litigating "did we already try this" later). The gate below only
# determines PASS/FAIL labeling, not report inclusion.
_IC_SHARPE_GATE_MIN = 0.0
_P_VALUE_GATE_MAX = 0.05


@dataclass(frozen=True)
class PrimitiveICSummary:
    """One row of the discovery report: per-feature IC Sharpe summary.

    Populated from feature_ic_scores (already written by services/ic_engine.py).
    This dataclass is the report's internal representation -- it is not a new
    persistence layer, just a query result shape.
    """

    feature_name: str
    vector_domain: str
    n_cells: int
    ic_sharpe_mean: float
    ic_sharpe_std: float
    ic_sharpe_min: float
    ic_sharpe_max: float
    passes_gate_fraction: float  # fraction of (symbol, tf, regime) cells passing the gate
    passes_fdr: bool


def _query_feature_ic_scores_sql() -> str:
    """Documented query structure for reading feature_ic_scores per primitive.

    Structure only -- not executed by this skeleton. Once implemented, this
    will read feature_ic_scores for a given training_window_end, group by
    feature_name, and compute the aggregate IC Sharpe statistics used by
    generate_primitive_discovery_report() below.

    Mirrors the SELECT shape services/ic_engine.py itself uses when reading
    back feature_ic_scores (idempotency / manifest-output queries), stratified
    by regime (9 cross-sectional labels: {low/mid/high}_{bull/neutral/bear})
    and gated on ic_sharpe > 0 AND p_value < 0.05 AND passes_fdr = true.
    """
    return """
        SELECT feature_name, vector_domain, symbol, tf, regime, lookahead_bars,
               ic_value, ic_sharpe, p_value, ic_ci_lower, ic_ci_upper,
               passes_ci_gate, passes_fdr, passes_walkforward
        FROM feature_ic_scores
        WHERE training_window_end = %(training_window_end)s
        ORDER BY feature_name, tf, regime
    """


def generate_primitive_discovery_report(
    training_window_end: datetime,
    report_path: Path,
) -> list[PrimitiveICSummary]:
    """Generate the IC Sharpe ranking report for all 152 FeatureVector primitives.

    Reads feature_ic_scores (already populated by services/ic_engine.py for the
    given training_window_end), ranks by IC Sharpe, and produces:
      - Per-feature IC Sharpe statistics (mean, std, min, max) across all
        (symbol, tf, regime) cells
      - Regime subgroup breakdown (9 cross-sectional labels)
      - Pass/fail gate: IC Sharpe > 0 AND p < 0.05 AND passes_fdr = true
      - Top-N and bottom-N primitive lists by mean IC Sharpe

    NOT IMPLEMENTED YET (Wave 0 skeleton): the actual DB read + aggregation is
    deferred until Plans 01-05.5 land the primitives and a corpus run populates
    feature_ic_scores for them. Calling this today with a real DB connection
    would simply return zero rows (no Renaissance primitive rows exist in
    feature_ic_scores until then) -- raising here instead makes that state
    explicit rather than silently writing an empty report.

    Args:
        training_window_end: The IC engine run's training_window_end boundary
            (OOS-enforced per CLAUDE.md Invariant -- see docs/plans/OOS-EVAL-PROTOCOL.md).
        report_path: Where to write the markdown report.

    Returns:
        List of PrimitiveICSummary, one per feature_name found in
        feature_ic_scores for training_window_end, ordered by ic_sharpe_mean
        descending.
    """
    raise NotImplementedError(
        "generate_primitive_discovery_report() query logic is deferred to a "
        "follow-on plan (post Plan 06 + corpus re-run). See "
        "_query_feature_ic_scores_sql() for the documented query structure "
        "this will execute against feature_ic_scores."
    )


def _write_report(summaries: list[PrimitiveICSummary], report_path: Path) -> None:
    """Render summaries to a markdown report at report_path.

    Structure only -- not implemented in this skeleton. Will produce a table
    ranked by ic_sharpe_mean descending, a PASS/FAIL gate column, and a
    top-N/bottom-N section, mirroring the report style of
    scripts/ops/corpus/ops_oos_holdout_eval.py's _write_report().
    """
    raise NotImplementedError("_write_report() is deferred to a follow-on plan.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Renaissance Primitive Discovery Report -- ranks all 152 FeatureVector "
            "primitives by IC Sharpe from feature_ic_scores. Skeleton only "
            "(Phase 142.5 Plan 00): query logic lands once primitives are implemented "
            "and a corpus run has populated feature_ic_scores for them."
        )
    )
    parser.add_argument(
        "--training-window-end",
        required=False,
        default=None,
        help=(
            "IC engine run's training_window_end boundary (ISO 8601, e.g. "
            "2026-07-01T00:00:00Z). Required once query logic is implemented."
        ),
    )
    parser.add_argument(
        "--report-path",
        default=_DEFAULT_REPORT_PATH,
        help=f"Output markdown report path (default: {_DEFAULT_REPORT_PATH})",
    )
    args: argparse.Namespace = parser.parse_args()

    if args.training_window_end is None:
        parser.error(
            "--training-window-end is required once query logic is implemented "
            "(this is a Wave 0 skeleton -- no query runs yet)."
        )

    training_window_end = datetime.fromisoformat(args.training_window_end.replace("Z", "+00:00"))
    report_path = Path(args.report_path)

    generate_primitive_discovery_report(training_window_end, report_path)


if __name__ == "__main__":
    main()
