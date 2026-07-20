#!/usr/bin/env python3
"""Cost-Hurdle / Threshold / Gap Calibration — todo 030 Steps 0-3.

Standalone, idempotent, re-runnable calibration script. Reads the current
`alpha_events` / `forward_returns` / `feature_ic_scores` corpus and:

- Step 0 (report only): re-emits the external cost-floor verdict recorded in
  todo 030 (median IC-implied gross E[R] vs cost floor per tf/scale). No APR write.
- Step 1: sets `alpha.quant.cost_hurdle.5m` / `.15m` to the empirical P10/P25
  of their `alpha_ci_lower` distribution. 1h/1d stay at 0.0 (cost immaterial
  at longer horizons per todo 030).
- Step 2: validates whether `alpha.quant.threshold.{tf}` is binding against
  the `abs(alpha_score)` distribution; lowers only on an `over_filtering`
  verdict (current > P50).
- Step 3: checks gap contamination in `forward_returns` (`has_gap_before_entry`)
  against `feature_ic_scores`. ALWAYS reports the finding; writes a follow-up
  todo file under `.planning/todos/pending/` ONLY when `--write-todo` is passed
  (default: report-only, no repo mutation).

Every APR write goes through `ConfigService.set` so provenance lands in
`config_history` with `changed_by='cost_hurdle_calibration'` and
`reason='rca_analysis'`.

CORRECTNESS INVARIANTS:
- Startup gate: raises RuntimeError if alpha_events or forward_returns is
  empty — never writes 0.0 as if it were calibrated.
- No direct corpus-table mutation: this script only reads alpha_events /
  forward_returns / feature_ic_scores; all writes go through ConfigService
  against config_state / config_history.
- Does NOT edit ic_engine.py, ensemble_trainer.py, alpha_publisher.py, or the
  corpus bash — deliberately standalone so it runs in parallel with Plans 01/02/04.

Usage:
    python scripts/ops/corpus/ops_cost_hurdle_calibration.py
    python scripts/ops/corpus/ops_cost_hurdle_calibration.py --dry-run
    python scripts/ops/corpus/ops_cost_hurdle_calibration.py --cost-percentile p10
    python scripts/ops/corpus/ops_cost_hurdle_calibration.py --write-todo
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402

setup_service_logging("logs/cost_hurdle_calibration.log")
_logger = structlog.get_logger(__name__)

_JOB = "cost-hurdle-calibration"
_CHANGED_BY = "cost_hurdle_calibration"
_REASON = "rca_analysis"

# Timeframes eligible for cost-hurdle calibration (Step 1). 1h/1d stay at 0.0 —
# cost is less material at longer horizons per todo 030.
_COST_HURDLE_TFS = ("5m", "15m")
_ALL_TFS = ("5m", "15m", "1h", "1d")

_DEFAULT_REPORT_PATH = "docs/analysis/cost-hurdle-calibration.md"

# Step 0 verdict table, recorded in todo 030 (run 2026-07-01). Report-only —
# no APR write from Step 0. Kept as a literal snapshot of the recorded
# finding; re-run todo 030's Step 0 manually if the corpus changes materially.
_STEP0_VERDICT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("5m fast (lookahead=1)", "0.26 bps", "Dead — 4-40x below cheapest cost floor"),
    ("5m mid", "0.84 bps", "Dead for most of universe"),
    ("5m slow", "4.33 bps", "Survives liquid core only"),
    ("5m extended", "13.6 bps", "Clears broadly"),
    ("15m fast", "0.55 bps", "Dead"),
    ("15m mid", "1.72 bps", "Marginal, cheapest names only"),
    ("15m slow", "8.9 bps", "Clears broadly"),
    ("1h fast", "4.0 bps", "Marginal-to-clears"),
    ("1d fast", "7.5 bps", "Clears broadly"),
    ("1d mid/slow/extended", "27-161 bps", "Clears comfortably"),
)

_GAP_FOLLOWUP_TODO_TEMPLATE = """---
**Created:** {date}
**Area:** intelligence / ic_engine
**Type:** hardening
**Priority:** P2
**Effort:** trivial (one-line WHERE clause, no migration)
**Risk:** low
**Gate:** none
---

