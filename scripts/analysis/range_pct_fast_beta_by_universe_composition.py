#!/usr/bin/env python3
"""Robustness diagnostic on the already-verdicted `range_pct_fast_xs_ls_h5` construction
(DEAD, 2026-09-02, `concept_registry` domain='construction'; falsification script:
range_pct_fast_xs_ls_h5_falsification.py).

NOT a new pre-registration or a new construction claim. This is a descriptive sidecar in
the same spirit as that script's own "reported, never gated" beta/R^2 output (see its
docstring item 9) -- it answers a single question the original verdict never isolated:
is the market-beta contamination (beta=+1.14, R^2=0.75, pooled) a property of the SIGNAL,
or a property of pooling single-name equities together with basket ETFs in one
cross-sectional ranking? ETFs are mechanically beta-dominated by construction; single
names carry more idiosyncratic variance. If beta/R^2 collapse materially on the
single-name-only subset, the pooled verdict's interpretation needs revisiting. If they
don't, this closes the question for good.

Method: reuses `_build_phase` from the original falsification script UNCHANGED (same
panel query, same eligibility/quintile/tie-break/OLS-neutralization logic) -- the only
difference is the input panel is restricted to a symbol subset before the phase is built,
so within-date eligible-cross-section sizes shrink naturally with the universe, exactly as
the original construction spec requires (no separate min-cross-section override).

Single-name / ETF split: `instrument_tags.tag = 'single_name_equity'` (128 of 231 active
equity symbols per live check 2026-09-12); the remaining 103 are ETFs. No new tagging
introduced.

Read-only. No writes -- this is a diagnostic, not a verdict; nothing lands in
concept_registry.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.analysis.range_pct_fast_xs_ls_h5_falsification import (  # noqa: E402
    _build_phase,
    _load_apr,
)
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)

    with conn.cursor() as cur:
        apr = _load_apr(cur)
        oos_start = pd.Timestamp(apr["alpha.validation.oos_start"])
        cur.execute(
            """
            SELECT fv.bar_ts, fv.symbol, fv.range_pct_fast, fr.return_mid
            FROM feature_vectors fv
            LEFT JOIN forward_returns fr
              ON fr.symbol = fv.symbol AND fr.bar_ts = fv.bar_ts AND fr.tf = fv.tf
             AND fr.return_type = 'executable_open_to_open'
            WHERE fv.tf = '1d'
              AND fv.range_pct_fast IS NOT NULL
              AND fv.bar_ts < %s
            """,
            (oos_start,),
        )
        panel = pd.DataFrame(
            cur.fetchall(), columns=["bar_ts", "symbol", "range_pct_fast", "return_mid"]
        )

        cur.execute("SELECT DISTINCT symbol FROM instrument_tags WHERE tag = 'single_name_equity'")
        single_name_symbols = {r[0] for r in cur.fetchall()}
    conn.close()

    panel["ret"] = np.expm1(panel["return_mid"].fillna(0.0).to_numpy())
    all_symbols = set(panel["symbol"].unique())
    etf_symbols = all_symbols - single_name_symbols
    print(
        f"universe: {len(all_symbols)} symbols total "
        f"({len(single_name_symbols & all_symbols)} single-name, "
        f"{len(etf_symbols)} ETF)"
    )

    subsets = {
        "pooled (sanity check, should reproduce beta~1.14/R2~0.75)": panel,
        "single-name-only": panel[panel["symbol"].isin(single_name_symbols)],
        "ETF-only": panel[panel["symbol"].isin(etf_symbols)],
    }

    print(
        f"\n{'subset':<55} {'rebalances':>10} {'beta':>9} {'R2':>8} "
        f"{'gross_mean_bp':>14} {'neutralized_bp':>15}"
    )
    for label, sub in subsets.items():
        phase = _build_phase(sub, offset=0)
        gross_mean_bp = float(phase.gross.mean()) * 1e4
        neutralized_bp = float(phase.neutralized.mean()) * 1e4
        print(
            f"{label:<55} {len(phase.dates):>10} {phase.beta:>+9.4f} "
            f"{phase.r2:>8.3f} {gross_mean_bp:>14.2f} {neutralized_bp:>15.2f}"
        )
    print(
        "\nDescriptive only: no cost drag, no bootstrap CI, no shuffled null, no "
        "neutralized-net-at-cost figure computed here (deliberately out of scope for a "
        "robustness sidecar). A positive neutralized intercept above is NOT a PASS "
        "signal -- it only says a market-beta OLS fit leaves a positive residual mean; "
        "whether that residual survives personal costs, bootstrap CI, and a shuffled "
        "null is the question a real falsification would answer, not this script."
    )


if __name__ == "__main__":
    main()
