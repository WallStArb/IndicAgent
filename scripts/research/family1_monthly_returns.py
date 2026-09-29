"""Family 1 opening plus closing slot book: gross and net P&L by month (reporting, outside the runner).

Weights are the runner's (15m panel, rank / vol, dollar neutral, gross 1 per slot, keep as given,
signal rows 25 and 23), built as `family1_slot_profile.py` builds them. Per session:

- gross: the P&L the book earns on raw prices, sum_j w * ln(exit / entry), opening slot 09:30
  open to 10:00 open of the next session, closing slot 15:30 open to the close;
- e17: the recorded E17 timing statistic on the S1 residual target, for comparison;
- net: gross minus each slot's traded units times its cost per unit (iteration 3: the auction
  leg crosses no spread, so cost per unit is half the continuous-leg median half-spread).

In-sample (scored span ends 2025-12-23); reads no forward span, writes no `research_run` row.
Monthly figures are sums of session bp; percent is of the capital deployed per slot.

    .venv/bin/python scripts/research/family1_monthly_returns.py --spec research/specs/family1_h2.yaml \
        --snapshot logs/research/snapshots/panel_<hash> --cache <dir> --member same_slot_mean20 \
        --keeps 0.5,0.1 --cost-open 1.95 --cost-close 0.85 --start 2024-01-01 --out <json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).parent))

import family1_conviction_gating as gating  # noqa: E402
from family1_slot_profile import CLOSE_ROW, OPEN_ROW, load_residuals  # noqa: E402

from src.intelligence.research import panel as panel_mod  # noqa: E402
from src.intelligence.research.evaluate import trade_mask  # noqa: E402
from src.intelligence.research.runner import _prepare_panel, _vol, compute_members  # noqa: E402
from src.intelligence.research.spec import load_spec_from_file  # noqa: E402
from src.intelligence.research.timing import timing_series  # noqa: E402

ET = "America/New_York"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--member", default="same_slot_mean20")
    ap.add_argument("--keeps", default="0.5,0.1")
    ap.add_argument("--cost-open", type=float, required=True, help="bp per unit traded")
    ap.add_argument("--cost-close", type=float, required=True, help="bp per unit traded")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    spec = load_spec_from_file(Path(args.spec)).model
    panel, _ = _prepare_panel(
        spec, panel_mod.load(Path(args.snapshot)), source_hash=None, symbols=None
    )
    bps = panel.bars_per_session
    n, m_names = panel.open.shape
    bar, fwd_res = load_residuals(spec, panel, Path(args.cache) if args.cache else None)
    member = next(m for m in spec.members if m.name == args.member)
    alpha_all = compute_members(spec, bar, bars_per_session=bps)[member.name]
    vol = _vol(spec, bar, bps)
    cfg = spec.scoring.evaluation_config()
    trade = trade_mask(panel.timestamps, cfg) & panel.valid
    first = pd.to_datetime(panel.timestamps.reshape(-1, bps)[:, 0], utc=True).tz_convert(ET)
    dates = first.tz_localize(None).normalize()
    row_in_session = np.tile(np.arange(bps), n // bps)

    op = panel.open.reshape(-1, bps, m_names)
    cl = panel.close.reshape(-1, bps, m_names)
    raw = np.full((n, m_names), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        raw[np.arange(op.shape[0] - 1) * bps + OPEN_ROW] = np.log(op[1:, 2] / op[1:, 0])
        raw[np.arange(op.shape[0]) * bps + CLOSE_ROW] = np.log(cl[:, bps - 1] / op[:, bps - 2])

    out = []
    for keep in [float(k) for k in args.keeps.split(",")]:
        per_slot = {}
        for slot, row, cost in (
            ("open", OPEN_ROW, args.cost_open),
            ("close", CLOSE_ROW, args.cost_close),
        ):
            alpha = np.where((row_in_session == row)[:, None], alpha_all, np.nan)
            w, has_pos, _ = gating.gated_weights(
                alpha,
                vol,
                keep=keep,
                coverage_floor=spec.construction.coverage_floor,
                direction=float(spec.construction.direction),
            )
            live = has_pos & trade
            gross = np.where(live[:, None], w * np.nan_to_num(raw), 0.0).sum(axis=1)
            units = np.where(live, 2.0 * np.abs(w).sum(axis=1), 0.0)
            e17 = timing_series(
                w,
                np.where((row_in_session == row)[:, None], fwd_res, np.nan),
                has_pos,
                trade,
                bars_per_session=bps,
                warmup_sessions=cfg.warmup_sessions,
                memory_sessions=member.slot_history_sessions,
            )
            per_slot[slot] = pd.DataFrame(
                {
                    "gross": gross.reshape(-1, bps).sum(axis=1) * 1e4,
                    "units": units.reshape(-1, bps).sum(axis=1),
                    "e17": np.nan_to_num(e17) * 1e4,
                    "cost": units.reshape(-1, bps).sum(axis=1) * cost,
                },
                index=dates,
            )
        df = per_slot["open"] + per_slot["close"]
        df["net"] = df["gross"] - df["cost"]
        df = df[(df.index >= args.start) & (df["units"] > 0)]
        monthly = df.groupby(df.index.to_period("M")).agg(
            sessions=("gross", "size"),
            gross_bp=("gross", "sum"),
            net_bp=("net", "sum"),
            e17_bp=("e17", "sum"),
            units=("units", "mean"),
        )
        daily_sd = df["gross"].std(ddof=1)
        summary = {
            "keep": keep,
            "member": member.name,
            "names": m_names,
            "sessions": int(len(df)),
            "gross_bp_per_session": float(df["gross"].mean()),
            "net_bp_per_session": float(df["net"].mean()),
            "gross_sharpe": float(df["gross"].mean() / daily_sd * np.sqrt(252)),
            "net_sharpe": float(df["net"].mean() / df["net"].std(ddof=1) * np.sqrt(252)),
            "units_per_session": float(df["units"].mean()),
            "months": [
                {"month": str(p), **{k: float(v) for k, v in r.items()}}
                for p, r in monthly.iterrows()
            ],
        }
        print(json.dumps({k: v for k, v in summary.items() if k != "months"}), flush=True)
        print(monthly.round(1).to_string(), flush=True)
        out.append(summary)
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