# {todo_number} — Gap-contamination IC filter

`ops_cost_hurdle_calibration.py` (todo 030 Step 3) found a material gap-contamination
effect in `forward_returns`: bars with `has_gap_before_entry = true` show a materially
different return distribution than bars without, and the gap fraction is large enough
to matter.

| Metric | gap=true | gap=false |
|---|---|---|
| n | {n_gap} | {n_nogap} |
| mean return_fast | {mean_gap:.6f} | {mean_nogap:.6f} |
| gap_fraction | {gap_fraction:.4f} | — |

## Fix

Add `WHERE has_gap_before_entry = false` to the `ic_engine.py` `forward_returns` join
(one-line change, no migration needed) so IC measurement excludes gap-contaminated bars.

## Reference

Found by `scripts/ops/corpus/ops_cost_hurdle_calibration.py` (todo 030 Step 3), run on
{date}. NOT applied here — this todo captures the finding for a future ic_engine change
(owned by a different plan to avoid file conflict).
"""


# ---------------------------------------------------------------------------
# Pure decision helpers — unit-tested without a DB (see tests/unit/test_cost_hurdle_calibration.py)
# ---------------------------------------------------------------------------


def _select_cost_hurdle(percentiles: dict[str, float], percentile: str = "p25") -> float:
    """Return the chosen percentile value from a per-tf percentile dict."""
    return percentiles[percentile]


def _threshold_verdict(current: float, p10: float, p50: float) -> str:
    """Classify whether an emission threshold is binding against the score distribution.

    'not_binding' when current < p10 (threshold rarely filters anything).
    'over_filtering' when current > p50 (threshold rejects the majority of the distribution).
    'ok' otherwise.
    """
    if current < p10:
        return "not_binding"
    if current > p50:
        return "over_filtering"
    return "ok"


def _gap_verdict(
    mean_gap: float, mean_nogap: float, gap_fraction: float, tolerance: float = 0.01
) -> str:
    """Classify whether gap-before-entry contamination is material.

    'not_supported' when the gap fraction is negligible (<5%) or the return means
    are within `tolerance` (relative, on the larger-magnitude mean) of each other.
    'material' otherwise.
    """
    if gap_fraction < 0.05:
        return "not_supported"
    scale = max(abs(mean_gap), abs(mean_nogap), 1e-12)
    if abs(mean_gap - mean_nogap) / scale < tolerance:
        return "not_supported"
    return "material"


# ---------------------------------------------------------------------------
# DB-touching steps
# ---------------------------------------------------------------------------


async def _startup_gate(conn: asyncpg.Connection) -> tuple[int, int]:
    """Raise RuntimeError if alpha_events or forward_returns is empty."""
    alpha_events_count = await conn.fetchval("SELECT count(*) FROM alpha_events")
    forward_returns_count = await conn.fetchval("SELECT count(*) FROM forward_returns")
    if alpha_events_count == 0 or forward_returns_count == 0:
        raise RuntimeError(
            "cost-hurdle calibration requires a populated corpus — "
            f"alpha_events={alpha_events_count}, forward_returns={forward_returns_count} "
            "(at least one is empty). Run the corpus pipeline first."
        )
    return alpha_events_count, forward_returns_count


async def _step1_cost_hurdle_percentiles(conn: asyncpg.Connection) -> dict[str, dict[str, float]]:
    """Step 1 SQL: percentile_cont(0.10/0.25/0.50) of alpha_ci_lower per tf."""
    rows = await conn.fetch("""
        SELECT
            tf,
            count(*) AS n,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY alpha_ci_lower) AS p10,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY alpha_ci_lower) AS p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY alpha_ci_lower) AS p50,
            avg(alpha_ci_lower) AS mean
        FROM alpha_events
        WHERE alpha_ci_lower IS NOT NULL
        GROUP BY tf ORDER BY tf
        """)
    return {
        row["tf"]: {
            "n": row["n"],
            "p10": row["p10"],
            "p25": row["p25"],
            "p50": row["p50"],
            "mean": row["mean"],
        }
        for row in rows
    }


async def _step2_threshold_percentiles(conn: asyncpg.Connection) -> dict[str, dict[str, float]]:
    """Step 2 SQL: percentile_cont(0.05/0.10/0.25) of abs(alpha_score) per tf."""
    rows = await conn.fetch("""
        SELECT
            tf,
            count(*) AS n,
            percentile_cont(0.05) WITHIN GROUP (ORDER BY abs(alpha_score)) AS p05,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY abs(alpha_score)) AS p10,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY abs(alpha_score)) AS p25,
            min(abs(alpha_score)) AS min_score
        FROM alpha_events
        GROUP BY tf ORDER BY tf
        """)
    return {
        row["tf"]: {
            "n": row["n"],
            "p05": row["p05"],
            "p10": row["p10"],
            "p25": row["p25"],
            "min_score": row["min_score"],
        }
        for row in rows
    }


async def _step3_gap_contamination(
    conn: asyncpg.Connection,
) -> tuple[dict[bool, dict[str, float]], dict[str, float]]:
    """Step 3 SQL: return distribution by has_gap_before_entry + avg IC per tf."""
    gap_rows = await conn.fetch("""
        SELECT
            has_gap_before_entry,
            count(*) AS n,
            avg(return_fast) FILTER (WHERE NOT return_fast_suspect) AS mean_return_fast,
            stddev(return_fast) FILTER (WHERE NOT return_fast_suspect) AS std_return_fast
        FROM forward_returns
        GROUP BY has_gap_before_entry
        """)
    gap_stats = {
        row["has_gap_before_entry"]: {
            "n": row["n"],
            "mean_return_fast": row["mean_return_fast"] or 0.0,
            "std_return_fast": row["std_return_fast"] or 0.0,
        }
        for row in gap_rows
    }

    ic_rows = await conn.fetch("""
        SELECT
            fis.tf,
            count(*) AS n,
            avg(fis.ic_value) AS avg_ic
        FROM feature_ic_scores fis
        GROUP BY fis.tf ORDER BY fis.tf
        """)
    ic_by_tf = {row["tf"]: row["avg_ic"] for row in ic_rows}

    return gap_stats, ic_by_tf


def _write_gap_followup_todo(
    gap_stats: dict[bool, dict[str, float]],
    todos_dir: Path,
) -> Path:
    """Write the follow-up todo file for a 'material' gap verdict. Caller must gate on --write-todo."""
    existing = sorted(todos_dir.glob("[0-9][0-9][0-9]-*.md"))
    next_number = 1
    if existing:
        numbers = [int(p.name.split("-", 1)[0]) for p in existing]
        next_number = max(numbers) + 1
    todo_number = f"{next_number:03d}"

    gap_row = gap_stats.get(True, {"n": 0, "mean_return_fast": 0.0})
    nogap_row = gap_stats.get(False, {"n": 0, "mean_return_fast": 0.0})
    total_n = gap_row["n"] + nogap_row["n"]
    gap_fraction = (gap_row["n"] / total_n) if total_n else 0.0

    content = _GAP_FOLLOWUP_TODO_TEMPLATE.format(
        date=datetime.now(UTC).date().isoformat(),
        todo_number=todo_number,
        n_gap=gap_row["n"],
        n_nogap=nogap_row["n"],
        mean_gap=gap_row["mean_return_fast"],
        mean_nogap=nogap_row["mean_return_fast"],
        gap_fraction=gap_fraction,
    )
    todos_dir.mkdir(parents=True, exist_ok=True)
    path = todos_dir / f"{todo_number}-gap-contamination-ic-filter.md"
    path.write_text(content)
    return path


def _proposed_gap_followup_text(gap_stats: dict[bool, dict[str, float]]) -> str:
    """Render the proposed follow-up todo text for report/console printing (no file write)."""
    gap_row = gap_stats.get(True, {"n": 0, "mean_return_fast": 0.0})
    nogap_row = gap_stats.get(False, {"n": 0, "mean_return_fast": 0.0})
    total_n = gap_row["n"] + nogap_row["n"]
    gap_fraction = (gap_row["n"] / total_n) if total_n else 0.0
    return (
        "Proposed follow-up todo: add `WHERE has_gap_before_entry = false` to the "
        "ic_engine.py forward_returns join (one-line change, no migration needed). "
        f"gap n={gap_row['n']} mean_return_fast={gap_row['mean_return_fast']:.6f}; "
        f"nogap n={nogap_row['n']} mean_return_fast={nogap_row['mean_return_fast']:.6f}; "
        f"gap_fraction={gap_fraction:.4f}. Pass --write-todo to capture this as a todo file."
    )


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _render_report(
    *,
    args: argparse.Namespace,
    alpha_events_count: int,
    forward_returns_count: int,
    step1_percentiles: dict[str, dict[str, float]],
    step1_writes: dict[str, float],
    step2_percentiles: dict[str, dict[str, float]],
    step2_verdicts: dict[str, str],
    step2_writes: dict[str, float],
    gap_stats: dict[bool, dict[str, float]],
    ic_by_tf: dict[str, float],
    gap_verdict: str,
    write_count: int,
) -> str:
    now = datetime.now(UTC).isoformat()
    lines: list[str] = []
    lines.append("# Cost-Hurdle / Threshold / Gap Calibration Report")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append(f"Mode: {'dry-run (no writes)' if args.dry_run else 'live'}")
    lines.append(f"cost-percentile: {args.cost_percentile}")
    lines.append(
        f"Corpus row counts at run time — alpha_events={alpha_events_count}, "
        f"forward_returns={forward_returns_count} "
        "(a partial/in-flight corpus produces provisional percentiles)."
    )
    lines.append("")

    lines.append("## Step 0 — External Cost Floor Verdict (recorded, report-only)")
    lines.append("")
    lines.append("| tf / scale | Median-IC gross E[R] | vs cost floor |")
    lines.append("|---|---|---|")
    for scale, er, verdict in _STEP0_VERDICT_ROWS:
        lines.append(f"| {scale} | {er} | {verdict} |")
    lines.append("")
    lines.append(
        "No APR write from Step 0 — it is a verdict, not a calibration. "
        "Source: todo 030, run 2026-07-01, unshrunk IC (upper bound)."
    )
    lines.append("")

    lines.append("## Step 1 — Cost-Hurdle Calibration")
    lines.append("")
    lines.append("| tf | n | p10 | p25 | p50 | mean | chosen | written |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for tf in _ALL_TFS:
        row = step1_percentiles.get(tf)
        if row is None:
            lines.append(f"| {tf} | 0 | - | - | - | - | - | no data |")
            continue
        chosen = step1_writes.get(tf)
        chosen_str = f"{chosen:.6f}" if chosen is not None else "n/a (1h/1d left at 0.0)"
        written_str = "yes" if (tf in step1_writes and not args.dry_run) else "no"
        lines.append(
            f"| {tf} | {row['n']} | {row['p10']:.6f} | {row['p25']:.6f} | "
            f"{row['p50']:.6f} | {row['mean']:.6f} | {chosen_str} | {written_str} |"
        )
    lines.append("")

    lines.append("## Step 2 — Emission Threshold Validation")
    lines.append("")
    lines.append("| tf | n | p05 | p10 | p25 | min_score | verdict | written |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for tf in _ALL_TFS:
        row = step2_percentiles.get(tf)
        if row is None:
            lines.append(f"| {tf} | 0 | - | - | - | - | no data | no |")
            continue
        verdict = step2_verdicts.get(tf, "unknown")
        written_str = "yes" if (tf in step2_writes and not args.dry_run) else "no"
        lines.append(
            f"| {tf} | {row['n']} | {row['p05']:.6f} | {row['p10']:.6f} | "
            f"{row['p25']:.6f} | {row['min_score']:.6f} | {verdict} | {written_str} |"
        )
    lines.append("")

    lines.append("## Step 3 — Gap Contamination Check")
    lines.append("")
    lines.append("| has_gap_before_entry | n | mean_return_fast | std_return_fast |")
    lines.append("|---|---|---|---|")
    for gap_flag in (True, False):
        row = gap_stats.get(gap_flag, {"n": 0, "mean_return_fast": 0.0, "std_return_fast": 0.0})
        lines.append(
            f"| {gap_flag} | {row['n']} | {row['mean_return_fast']:.6f} | {row['std_return_fast']:.6f} |"
        )
    lines.append("")
    lines.append("| tf | avg IC |")
    lines.append("|---|---|")
    for tf in _ALL_TFS:
        avg_ic = ic_by_tf.get(tf)
        lines.append(f"| {tf} | {avg_ic:.6f} |" if avg_ic is not None else f"| {tf} | no data |")
    lines.append("")
    lines.append(f"**Gap verdict: {gap_verdict}**")
    lines.append("")
    if gap_verdict == "material":
        lines.append(_proposed_gap_followup_text(gap_stats))
        lines.append("")
        if args.write_todo:
            lines.append("Follow-up todo file WRITTEN (--write-todo passed).")
        else:
            lines.append(
                "Follow-up todo file NOT written (default report-only — pass --write-todo to write it)."
            )
    else:
        lines.append("Hypothesis not supported — no action.")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"Total APR writes this run: {write_count if not args.dry_run else 0}")
    lines.append(
        "All writes route through ConfigService.set(changed_by='cost_hurdle_calibration', "
        "reason='rca_analysis') — audited in config_history."
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)

    config_service = ConfigService(database_url=settings.database_url)
    await config_service.initialize()

    write_count = 0
    try:
        async with pool.acquire() as conn:
            alpha_events_count, forward_returns_count = await _startup_gate(conn)
            _logger.info(
                "cost_hurdle_calibration.corpus_gate_passed",
                alpha_events=alpha_events_count,
                forward_returns=forward_returns_count,
            )

            # Step 1
            step1_percentiles = await _step1_cost_hurdle_percentiles(conn)
            step1_writes: dict[str, float] = {}
            for tf in _COST_HURDLE_TFS:
                row = step1_percentiles.get(tf)
                if row is None:
                    continue
                chosen = _select_cost_hurdle(row, percentile=args.cost_percentile)
                if chosen is None:
                    continue
                step1_writes[tf] = chosen
                if not args.dry_run:
                    await config_service.set(
                        f"alpha.quant.cost_hurdle.{tf}",
                        chosen,
                        changed_by=_CHANGED_BY,
                        reason=_REASON,
                    )
                    write_count += 1

            # Step 2
            step2_percentiles = await _step2_threshold_percentiles(conn)
            current_thresholds = {
                tf: await config_service.get(f"alpha.quant.threshold.{tf}") for tf in _ALL_TFS
            }
            step2_verdicts: dict[str, str] = {}
            step2_writes: dict[str, float] = {}
            for tf in _ALL_TFS:
                row = step2_percentiles.get(tf)
                current = current_thresholds.get(tf)
                if row is None or current is None:
                    continue
                verdict = _threshold_verdict(float(current), row["p10"], row["p50"])
                step2_verdicts[tf] = verdict
                if verdict == "over_filtering":
                    new_value = row["p25"]
                    step2_writes[tf] = new_value
                    if not args.dry_run:
                        await config_service.set(
                            f"alpha.quant.threshold.{tf}",
                            new_value,
                            changed_by=_CHANGED_BY,
                            reason=_REASON,
                        )
                        write_count += 1

            # Step 3
            gap_stats, ic_by_tf = await _step3_gap_contamination(conn)
            gap_row = gap_stats.get(True, {"n": 0, "mean_return_fast": 0.0})
            nogap_row = gap_stats.get(False, {"n": 0, "mean_return_fast": 0.0})
            total_n = gap_row["n"] + nogap_row["n"]
            gap_fraction = (gap_row["n"] / total_n) if total_n else 0.0
            gap_verdict = _gap_verdict(
                mean_gap=gap_row["mean_return_fast"],
                mean_nogap=nogap_row["mean_return_fast"],
                gap_fraction=gap_fraction,
            )

            if gap_verdict == "material":
                proposed_text = _proposed_gap_followup_text(gap_stats)
                print(proposed_text)  # noqa: T201 — always-report console output per spec
                _logger.info("cost_hurdle_calibration.gap_material", finding=proposed_text)
                if args.write_todo:
                    todos_dir = project_root / ".planning" / "todos" / "pending"
                    todo_path = _write_gap_followup_todo(gap_stats, todos_dir)
                    _logger.info(
                        "cost_hurdle_calibration.gap_followup_todo_written",
                        path=str(todo_path),
                    )
                    print(f"Follow-up todo written: {todo_path}")  # noqa: T201
            else:
                _logger.info("cost_hurdle_calibration.gap_not_supported", gap_fraction=gap_fraction)

        report = _render_report(
            args=args,
            alpha_events_count=alpha_events_count,
            forward_returns_count=forward_returns_count,
            step1_percentiles=step1_percentiles,
            step1_writes=step1_writes,
            step2_percentiles=step2_percentiles,
            step2_verdicts=step2_verdicts,
            step2_writes=step2_writes,
            gap_stats=gap_stats,
            ic_by_tf=ic_by_tf,
            gap_verdict=gap_verdict,
            write_count=write_count,
        )
        report_path = project_root / args.report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report)
        _logger.info(
            "cost_hurdle_calibration.report_written",
            path=str(report_path),
            write_count=write_count,
            dry_run=args.dry_run,
        )
        print(f"Report written: {report_path}")  # noqa: T201
        print(f"APR writes: {write_count if not args.dry_run else 0}")  # noqa: T201
    finally:
        await config_service.close()
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cost-hurdle / threshold / gap calibration — todo 030 Steps 0-3"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + report only, no APR writes",
    )
    parser.add_argument(
        "--cost-percentile",
        choices=["p10", "p25"],
        default="p25",
        help="Percentile of alpha_ci_lower to use for the cost-hurdle write (default: p25)",
    )
    parser.add_argument(
        "--report-path",
        default=_DEFAULT_REPORT_PATH,
        help=f"Path (relative to repo root) to write the markdown report (default: {_DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--write-todo",
        action="store_true",
        default=False,
        help=(
            "When Step 3 finds a material gap-contamination verdict, write the follow-up "
            "todo FILE under .planning/todos/pending/. Default: report-only (the finding is "
            "always reported and printed; the file is written only with this flag)."
        ),
    )
    args = parser.parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("cost_hurdle_calibration.otel_init_failed", error=str(error))

    try:
        asyncio.run(_run(args))
    except RuntimeError as error:
        _logger.error("cost_hurdle_calibration.failed", error=str(error))
        print(f"FATAL: {error}", file=sys.stderr)  # noqa: T201
        sys.exit(1)


if __name__ == "__main__":
    main()
