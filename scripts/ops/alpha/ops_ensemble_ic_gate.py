#!/usr/bin/env python3
"""
ops_ensemble_ic_gate.py — EIC-04 phase-gate evaluation.

Reads alpha_ensemble_ic, computes the fraction of (symbol, tf, regime) cells WHERE
lookahead = gate_lookahead AND ic_ci_lower > 0 AND passes_fdr = true AND
walk_forward_stable = true on the LATEST run (scored_at = max(scored_at); D-142A-R2 —
a single pinned-per-run vintage), compares to alpha.ensemble_ic.min_qualifying_fraction
(APR, NOT baked in), emits a PASS/FAIL markdown verdict.

Phase 144 re-evaluates OOS by running EnsembleICEngine on the OOS window (which writes
a NEW scored_at vintage) and re-running this gate — the query always targets the latest
run, never a rolling time-window subtraction from the current instant (review finding #4).

Exit code 0 on PASS, 1 on FAIL (so CI/systemd can gate on it).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg

from src.config.settings import Settings

# EIC-04 gate SQL (D-142A-R2, review finding #4): run selection is the deterministic
# latest scored_at vintage, NOT a rolling time-window subtraction from the current
# instant. The in-sample constraint (bar_ts < alpha.validation.oos_start) is already
# enforced at IC-compute time by EnsembleICEngine (Plan 01), so this query does not
# re-filter on bar_ts.
# Phase 144 OOS evaluation requires a SEPARATE EnsembleICEngine run on the OOS window
# (producing a new latest scored_at) then re-running this script against that vintage.
_GATE_SQL = """
    WITH latest AS (SELECT max(scored_at) AS ts FROM alpha_ensemble_ic),
    qualifying AS (
        SELECT symbol, tf, regime FROM alpha_ensemble_ic
        WHERE lookahead = $1
          AND ic_ci_lower > 0 AND passes_fdr = true AND walk_forward_stable = true
          AND scored_at = (SELECT ts FROM latest)
        GROUP BY symbol, tf, regime
    ),
    total AS (
        SELECT COUNT(DISTINCT (symbol, tf, regime)) AS n_total FROM alpha_ensemble_ic
        WHERE lookahead = $1
          AND scored_at = (SELECT ts FROM latest)
    )
    SELECT (SELECT ts FROM latest) AS latest_scored_at,
           (SELECT COUNT(*) FROM qualifying) AS n_qualifying,
           (SELECT n_total FROM total) AS n_total
"""


def _evaluate_gate(
    n_qualifying: int, n_total: int, min_qualifying_fraction: float
) -> tuple[bool, float]:
    """Pure helper: compute the qualifying-cell fraction and compare to the threshold.

    Guards n_total == 0 (empty table / no cells at the latest vintage) by returning
    (False, 0.0) without raising ZeroDivisionError.
    """
    fraction = n_qualifying / n_total if n_total else 0.0
    passed = fraction >= min_qualifying_fraction
    return passed, fraction


async def main() -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            try:
                threshold = await conn.fetchval(
                    "SELECT config_value::float FROM config_state "
                    "WHERE config_key = 'alpha.ensemble_ic.min_qualifying_fraction'"
                )
                gate_lookahead = await conn.fetchval(
                    "SELECT config_value FROM config_state "
                    "WHERE config_key = 'alpha.ensemble_ic.gate_lookahead'"
                )
            except Exception as error:  # CLAUDE.md: exception variable name is `error`
                print(f"## EIC-04 Phase Gate\n\nFAILED to read APR config: {error}")
                return 1

            if threshold is None:
                print(
                    "## EIC-04 Phase Gate\n\n"
                    "FAILED: alpha.ensemble_ic.min_qualifying_fraction missing from "
                    "config_state — seed it via migration 195 before running this gate."
                )
                return 1
            if gate_lookahead is None:
                print(
                    "## EIC-04 Phase Gate\n\n"
                    "FAILED: alpha.ensemble_ic.gate_lookahead missing from config_state "
                    "— seed it via migration 195 before running this gate."
                )
                return 1

            try:
                row = await conn.fetchrow(_GATE_SQL, gate_lookahead)
            except Exception as error:
                print(f"## EIC-04 Phase Gate\n\nFAILED querying alpha_ensemble_ic: {error}")
                return 1

        latest_scored_at = row["latest_scored_at"]
        n_qualifying = row["n_qualifying"] or 0
        n_total = row["n_total"] or 0

        if latest_scored_at is None:
            print(
                "## EIC-04 Phase Gate\n\n"
                "no IC rows yet — run EnsembleICEngine first "
                "(scripts: `python services/ensemble_ic_engine.py`)."
            )
            return 1

        passed, fraction = _evaluate_gate(n_qualifying, n_total, threshold)

        print("## EIC-04 Phase Gate")
        print()
        print(f"Run (scored_at): {latest_scored_at}")
        print(f"Threshold (APR): {threshold}")
        print(f"Gate lookahead (APR): {gate_lookahead}")
        print(f"Qualifying cells: {n_qualifying}/{n_total}")
        print(f"Fraction: {fraction:.4f}")
        print(f"Verdict: {'PASS' if passed else 'FAIL'}")
        if not passed:
            print()
            print(
                "Run scripts/ops/alpha/ops_ensemble_ic_diagnosis.py for structured "
                "diagnosis (EIC-05)."
            )

        return 0 if passed else 1
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
