#!/usr/bin/env python3
"""Cost-assumption sensitivity check on the already-verdicted `range_pct_fast_xs_ls_h5`
pooled DEAD verdict (2026-09-02), prompted by a direct user challenge 2026-09-13:
"execution costs are near free... we should assume minimal costs."

NOT a new pre-registration or a re-run presented as a fresh verdict -- this recomputes
the ORIGINAL pre-registered PASS rule (all three criteria, same locked methodology:
`_build_phase`, `_block_bootstrap_mean`, `_shuffled_null` imported unchanged from
range_pct_fast_xs_ls_h5_falsification.py) under ONE additional cost assumption:
commission fully zeroed (both the per-share rate and the $0.35/order minimum), holding
spread and borrow at their ORIGINAL measured/pre-registered values.

Why commission specifically, and why spread/borrow are NOT also zeroed: commission is
a broker fee -- genuinely can approach zero on a modern zero-commission plan. Spread
(1.4bp live-measured median bid-ask) is NOT a broker fee -- it is the real cost of
crossing the market when taking liquidity, a function of market microstructure, and
exists regardless of commission plan. Borrow cost on the short leg is a stock-loan fee,
also independent of trading-commission structure. "Minimal execution costs" legitimately
zeros commission; it does not make the bid-ask spread or borrow fee disappear.

This is a robustness check on an existing verdict, same status as
range_pct_fast_beta_by_universe_composition.py and the AGY-reviewed Pre-registration 3
that followed it -- if the PASS rule flips under this cost assumption, that is a real,
consequential finding requiring its own concept_registry treatment, not something to
report casually. If it does not flip, this closes the "was commission driving the DEAD
verdict" question for good.

Read-only. No writes -- verdict-consequential only if the PASS rule actually flips.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.analysis.range_pct_fast_xs_ls_h5_falsification import (  # noqa: E402
    _ANCHOR_BORROW,
    _BLOCK_REBALANCES,
    _BORROW_BAND,
    _CONSTRUCTION,
    _LIVE_SPREAD_ANCHOR,
    _N_BOOT,
    _N_NULL,
    _N_SUBPERIODS,
    _QUINTILE,
    _SPREAD_MULTIPLIERS,
    _block_bootstrap_mean,
    _build_phase,
    _load_apr,
    _shuffled_null,
)
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.rng import hash_key_to_int  # noqa: E402


def _drag_zero_commission(phase, spread: float, borrow: float) -> np.ndarray:
    """Identical to the original _drag() except commission_frac is forced to 0 --
    the ONLY change from the pre-registered cost model."""
    return 2.0 * phase.turnover * (spread / 2.0 + 0.0) + borrow


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
            WHERE fv.tf = '1d' AND fv.range_pct_fast IS NOT NULL AND fv.bar_ts < %s
            """,
            (oos_start,),
        )
        panel = pd.DataFrame(
            cur.fetchall(), columns=["bar_ts", "symbol", "range_pct_fast", "return_mid"]
        )
    conn.close()

    panel["ret"] = np.expm1(panel["return_mid"].fillna(0.0).to_numpy())
    primary = _build_phase(panel, offset=0)
    boot_rng = np.random.default_rng(hash_key_to_int(f"{_CONSTRUCTION}_zerocomm_boot"))

    print(f"panel: {len(primary.dates)} rebalances, mean turnover {primary.turnover.mean():.3f}")
    print(
        f"neutralization: beta {primary.beta:+.4f}  R2 {primary.r2:.3f}  "
        f"gross mean {primary.gross.mean() * 1e4:+.2f}bp  "
        f"intercept {primary.neutralized.mean() * 1e4:+.2f}bp"
    )

    spread_levels = tuple(_LIVE_SPREAD_ANCHOR * mult for mult in _SPREAD_MULTIPLIERS)
    print(
        "\n--- Criterion (a): neutralized net, ZERO COMMISSION, "
        "block bootstrap CIs (block=2, B=2000) ---"
    )
    pass_a = True
    for spread in spread_levels:
        for borrow in _BORROW_BAND:
            net = primary.neutralized - _drag_zero_commission(primary, spread, borrow)
            m, lo, hi = _block_bootstrap_mean(net, _BLOCK_REBALANCES, _N_BOOT, boot_rng)
            cleared = lo > 0.0
            pass_a = pass_a and cleared
            print(
                f"  spread {spread * 1e4:.1f}bp borrow {borrow * 1e4:.2f}bp: "
                f"mean {m * 1e4:+.2f}bp  CI [{lo * 1e4:+.2f}, {hi * 1e4:+.2f}]bp  "
                f"lower>0: {'YES' if cleared else 'NO'}"
            )

    # --- shuffled null on GROSS (cost-independent -- commission assumption cannot
    # change this; recomputed only for completeness, identical to the original run) ---
    by_date = {ts: g for ts, g in panel.groupby("bar_ts", sort=False)}
    prepared = [
        (
            by_date[ts]["range_pct_fast"].to_numpy(),
            by_date[ts]["ret"].to_numpy(),
            len(by_date[ts]) // _QUINTILE,
        )
        for ts in primary.dates
    ]
    null_rng = np.random.default_rng(hash_key_to_int(f"{_CONSTRUCTION}_is_null"))
    null_means = _shuffled_null(prepared, null_rng)
    p_null = (1 + int((null_means >= primary.gross.mean()).sum())) / (_N_NULL + 1)
    pass_b = p_null < 0.05
    print(
        f"\n--- Criterion (b): shuffled null on gross (cost-independent, unchanged "
        f"from original run) ---\np = {p_null:.4f}  p<0.05: {'YES' if pass_b else 'NO'}"
    )

    # --- Criterion (c): subperiod stability at ZERO-COMMISSION anchor cost ---
    anchor_net = primary.neutralized - _drag_zero_commission(
        primary, _LIVE_SPREAD_ANCHOR, _ANCHOR_BORROW
    )
    splits = np.array_split(np.arange(len(anchor_net)), _N_SUBPERIODS)
    sub_means = [anchor_net[ix].mean() for ix in splits]
    pass_c = all(s > 0.0 for s in sub_means)
    print("\n--- Criterion (c): subperiod stability, ZERO-COMMISSION anchor cost ---")
    for i, (ix, s) in enumerate(zip(splits, sub_means), 1):
        print(
            f"  subperiod {i}: {primary.dates[ix[0]].date()} .. "
            f"{primary.dates[ix[-1]].date()}  net(zero-comm anchor) mean {s * 1e4:+.2f}bp"
        )
    print(f"  stability (3/3 positive): {'YES' if pass_c else 'NO'}")

    verdict = "PASS" if (pass_a and pass_b and pass_c) else "STILL DEAD"
    print(f"\n{'=' * 70}")
    print(
        f"VERDICT under zero-commission sensitivity: {verdict}  "
        f"(a: {'Y' if pass_a else 'N'}, b: {'Y' if pass_b else 'N'}, c: {'Y' if pass_c else 'N'})"
    )


if __name__ == "__main__":
    main()
