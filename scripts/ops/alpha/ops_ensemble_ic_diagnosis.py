#!/usr/bin/env python3
"""
ops_ensemble_ic_diagnosis.py — EIC-05 gate-failure diagnosis report.

Emits a 4-section markdown report (N-per-cell, pooled-vs-per-symbol IC gap, TF
breakdown, regime coverage) reading alpha_ensemble_ic + feature_ic_scores, scoped to
the LATEST run (scored_at = max(scored_at); D-142A-R2, review finding #4 — never a
rolling time-window subtraction from the current instant). Each section carries a
root-cause label so an operator can immediately tell WHY the EIC-04 gate failed
without re-deriving the diagnosis by hand.

This report is diagnostic; remediation decisions are human/operator. Exit code is
always 0 — this is informational, not a gate (scripts/ops/alpha/ops_ensemble_ic_gate.py
is the gate).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg

from src.config.settings import Settings

_DEFAULT_MIN_OBS_PER_REGIME = 200


def print_section(title: str) -> None:
    print(f"\n### {title}\n")


async def main() -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            try:
                latest_scored_at = await conn.fetchval(
                    "SELECT max(scored_at) FROM alpha_ensemble_ic"
                )
            except Exception as error:  # CLAUDE.md: exception variable name is `error`
                print(
                    f"## EIC-05 Ensemble IC Diagnosis\n\nFAILED querying alpha_ensemble_ic: {error}"
                )
                return 0

            if latest_scored_at is None:
                print(
                    "## EIC-05 Ensemble IC Diagnosis\n\n"
                    "no IC rows yet — run EnsembleICEngine first "
                    "(scripts: `python services/ensemble_ic_engine.py`)."
                )
                return 0

            min_obs_per_regime = await conn.fetchval(
                "SELECT config_value::int FROM config_state "
                "WHERE config_key = 'alpha.ensemble_ic.min_obs_per_regime'"
            )
            min_obs_warning = None
            if min_obs_per_regime is None:
                min_obs_per_regime = _DEFAULT_MIN_OBS_PER_REGIME
                min_obs_warning = (
                    f"> **WARNING:** alpha.ensemble_ic.min_obs_per_regime missing from APR — "
                    f"using fallback={_DEFAULT_MIN_OBS_PER_REGIME}. This masks APR/migration "
                    "drift; seed the key (migration 195) before trusting section 1."
                )

            # regime_scope may be absent if Phase 141.1 (RSCOPE-01) has not been applied
            # to this DB yet -- fall back to an unfiltered feature_ic_scores count with a
            # documented caveat rather than crashing.
            has_regime_scope = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'feature_ic_scores' AND column_name = 'regime_scope')"
            )

            section1_rows = await conn.fetch(
                "SELECT symbol, tf, regime, lookahead, n_independent FROM alpha_ensemble_ic "
                "WHERE scored_at = $1 ORDER BY n_independent ASC NULLS FIRST LIMIT 50",
                latest_scored_at,
            )

            section2_rows = await conn.fetch(
                """
                SELECT tf, regime, lookahead,
                       max(ic_ci_lower) FILTER (WHERE is_pooled) AS pooled_ci_lower,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY ic_ci_lower)
                           FILTER (WHERE NOT is_pooled) AS per_symbol_median_ci_lower
                FROM alpha_ensemble_ic
                WHERE scored_at = $1 AND ic_ci_lower IS NOT NULL
                GROUP BY tf, regime, lookahead
                ORDER BY tf, regime, lookahead
                """,
                latest_scored_at,
            )

            if has_regime_scope:
                feature_qualifying_count = await conn.fetchval(
                    "SELECT count(*) FROM feature_ic_scores "
                    "WHERE ic_ci_lower > 0 AND regime_scope = 'cross_sectional'"
                )
            else:
                feature_qualifying_count = await conn.fetchval(
                    "SELECT count(*) FROM feature_ic_scores WHERE ic_ci_lower > 0"
                )

            section3_rows = await conn.fetch(
                """
                SELECT tf, count(*) AS n_cells,
                       count(*) FILTER (WHERE ic_ci_lower > 0 AND passes_fdr) AS n_qualifying
                FROM alpha_ensemble_ic
                WHERE scored_at = $1
                GROUP BY tf ORDER BY tf
                """,
                latest_scored_at,
            )

            section4_rows = await conn.fetch(
                """
                SELECT regime, count(*) AS n_cells,
                       count(*) FILTER (WHERE ic_ci_lower > 0 AND passes_fdr) AS n_qualifying
                FROM alpha_ensemble_ic
                WHERE scored_at = $1
                GROUP BY regime ORDER BY regime
                """,
                latest_scored_at,
            )

        print(f"## EIC-05 Ensemble IC Diagnosis (scored_at: {latest_scored_at})")
        if min_obs_warning:
            print()
            print(min_obs_warning)

        # --- Section 1: N per cell -------------------------------------------------
        print_section("Section 1: N per cell (lowest first)")
        print("| symbol | tf | regime | lookahead | n_independent | flag |")
        print("|---|---|---|---|---|---|")
        for r in section1_rows:
            n_ind = r["n_independent"]
            flag = ""
            if n_ind is None or n_ind < min_obs_per_regime:
                flag = "DATA STARVATION (low N, not signal absence)"
            print(
                f"| {r['symbol']} | {r['tf']} | {r['regime']} | {r['lookahead']} | "
                f"{n_ind if n_ind is not None else '-'} | {flag} |"
            )

        # --- Section 2: pooled vs per-symbol IC gap ---------------------------------
        print_section("Section 2: Pooled vs per-symbol IC gap")
        if not has_regime_scope:
            print(
                "> Note: feature_ic_scores.regime_scope not present on this DB — the "
                "comparison count below is provenance-unfiltered (Phase 141.1 RSCOPE-01 "
                "not yet applied)."
            )
        print(
            f"Comparison context: feature_ic_scores rows with ic_ci_lower > 0 "
            f"(cross_sectional scope): {feature_qualifying_count}"
        )
        print()
        print("| tf | regime | lookahead | pooled_ci_lower | per_symbol_median_ci_lower | flag |")
        print("|---|---|---|---|---|---|")
        for r in section2_rows:
            pooled = r["pooled_ci_lower"]
            per_symbol_median = r["per_symbol_median_ci_lower"]
            flag = ""
            if (
                pooled is not None
                and pooled > 0
                and (per_symbol_median is None or per_symbol_median <= 0)
            ):
                flag = "REGIME GRANULARITY ISSUE (cross-sectional label too coarse)"
            print(
                f"| {r['tf']} | {r['regime']} | {r['lookahead']} | "
                f"{pooled if pooled is not None else '-'} | "
                f"{per_symbol_median if per_symbol_median is not None else '-'} | {flag} |"
            )

        # --- Section 3: TF breakdown -------------------------------------------------
        print_section("Section 3: TF breakdown")
        print("| tf | n_cells | n_qualifying | flag |")
        print("|---|---|---|---|")
        tf_qual = {r["tf"]: r["n_qualifying"] for r in section3_rows}
        for r in section3_rows:
            flag = ""
            if tf_qual.get("1h", 0) and not tf_qual.get("5m", 0):
                flag = "TF-specific problem (5m fewer independent obs per regime)"
            print(f"| {r['tf']} | {r['n_cells']} | {r['n_qualifying']} | {flag} |")

        # --- Section 4: regime coverage -----------------------------------------------
        print_section("Section 4: Regime coverage")
        zero_qualifying_regimes = [r["regime"] for r in section4_rows if not r["n_qualifying"]]
        print("| regime | n_cells | n_qualifying | flag |")
        print("|---|---|---|---|")
        for r in section4_rows:
            flag = ""
            if len(zero_qualifying_regimes) >= 3 and r["regime"] in zero_qualifying_regimes:
                flag = "regime label quality issue (check market_regimes / equity_regime_model)"
            print(f"| {r['regime']} | {r['n_cells']} | {r['n_qualifying']} | {flag} |")

        print()
        print("---")
        print("This report is diagnostic; remediation decisions are human/operator.")

        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
