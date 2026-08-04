#!/usr/bin/env python3
"""AlphaScorer -- decile-level diagnostic aggregation over closed primary alpha_frames
(Phase 148, SCORE-01).

Manual/on-demand oneshot: this module is NOT registered on a systemd timer and NOT added
to service_auditor._DAG_ORDER. Its deliverable is the decile-level gate diagnostic
(alpha_strategy_scores), not a recurring measurement cadence -- systemd unit creation and
DAG registration are explicitly deferred (RESEARCH.md Open Question 2; project "prove edge
before production infra" principle). Invoke manually via `.venv/bin/python
services/alpha_scorer.py [--symbols ...] [--tf ...]` when a fresh diagnostic snapshot is
needed.

Buckets alpha_score into per-(symbol, tf, regime) cohort deciles (NTILE(10), deterministic
tie-break ORDER BY alpha_score, bar_ts, frame_id -- Codex MEDIUM: an undefined tie-break
makes NTILE decile assignment unstable across runs) and writes one row per
(symbol, tf, regime, alpha_score_decile) cell to alpha_strategy_scores, including:
  - sample_n / n_clusters / ci_lower / ci_upper -- reused UNMODIFIED from
    counterfactual_tracker.evaluate_frame_gate's day-clustered bootstrap machinery (no new
    or reimplemented statistics in this module)
  - win_rate / sharpe_annualized / max_drawdown -- per-cell descriptive diagnostics
  - ic_alpha_score_corr -- per-cohort rank correlation between alpha_score_decile and
    per-decile mean counterfactual_pnl_r (monotonicity diagnostic; DIAGNOSTIC-ONLY per
    migration 248's alpha.scoring.min_ic_alpha_score_corr provenance, not a gate threshold
    this module itself enforces)

Cells with sample_n < alpha.scoring.min_strategy_n are dropped, never written.

CRITICAL SHAPE CONSTRAINT (verified against live source, services/counterfactual_tracker.py
evaluate_frame_gate line ~954): the helper unpacks its group key as
`for (dim_a, dim_b), bucket in groups.items():` -- it ONLY accepts a 2-tuple group_key. A
4-tuple (symbol, tf, regime, alpha_score_decile) would raise `ValueError: too many values to
unpack`. AlphaScorer therefore iterates per-(symbol, tf, regime) cohort and calls
evaluate_frame_gate ONCE PER COHORT with a 2-tuple group_key=(alpha_score_decile, regime),
reassembling the 4-key output grain in Python: the returned verdict's "tf" field carries the
decile (group_key's first element) and "regime" carries the regime (group_key's second
element); symbol/tf for the output row come from the outer cohort loop, not from the verdict.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import (
    cfg,  # noqa: E402
    load_apr_dict_async,  # noqa: E402
)
from src.config.settings import Settings, get_active_contracts  # noqa: E402
from src.core.agent.base_batch import BaseBatch  # noqa: E402
from src.intelligence.statistics.gate_math import evaluate_frame_gate  # noqa: E402

# Deterministic decile bucketing per (symbol, tf, regime) cohort (RESEARCH.md Assumption
# A3: deciles are cohort-local, not global across the corpus). ORDER BY alpha_score, bar_ts,
# frame_id is the mandatory tie-break (Codex MEDIUM) -- without a deterministic secondary
# sort, NTILE's decile assignment for tied alpha_score values is arbitrary and unstable
# across runs. frame_variant='primary' / status != 'open' / counterfactual_pnl_r IS NOT
# NULL matches the live schema (\d alpha_frames), not the design doc (RESEARCH.md Pitfall 4).
_ALPHA_SCORE_DECILE_SQL = """
    SELECT
        symbol,
        tf,
        regime,
        bar_ts,
        bar_ts::date AS cluster_id,
        counterfactual_pnl_r AS pnl_r,
        NTILE(10) OVER (
            PARTITION BY symbol, tf, regime
            ORDER BY alpha_score, bar_ts, frame_id
        ) AS alpha_score_decile
    FROM alpha_frames
    WHERE frame_variant = 'primary'
      AND status != 'open'
      AND counterfactual_pnl_r IS NOT NULL
      AND ($1::text[] IS NULL OR symbol = ANY($1::text[]))
      AND ($2::text[] IS NULL OR tf = ANY($2::text[]))
"""

_INSERT_SQL = """
    INSERT INTO alpha_strategy_scores (
        symbol, tf, regime, alpha_score_decile, sample_n, n_clusters,
        win_rate, sharpe_annualized, max_drawdown, ic_alpha_score_corr,
        ci_lower, ci_upper, compute_version, run_ts
    ) VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
    )
