#!/usr/bin/env python3
"""Todo 367's substantive remainder (workstream 0c,
docs/plans/2026-09-02-personal-scale-edge-determination-plan.md): place Phase 148's
Gate-1-passing per-symbol directional construction (ensemble `alpha_score`) against
the 0b personal hurdle. Pure paper placement -- consumes existing measured numbers
only, no new measurement runs.

Inputs (all existing, all read-only):
- Gate 1 per-cell OOS rank-ICs: gate_evaluations evidence (gate_id='gate1_signal',
  run 2026-07-22), 640 (symbol, tf, scale) cells, 5m/15m, OOS from 2025-12-24.
- Horizon bars per (tf, scale): APR keys alpha.ic.lookahead.{tf}.{scale} in config_state.
- The 0b hurdle formula and constants (personal_cost_hurdle.py): sigma 16%,
  commission 0.7 bp/side, spread band 0.7/1.4/2.8 bp around the measured 1.4 bp live
  anchor.
- Todo 277's measured sign-co-firing degeneracy: same-direction concurrency 100.0%
  at 15m (1,721 OOS bars) / 100.0% 1h / 100.0% 1d / 99.6% 5m -> the raw construction
  is ONE systematic directional bet per rebalance, not universe_breadth independent
  bets. Bets band {1, 2}: 1 is the measured value, 2 is pure generosity.
- Turnover band {0.08, 0.45} per side: alpha_score's own turnover is unmeasured; the
  band's endpoints are the program's two measured anchors -- 0.08 is the LOWEST 0b
  turnover of any measured feature (ctf_momentum at H=1, a daily feature), 0.45 is
  pre-registration 1's measured quintile-construction turnover at 1d H=5. An intraday
  sign construction cannot credibly sit below the slowest daily feature; if it clears
  nothing even at 0.08, the verdict does not depend on the missing measurement.
- Gate 2's realized gross OOS frame P&L (2026-07-22 promotion decision): mean
  -0.1215 R, Sharpe 0.385, max-dd ratio 9.60 across 33,892 frames / 69 OOS days --
  gross of personal trading costs. A negative-gross-edge construction has no positive
  edge for a lower cost hurdle to rescue; recorded as the primary structural fact.

IC flavor mapping, stated: the 0c screen placed pooled CROSS-SECTIONAL ICs; Gate 1
measured per-symbol TIME-SERIES rank ICs. For a bets~1 systematic directional call
the per-bet IC IS a time-series quantity (the bet is "the market rises"), and each
symbol's return is a noisy proxy of the market, so the all-symbol mean of Gate 1's
per-cell ICs is the flavor-consistent placement. Two estimates are reported:
  - all-cell mean (PRIMARY, unbiased -- no selection on significance)
  - qualifying-cell mean (shown for transparency; selection-inflated by construction,
    140 cells cherry-picked from 640 by BH-FDR -- the exact multiple-comparisons trap
    the program's discipline exists to catch; NOT a valid placement number)

Accounting (identical to the 0c screen's, personal_edge_paper_screen.py):
  H_days        = lookahead_bars * bar_minutes / 390   (equity ETF session)
  bets_annual   = bets_per_rebalance * (252 / H_days) * autocorr_discount
  drag_annual   = (252 / H_days) * 2 * turnover * (spread/2 + commission)
  IC_min        = drag_annual / (sigma * sqrt(bets_annual))
Verdict = worst case across ALL bands (spread x discount x turnover x bets), same
rule as the screen. A KILL is robust iff the measured IC also fails the BEST-case
IC_min (the construction's most favorable admissible combination).

Read-only. No writes. The verdict lands in concept_registry domain='construction'
via migration after this run, per the program's governance rule.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from scripts.analysis.personal_cost_hurdle import (  # noqa: E402
    _COMMISSION_FRAC,
    _SIGMA_TARGET,
    _SPREAD_SENSITIVITY_BAND,
)
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_BAR_MINUTES = {"5m": 5.0, "15m": 15.0}
_SESSION_MINUTES = 390.0
_TRADING_DAYS = 252.0
_BETS_PER_REBALANCE = (1.0, 2.0)  # todo 277 measured ~1 (100% same-direction co-firing)
_AUTOCORR_DISCOUNTS = (1.0, 0.5)  # same band as the 0c screen
_TURNOVER_BAND = (0.08, 0.45)  # program's two measured turnover anchors
_LIVE_SPREAD_ANCHOR = 0.00014  # 1.4 bp, measured 0b (live-quote cache median 0.000138)

# Gate 2 realized gross OOS frame P&L (docs/plans/archive/2026-07-22-phase148-promotion-decision.md)
_GATE2 = {
    "mean_pnl_r": -0.1214896346368989,
    "sharpe": 0.38512018365944,
    "max_dd_ratio": 9.596266492204732,
    "n_frames": 33_892,
    "oos_days": 69,
}
# Todo 277 measured OOS sign-co-firing (alpha_events, bar_ts >= 2025-12-24)
_COFIRING = {"5m": 0.996, "15m": 1.000, "1h": 1.000, "1d": 1.000}
# Todo 277 diagnostic-tier pooled Pearson ICs at 15m (raw vs cross-sectionally demeaned)
_277_POOLED_IC = {"raw": -0.00129, "residual": 0.00453}
_SCALE_ORDER = ["fast", "mid", "slow", "extended"]


def _gate1_cells(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT evidence::text FROM gate_evaluations "
            "WHERE gate_id = 'gate1_signal' ORDER BY run_ts DESC LIMIT 1"
        )
        row = cur.fetchone()
    if not row:
        raise SystemExit("no gate1_signal row in gate_evaluations")
    return json.loads(row[0])["cells"]


def _lookaheads(conn) -> dict[tuple[str, str], int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state "
            "WHERE config_key LIKE 'alpha.ic.lookahead.5m.%' "
            "   OR config_key LIKE 'alpha.ic.lookahead.15m.%'"
        )
        out = {}
        for key, value in cur.fetchall():
            _, _, _, tf, scale = key.split(".")
            out[(tf, scale)] = int(value)
    return out


def _ic_min_bands(h_days: float) -> tuple[float, float]:
    """(best, worst) IC_min across every admissible band combination."""
    rebalances = _TRADING_DAYS / h_days
    values = []
    for spread_mult in _SPREAD_SENSITIVITY_BAND:
        spread = _LIVE_SPREAD_ANCHOR * spread_mult
        one_way = spread / 2 + _COMMISSION_FRAC
        for turnover in _TURNOVER_BAND:
            drag = rebalances * 2 * turnover * one_way
            for bets in _BETS_PER_REBALANCE:
                for discount in _AUTOCORR_DISCOUNTS:
                    bets_annual = bets * rebalances * discount
                    values.append(drag / (_SIGMA_TARGET * np.sqrt(bets_annual)))
    return min(values), max(values)


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    cells = _gate1_cells(conn)
    lookaheads = _lookaheads(conn)
    conn.close()

    print("Phase 148 construction vs the 0b personal hurdle (paper placement, todo 367)")
    print("=" * 112)
    print(
        f"Gross-edge reality first: Gate 2 realized OOS frame P&L is NEGATIVE gross of\n"
        f"personal costs -- mean {_GATE2['mean_pnl_r']:.4f} R, Sharpe {_GATE2['sharpe']:.3f},\n"
        f"max-dd ratio {_GATE2['max_dd_ratio']:.2f} over {_GATE2['n_frames']:,} frames /\n"
        f"{_GATE2['oos_days']} OOS days. A lower cost hurdle cannot rescue a construction\n"
        f"whose gross mean return is negative; 0b's 'wrong trader' insight only creates room\n"
        f"for slow low-IC constructions with POSITIVE gross edge.\n"
    )
    print(
        "Sign-co-firing (todo 277, measured): "
        + ", ".join(f"{tf} {pct:.1%}" for tf, pct in _COFIRING.items())
        + "\n-> ONE systematic directional bet per rebalance (bets band 1-2, measured 1)."
    )
    print(
        f"Todo 277 pooled IC at 15m (diagnostic tier): raw {_277_POOLED_IC['raw']:+.5f}, "
        f"demeaned residual {_277_POOLED_IC['residual']:+.5f} (residual thread = workstream 2,\n"
        f"unaffected by this placement of the RAW construction).\n"
    )

    header = (
        f"{'tf':4s} {'scale':9s} {'bars':>4s} {'H_days':>7s} {'rebal/yr':>8s} "
        f"{'IC_all':>7s} {'IC_qual':>7s} {'ICmin_best':>10s} {'ICmin_worst':>11s} "
        f"{'all/best':>8s} {'verdict':>10s}"
    )
    print(header)
    for tf in ("5m", "15m"):
        for scale in _SCALE_ORDER:
            subset = [c for c in cells if c["tf"] == tf and c["scale"] == scale]
            reliable = [c for c in subset if c.get("reliable")]
            qualifying = [
                c for c in reliable if c.get("passes_fdr") and c.get("ic_ci_lower", -1) > 0
            ]
            ic_all = float(np.mean([c["ic_value"] for c in reliable]))
            ic_qual = (
                float(np.mean([c["ic_value"] for c in qualifying])) if qualifying else float("nan")
            )
            bars = lookaheads[(tf, scale)]
            h_days = bars * _BAR_MINUTES[tf] / _SESSION_MINUTES
            best, worst = _ic_min_bands(h_days)
            rebalances = _TRADING_DAYS / h_days
            margin_best = ic_all / best
            verdict = "KILLED" if ic_all < best else ("clears-best" if ic_all < worst else "CLEARS")
            print(
                f"{tf:4s} {scale:9s} {bars:4d} {h_days:7.4f} {rebalances:8.0f} "
                f"{ic_all:7.4f} {ic_qual:7.4f} {best:10.4f} {worst:11.4f} "
                f"{margin_best:8.2f}x {verdict:>10s}"
            )

    print(
        "\nReading: IC_all = all-reliable-cell mean (unbiased, PRIMARY). IC_qual =\n"
        "qualifying-cell mean (selection-inflated, shown for transparency only).\n"
        "ICmin_best = the construction's MOST favorable admissible band (0.7bp spread,\n"
        "0.08 turnover, 2 bets, 1.0 discount); ICmin_worst = the screen's worst-case rule.\n"
        "KILLED = the unbiased IC fails even the most favorable band, so the verdict does\n"
        "not depend on any unmeasured band choice."
    )


if __name__ == "__main__":
    main()
