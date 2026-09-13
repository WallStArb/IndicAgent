#!/usr/bin/env python3
"""Near-free due-diligence screen, proposed but never executed in
docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md ("Construction:
time-series (absolute) momentum, multi-asset-class" section): "query existing momentum
features' per-symbol IC broken out by asset_class before building anything new."

NOT a construction falsification and NOT a pre-registration -- this is a SCREEN, the same
status as personal_edge_paper_screen.py (0c): it shortlists, it does not verdict. Every
construction this program has actually falsified so far (range_pct_fast_xs_ls_h5,
alpha_score_residual_single_security_15m, phase148) tested cross-sectional RELATIVE VALUE
(rank symbols against each other, go long/short the extremes). This script asks a
structurally different question that has never been asked in this corpus: does a symbol's
OWN past momentum predict that SAME symbol's OWN future return (time-series/absolute
momentum, the TSMOM framing) -- no cross-sectional ranking, no basket construction, and
therefore no exposure to the beta-contamination failure mode that killed both prior
cross-sectional attempts (range_pct_fast: beta=1.14/R2=0.75; raw alpha_score: 100% sign
co-firing).

Segmented single-name-equity vs ETF (128 vs 103 of 231 active symbols,
instrument_tags.tag='single_name_equity') because the companion diagnostic
(range_pct_fast_beta_by_universe_composition.py) found the pooled DEAD verdict's beta
contamination was disproportionately an ETF-subset property (ETF beta 1.31/R2 0.82 vs
single-name 0.91/R2 0.44) -- if a real per-symbol signal exists in this corpus, the
single-name subset is the more plausible place to find it uncontaminated.

Signal: ctf_momentum (the momentum family's canonical member per this program's own
convention -- see docs/plans/2026-09-02-personal-scale-edge-determination-plan.md, 0a
results). Horizon: H=5 (alpha.ic.lookahead.mid), matching 0a's own reported peak-signal-
mass horizon band. Return: forward_returns.return_mid / return_type='executable_open_to_open'
(Invariant 1). IS window only (bar_ts < alpha.validation.oos_start) -- this program has
never touched the OOS holdout with anything but a one-shot gate look, and this screen
doesn't get one either.

Per-symbol statistic: Spearman IC of (ctf_momentum_t, return_mid_t) over that symbol's own
full IS time series -- literally the definition of "does this symbol's own signal predict
its own future," the TSMOM question. Null: ic_math._circular_shift_null (per-symbol
circular shift of the return series, N=1000) -- preserves each symbol's own
autocorrelation structure, matches this program's established per-symbol null convention
(e.g. alpha_score_residual_single_security_15m's per-symbol family null). BH-FDR across
each subset's own symbol family, alpha=0.05.

Read-only. No writes -- a screen shortlists, it does not verdict; nothing lands in
concept_registry unless a construction is later pre-registered off this shortlist, per
the program's own governance rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.rng import hash_key_to_int  # noqa: E402
from src.intelligence.statistics.ic_math import _circular_shift_null, apply_bh_fdr  # noqa: E402

_MIN_ROWS_PER_SYMBOL = 100  # matches this program's own single-security-diagnostic floor
_N_NULL = 1000
_ALPHA = 0.05
_SCREEN_NAME = "tsmom_per_symbol_ic_screen"


def _per_symbol_ic(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for symbol, g in df.groupby("symbol", sort=False):
        if len(g) < _MIN_ROWS_PER_SYMBOL:
            continue
        x = g["ctf_momentum"].to_numpy()
        y = g["ret"].to_numpy()
        observed, _ = spearmanr(x, y)
        if not np.isfinite(observed):
            continue
        null_draws = np.empty(_N_NULL)
        for i in range(_N_NULL):
            y_shift = _circular_shift_null(y, rng)
            null_draws[i], _ = spearmanr(x, y_shift)
        null_draws = null_draws[np.isfinite(null_draws)]
        if len(null_draws) < 0.5 * _N_NULL:
            continue
        p = (1 + int((null_draws >= observed).sum())) / (len(null_draws) + 1)
        rows.append({"symbol": symbol, "ic": observed, "p": p, "n": len(g)})
    return pd.DataFrame(rows)


def _report(label: str, panel: pd.DataFrame, rng: np.random.Generator) -> None:
    per_symbol = _per_symbol_ic(panel, rng)
    if per_symbol.empty:
        print(f"\n{label}: no symbols cleared the row-count floor")
        return
    rejected, adj_p = apply_bh_fdr(per_symbol["p"].tolist(), _ALPHA)
    per_symbol["passes_fdr"] = rejected
    per_symbol["adj_p"] = adj_p
    n_qualify = int((per_symbol["passes_fdr"] & (per_symbol["ic"] > 0)).sum())
    n_family = len(per_symbol)
    print(
        f"\n{label}: {n_family} symbols tested, mean IC {per_symbol['ic'].mean():+.4f}, "
        f"median IC {per_symbol['ic'].median():+.4f}"
    )
    print(
        f"  BY/BH-FDR qualifying (positive, alpha={_ALPHA}): {n_qualify}/{n_family} "
        f"({100 * n_qualify / n_family:.1f}%)"
    )
    top = per_symbol.sort_values("ic", ascending=False).head(5)
    print("  top 5 by IC:")
    for _, r in top.iterrows():
        print(
            f"    {r['symbol']:<8} ic={r['ic']:+.4f}  p={r['p']:.4f}  "
            f"adj_p={r['adj_p']:.4f}  n={int(r['n'])}"
        )


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_value FROM config_state WHERE config_key = 'alpha.validation.oos_start'"
        )
        row = cur.fetchone()
        if not row or not row[0]:
            raise RuntimeError("alpha.validation.oos_start APR key missing/empty, refusing to run")
        oos_start = pd.Timestamp(row[0])

        cur.execute(
            """
            SELECT fv.bar_ts, fv.symbol, fv.ctf_momentum, fr.return_mid
            FROM feature_vectors fv
            JOIN forward_returns fr
              ON fr.symbol = fv.symbol AND fr.bar_ts = fv.bar_ts AND fr.tf = fv.tf
             AND fr.return_type = 'executable_open_to_open' AND fr.complete_mid = true
            WHERE fv.tf = '1d'
              AND fv.ctf_momentum IS NOT NULL
              AND fv.bar_ts < %s
            """,
            (oos_start,),
        )
        panel = pd.DataFrame(
            cur.fetchall(), columns=["bar_ts", "symbol", "ctf_momentum", "return_mid"]
        )

        cur.execute("SELECT DISTINCT symbol FROM instrument_tags WHERE tag = 'single_name_equity'")
        single_name_symbols = {r[0] for r in cur.fetchall()}
    conn.close()

    if panel.duplicated(["bar_ts", "symbol"]).any():
        raise RuntimeError("panel fan-out: (bar_ts, symbol) not unique after JOIN")
    panel["ret"] = np.expm1(panel["return_mid"].to_numpy())

    all_symbols = set(panel["symbol"].unique())
    etf_symbols = all_symbols - single_name_symbols
    print(f"panel rows: {len(panel):,}  symbols: {len(all_symbols)}")
    print(
        f"universe: {len(single_name_symbols & all_symbols)} single-name, "
        f"{len(etf_symbols)} ETF"
    )

    rng = np.random.default_rng(hash_key_to_int(f"{_SCREEN_NAME}_null"))
    _report("pooled (all symbols)", panel, rng)
    _report(
        "single-name-only",
        panel[panel["symbol"].isin(single_name_symbols)],
        rng,
    )
    _report("ETF-only", panel[panel["symbol"].isin(etf_symbols)], rng)

    print(
        "\nScreen only -- shortlists, does not verdict (0c's own convention). A "
        "qualifying fraction here is the trigger for designing a real pre-registered "
        "TSMOM falsification (vol-scaling, position sizing, cost bands, bootstrap CI, "
        "stability), not a construction verdict itself."
    )


if __name__ == "__main__":
    main()