"""


def _max_drawdown(pnl_r_ordered: np.ndarray) -> float | None:
    """Max peak-to-trough decline of the cumulative-R equity curve for one cell.

    Adapted from scripts/analysis/phase143_1_08_shadow_validation.py's `_max_drawdown` --
    this diagnostic table has no pass/fail gate threshold of its own (alpha.scoring.
    max_drawdown_ratio is consumed downstream by SCORE-03, not by this module), so only the
    raw ratio is returned, not a threshold verdict. WR-03 frozen edge case: if the running
    peak cumulative R at the point of max decline is <= 0, the ratio is not meaningful --
    returns None.
    """
    if len(pnl_r_ordered) == 0:
        return None
    cum = np.cumsum(pnl_r_ordered)
    peak = np.maximum.accumulate(cum)
    decline = peak - cum
    trough_idx = int(np.argmax(decline))
    peak_at_trough = float(peak[trough_idx])
    if peak_at_trough <= 0:
        return None
    return float(decline[trough_idx] / peak_at_trough)


def _annualized_sharpe(pnl_r_ordered: list[float], bar_ts_ordered: list[Any]) -> float | None:
    """Annualized Sharpe of per-trading-day pooled mean counterfactual_pnl_r for one cell.

    Adapted from scripts/analysis/phase143_1_08_shadow_validation.py's `_annualized_sharpe`.
    """
    if not pnl_r_ordered:
        return None
    df = pd.DataFrame({"day": pd.to_datetime(bar_ts_ordered).date, "pnl_r": pnl_r_ordered})
    daily = df.groupby("day")["pnl_r"].mean()
    if len(daily) < 2 or daily.std(ddof=1) == 0:
        return None
    return float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))


def _win_rate(pnl_r_values: list[float]) -> float | None:
    if not pnl_r_values:
        return None
    return float(sum(1 for p in pnl_r_values if p > 0) / len(pnl_r_values))


def _ic_alpha_score_corr(decile_means: dict[int, float]) -> float | None:
    """Rank correlation between alpha_score_decile and per-decile mean counterfactual_pnl_r
    -- a monotonicity diagnostic that is higher when higher deciles earn higher returns.

    Requires at least 2 distinct deciles to form a correlation; returns None otherwise (or
    if scipy returns NaN, e.g. a fully flat/degenerate per-decile mean series).
    """
    if len(decile_means) < 2:
        return None
    deciles = sorted(decile_means)
    means = [decile_means[d] for d in deciles]
    corr, _p_value = spearmanr(deciles, means)
    if corr is None or (isinstance(corr, float) and np.isnan(corr)):
        return None
    return float(corr)


def score_cells(
    rows: list[dict[str, Any]],
    *,
    min_strategy_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
) -> list[dict[str, Any]]:
    """Pure aggregation core: rows (symbol, tf, regime, bar_ts, cluster_id, pnl_r,
    alpha_score_decile) -> list of alpha_strategy_scores row dicts.

    Groups rows into (symbol, tf, regime) cohorts, calls evaluate_frame_gate ONCE PER
    COHORT with a 2-tuple group_key=(alpha_score_decile, regime) (the helper only accepts
    a 2-tuple -- see module docstring), computes per-cell win_rate/sharpe_annualized/
    max_drawdown and per-cohort ic_alpha_score_corr, and filters out any cell with
    sample_n < min_strategy_n before returning.
    """
    cohorts: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cohorts[(row["symbol"], row["tf"], row["regime"])].append(row)

    output: list[dict[str, Any]] = []
    for (symbol, tf, regime), cohort_rows in cohorts.items():
        verdicts = evaluate_frame_gate(
            cohort_rows,
            min_n=min_strategy_n,
            bootstrap_max_n=bootstrap_max_n,
            bootstrap_batch=bootstrap_batch,
            bootstrap_random_state=bootstrap_random_state,
            group_key=lambda row: (row["alpha_score_decile"], row["regime"]),  # noqa: B023
            min_clusters=None,
        )

        by_decile: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in cohort_rows:
            by_decile[row["alpha_score_decile"]].append(row)

        decile_means = {
            decile: float(np.mean([r["pnl_r"] for r in decile_rows]))
            for decile, decile_rows in by_decile.items()
        }
        ic_alpha_score_corr = _ic_alpha_score_corr(decile_means)

        for verdict in verdicts:
            # Remap per STEP 0's verified round-trip: verdict["tf"] carries the decile
            # (group_key's first element), verdict["regime"] carries the regime (group_key's
            # second element) -- never the literal tf/regime the field names would suggest.
            alpha_score_decile = verdict["tf"]
            verdict_regime = verdict["regime"]
            sample_n = verdict["n_frames"]

            if sample_n < min_strategy_n:
                continue

            decile_rows = by_decile[alpha_score_decile]
            decile_rows_sorted = sorted(decile_rows, key=lambda r: r["bar_ts"])
            pnl_r_ordered = [r["pnl_r"] for r in decile_rows_sorted]
            bar_ts_ordered = [r["bar_ts"] for r in decile_rows_sorted]

            output.append(
                {
                    "symbol": symbol,
                    "tf": tf,
                    "regime": verdict_regime,
                    "alpha_score_decile": alpha_score_decile,
                    "sample_n": sample_n,
                    "n_clusters": verdict["n_clusters"],
                    "win_rate": _win_rate(pnl_r_ordered),
                    "sharpe_annualized": _annualized_sharpe(pnl_r_ordered, bar_ts_ordered),
                    "max_drawdown": _max_drawdown(np.array(pnl_r_ordered)),
                    "ic_alpha_score_corr": ic_alpha_score_corr,
                    "ci_lower": verdict["ci_lower"],
                    "ci_upper": verdict["ci_upper"],
                }
            )

    return output


class AlphaScorer(BaseBatch):
    """Batch compute service: alpha_frames -> alpha_strategy_scores.

    Aggregates closed primary alpha_frames into per-(symbol, tf, regime, alpha_score_decile)
    diagnostic cells, reusing counterfactual_tracker.evaluate_frame_gate for the day-clustered
    bootstrap CI (no new statistics). See module docstring for the group-key shape constraint.
    """

    job_name = "alpha-scorer"
    compute_version = "1.0.0"

    def __init__(
        self,
        db_dsn: str,
        symbols: list[str] | None = None,
        tfs: list[str] | None = None,
    ) -> None:
        super().__init__(db_dsn)
        self._symbols = symbols
        self._tfs = tfs

    async def execute(self, pool: asyncpg.Pool) -> None:
        try:
            await self._execute_inner(pool)
        except Exception as error:  # CLAUDE.md: exception variable name is `error`
            self.logger.error("alpha_scorer.failed", error=str(error))
            raise

    async def _execute_inner(self, pool: asyncpg.Pool) -> None:
        run_ts = datetime.now(UTC)
        self.logger.info("alpha_scorer.run_ts_locked", run_ts=str(run_ts))

        async with pool.acquire() as conn:
            apr_cfg = await load_apr_dict_async(conn, extra_like_patterns=["alpha.scoring.%"])
            min_strategy_n = cfg(apr_cfg, "alpha.scoring.min_strategy_n", 30)
            bootstrap_max_n = cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000)
            bootstrap_batch = cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000)
            bootstrap_random_state = cfg(apr_cfg, "alpha.scoring.bootstrap_random_state", 42)

            rows = [
                dict(r) for r in await conn.fetch(_ALPHA_SCORE_DECILE_SQL, self._symbols, self._tfs)
            ]

        self.logger.info(
            "alpha_scorer.rows_fetched",
            n_rows=len(rows),
            symbols=self._symbols,
            tfs=self._tfs,
        )
        if not rows:
            self.logger.warning("alpha_scorer.no_rows_matched")
            return

        cells = score_cells(
            rows,
            min_strategy_n=min_strategy_n,
            bootstrap_max_n=bootstrap_max_n,
            bootstrap_batch=bootstrap_batch,
            bootstrap_random_state=bootstrap_random_state,
        )
        self.logger.info("alpha_scorer.cells_scored", n_cells_written=len(cells))

        if not cells:
            self.logger.warning("alpha_scorer.no_cells_cleared_min_strategy_n")
            return

        async with pool.acquire() as conn:
            async with conn.transaction():
                for cell in cells:
                    await conn.execute(
                        _INSERT_SQL,
                        cell["symbol"],
                        cell["tf"],
                        cell["regime"],
                        cell["alpha_score_decile"],
                        cell["sample_n"],
                        cell["n_clusters"],
                        cell["win_rate"],
                        cell["sharpe_annualized"],
                        cell["max_drawdown"],
                        cell["ic_alpha_score_corr"],
                        cell["ci_lower"],
                        cell["ci_upper"],
                        self.compute_version,
                        run_ts,
                    )

        self.logger.info("alpha_scorer.completed", n_rows_written=len(cells))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="AlphaScorer manual/on-demand oneshot -- writes alpha_strategy_scores"
    )
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--tf", nargs="*", dest="tfs", default=None)
    args = parser.parse_args()

    settings = Settings()

    if args.symbols:
        active_symbols = {i.symbol for i in get_active_contracts(settings)}
        invalid = set(args.symbols) - active_symbols
        if invalid:
            raise ValueError(
                f"--symbols contains inactive/unknown symbols: {sorted(invalid)}. "
                f"Active symbols: {sorted(active_symbols)}"
            )

    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    await AlphaScorer(db_dsn=db_dsn, symbols=args.symbols, tfs=args.tfs).run()


if __name__ == "__main__":
    asyncio.run(main())
