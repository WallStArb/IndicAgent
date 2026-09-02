#!/usr/bin/env python3
"""Workstream 0c (todo 367) of
docs/plans/2026-09-02-personal-scale-edge-determination-plan.md: the paper screen.

DESIGN (per user direction 2026-09-02): the ~250-feature library is a FLAT panel of
mostly-primitive, theory-free measurements. No family grouping, no thesis layer: the
theory-free shortlist is every FDR-passing pooled cell the corpus's own ic_engine
measurements already produced. This script enumerates that shortlist and places each
feature against the program's personal hurdle, under STANDALONE accounting per the
user's correction: a signal's edge does not require orthogonality to anything;
correlation only limits combination credit, which is a later, separate question.

Standalone annualized breadth (the accounting 0b's table conservatively omitted):
  bets_annual = universe_breadth x periods_per_year x autocorr_discount
  IC_min      = drag_annual / (sigma x sqrt(bets_annual))
Reported at discount 1.0 (optimistic) and 0.5 (conservative), and across the 0b spread
sensitivity band, so the verdict shown for each feature is the WORST case across all
bands: a feature marked CLEARS survives every assumption simultaneously.

Robustness column: distinct symbols where the feature's per-symbol IC itself clears
zero (ci_lower > 0, reliable) -- pooled FDR can be carried by a few names; standalone
tradeability needs the edge to be broad, not just significant.

Read-only. No writes (construction verdicts land in concept_registry later, when actual
constructions are proposed, per the program's governance rule).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.analysis.personal_cost_hurdle import (  # noqa: E402
    _COMMISSION_FRAC,
    _HORIZONS,
    _SIGMA_TARGET,
    _SPREAD_SENSITIVITY_BAND,
)
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_UNIVERSE_BREADTH = (4.5, 8.4)
_AUTOCORR_DISCOUNTS = (1.0, 0.5)
_LIVE_SPREAD_ANCHOR = 0.0014  # 1.4 bps, measured 0b (20 live top-of-book quotes; CS estimator
# failed validation and was declared unusable -- see program doc). Band = anchor x multipliers.
_MIN_SYMBOL_SUPPORT = 10  # a standalone candidate needs the edge on >= this many names
_TURNOVER_FALLBACK = {1: 0.16, 2: 0.16, 5: 0.17, 10: 0.17}  # measured 0b values (range_to_close,
# the near-horizon-independent profile); ctf_momentum's H10=0.23 is covered by the
# worst-case-across-bands rule below.


def _ic_min(horizon: int, turnover: float, spread: float, discount: float) -> tuple[float, float]:
    """Worst-case and best-case standalone IC_min across the universe-breadth band."""
    worst = best = None
    for ub in _UNIVERSE_BREADTH:
        bets = ub * (252 / horizon) * discount
        one_way = spread / 2 + _COMMISSION_FRAC
        drag = (252 / horizon) * 2 * turnover * one_way
        icm = drag / (_SIGMA_TARGET * np.sqrt(bets))
        worst = icm if worst is None else max(worst, icm)
        best = icm if best is None else min(best, icm)
    return worst, best


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT feature_name, lookahead_bars,
                   count(*) AS n_cells,
                   avg(ic_value) AS avg_ic,
                   max(ic_value) AS max_ic,
                   count(DISTINCT symbol) AS n_symbols_in_pool
            FROM feature_ic_scores
            WHERE tf = '1d' AND is_pooled AND symbol = 'POOLED'
              AND reliable AND ic_ci_lower > 0 AND passes_fdr
              AND lookahead_bars = ANY(%s)
            GROUP BY feature_name, lookahead_bars
            """,
            (_HORIZONS,),
        )
        pooled = pd.DataFrame(
            cur.fetchall(),
            columns=["feature", "H", "n_cells", "avg_ic", "max_ic", "pool_symbols"],
        )
        cur.execute(
            """
            SELECT feature_name, lookahead_bars, count(DISTINCT symbol) AS support
            FROM feature_ic_scores
            WHERE tf = '1d' AND is_pooled = false
              AND reliable AND ic_ci_lower > 0
              AND lookahead_bars = ANY(%s)
            GROUP BY feature_name, lookahead_bars
            """,
            (_HORIZONS,),
        )
        support = pd.DataFrame(cur.fetchall(), columns=["feature", "H", "support"])
    conn.close()

    df = pooled.merge(support, on=["feature", "H"], how="left")
    df["support"] = df["support"].fillna(0).astype(int)

    # Worst-case spread band x discount: a feature's verdict uses the highest IC_min any
    # admissible assumption combination produces. Spreads = live anchor x band multipliers.
    rows = []
    for _, r in df.iterrows():
        turnover = _TURNOVER_FALLBACK.get(int(r["H"]), 0.17)
        ic_mins = []
        for spread_mult in _SPREAD_SENSITIVITY_BAND:
            for discount in _AUTOCORR_DISCOUNTS:
                worst, _ = _ic_min(
                    int(r["H"]), turnover, _LIVE_SPREAD_ANCHOR * spread_mult, discount
                )
                ic_mins.append(worst)
        ic_min_worst = max(ic_mins)
        rows.append({**r.to_dict(), "ic_min_worst": ic_min_worst})
    df = pd.DataFrame(rows)

    df["clears"] = df["avg_ic"] > df["ic_min_worst"]
    df["margin"] = df["avg_ic"] / df["ic_min_worst"]
    df["verdict"] = np.where(
        ~df["clears"],
        "fails hurdle",
        np.where(
            df["support"] >= _MIN_SYMBOL_SUPPORT, "CLEARS (broad support)", "CLEARS (thin support)"
        ),
    )

    df = df.sort_values(["clears", "margin"], ascending=[False, False])
    out = df[
        [
            "feature",
            "H",
            "avg_ic",
            "max_ic",
            "n_cells",
            "support",
            "ic_min_worst",
            "margin",
            "verdict",
        ]
    ]
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 300)
    print(f"Shortlist: {len(df)} FDR-passing (feature, H) pairs at 1d")
    print(
        "Standalone accounting: bets = universe(4.5-8.4) x periods(252/H) x discount(1.0/0.5); "
        "spread band 0.7/1.4/2.8bp; verdict = worst case across ALL bands.\n"
    )
    print(out.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    broad = df[(df["clears"]) & (df["support"] >= _MIN_SYMBOL_SUPPORT)]
    print(
        f"\nSUMMARY: {len(df)} shortlisted cells; {int(df['clears'].sum())} clear the worst-case "
        f"personal hurdle; {len(broad)} clear with per-symbol support >= {_MIN_SYMBOL_SUPPORT}."
    )
    print(
        "Next per the program's decision rule 2: at most ONE construction gets designed "
        "and pre-registered. Selection among broad-support clearers is by measured margin "
        "AND cross-symbol sign consistency, at the horizon band where the mass sits."
    )


if __name__ == "__main__":
    main()
