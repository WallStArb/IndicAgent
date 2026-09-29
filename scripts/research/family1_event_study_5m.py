"""Family 1 opening and closing slot event study at 5m (exploration, outside the runner).

The book's weights are the runner's, built on the 15m panel exactly as
`family1_slot_profile.py` builds them (members same_slot_mean5 and mean20, keep 0.5 and 0.1,
signal rows 25 and 23). They are applied to 5m price paths instead of the 15m target, to see
where inside and just after each slot the P&L accrues:

- opening slot: cumulative log return from the 09:30 open to each 5m bar open from 09:35 to
  11:00 of the entry session (the runner exits at the 10:00 open);
- closing slot: cumulative log return from the 15:00 open to each 5m bar open from 15:05 to
  15:55 and to the 15:55 bar's close (the runner enters at 15:30 and exits at the close). The
  15:00 to 15:30 part is before the runner's entry; its weights carry a volatility scale read
  through 15:30, so that segment is descriptive only.

Returns are raw 5m log returns (no S1 residual exists at 5m); the book is dollar neutral. Each
point's series is the E17 timing series (`timing.timing_series`), the recorded statistic. A
reconciliation row compares the 5m path at the runner's exit with the same raw return from the
15m panel and with the runner's residual target. Missing 5m bars are NaN (no fill), so a name
drops out of a point it has no bar for. Reads no forward span, writes no `research_run` row,
not a verdict (docs/plans/2026-09-29-family1-iteration-4-5m-timing.md).

    .venv/bin/python scripts/research/family1_event_study_5m.py \
        --spec research/specs/family1_h2.yaml --snapshot logs/research/snapshots/panel_<hash> \
        --bars5m <csv: symbol,ts,open,close> --cache <residual cache dir> --out <json>
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
from src.intelligence.research.evidence import turnover_per_session  # noqa: E402
from src.intelligence.research.runner import _prepare_panel, _vol, compute_members  # noqa: E402
from src.intelligence.research.spec import load_spec_from_file  # noqa: E402
from src.intelligence.research.timing import timing_series  # noqa: E402
from src.intelligence.statistics.hac import hac_mean_test  # noqa: E402

ET = "America/New_York"
OPEN_TIMES = [f"{9 + (30 + 5 * k) // 60:02d}:{(30 + 5 * k) % 60:02d}" for k in range(19)]
CLOSE_TIMES = [f"15:{5 * k:02d}" for k in range(12)] + ["16:00"]  # 16:00 = 15:55 bar close


def price_grid(path: Path, symbols, session_dates) -> tuple[np.ndarray, np.ndarray]:
    """[point, session, name] prices for the opening and closing windows, NaN where missing."""
    df = pd.read_csv(path, dtype={"symbol": str, "ts": np.int64, "open": float, "close": float})
    local = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(ET)
    df["date"] = local.dt.tz_localize(None).dt.normalize().to_numpy().astype("datetime64[D]")
    df["hhmm"] = local.dt.strftime("%H:%M")
    sess_idx = pd.Series(np.arange(len(session_dates)), index=pd.Index(session_dates))
    df["s"] = sess_idx.reindex(df["date"].to_numpy()).to_numpy()
    df["j"] = (
        pd.Series(np.arange(len(symbols)), index=pd.Index(symbols)).reindex(df["symbol"]).to_numpy()
    )
    df = df[df["s"].notna() & df["j"].notna()]
    s, j = df["s"].to_numpy(int), df["j"].to_numpy(int)
    grids = []
    for times in (OPEN_TIMES, CLOSE_TIMES):
        g = np.full((len(times), len(session_dates), len(symbols)), np.nan)
        for k, hhmm in enumerate(times):
            if hhmm == "16:00":
                sel = (df["hhmm"] == "15:55").to_numpy()
                g[k, s[sel], j[sel]] = df["close"].to_numpy()[sel]
            else:
                sel = (df["hhmm"] == hhmm).to_numpy()
                g[k, s[sel], j[sel]] = df["open"].to_numpy()[sel]
        grids.append(g)
    return grids[0], grids[1]


def point_fwd(n_rows, bps, row, entry_shift, grid, ref, k):
    """[n_rows, m] forward array holding ln(P[k] / P[ref]) at signal row `row` of each session,
    the price path read from session s + entry_shift; NaN elsewhere."""
    fwd = np.full((n_rows, grid.shape[2]), np.nan)
    s_n = n_rows // bps
    src = np.arange(s_n) + entry_shift
    ok = src < s_n
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.log(grid[k, src[ok]] / grid[ref, src[ok]])
    fwd[np.arange(s_n)[ok] * bps + row] = r
    return fwd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--bars5m", required=True)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--members", default="same_slot_mean5,same_slot_mean20")
    ap.add_argument("--keeps", default="0.5,0.1")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    spec = load_spec_from_file(Path(args.spec)).model
    panel, _ = _prepare_panel(
        spec, panel_mod.load(Path(args.snapshot)), source_hash=None, symbols=None
    )
    bps = panel.bars_per_session
    n = panel.timestamps.shape[0]
    bar, fwd_res = load_residuals(spec, panel, Path(args.cache) if args.cache else None)
    members = compute_members(spec, bar, bars_per_session=bps)
    vol = _vol(spec, bar, bps)
    cfg = spec.scoring.evaluation_config()
    trade = trade_mask(panel.timestamps, cfg) & panel.valid
    first = pd.to_datetime(panel.timestamps.reshape(-1, bps)[:, 0], utc=True).tz_convert(ET)
    session_dates = first.tz_localize(None).normalize().to_numpy().astype("datetime64[D]")
    row_in_session = np.tile(np.arange(bps), n // bps)
    open_grid, close_grid = price_grid(Path(args.bars5m), panel.symbols, session_dates)
    print(f"names {len(panel.symbols)} sessions {n // bps}", flush=True)

    # Raw 15m reconciliation targets at the runner's exits, same rows.
    op = panel.open.reshape(-1, bps, panel.open.shape[1])
    cl = panel.close.reshape(-1, bps, panel.close.shape[1])
    raw15 = {"open": np.full((n, op.shape[2]), np.nan), "close": np.full((n, op.shape[2]), np.nan)}
    with np.errstate(invalid="ignore", divide="ignore"):
        raw15["open"][np.arange(op.shape[0] - 1) * bps + OPEN_ROW] = np.log(op[1:, 2] / op[1:, 0])
        raw15["close"][np.arange(op.shape[0]) * bps + CLOSE_ROW] = np.log(cl[:, 25] / op[:, 24])

    slots = {
        "open": dict(row=OPEN_ROW, shift=1, grid=open_grid, ref=0, times=OPEN_TIMES),
        "close": dict(row=CLOSE_ROW, shift=0, grid=close_grid, ref=0, times=CLOSE_TIMES),
    }
    out = []
    for m in spec.members:
        if m.name not in args.members.split(","):
            continue
        for keep in [float(k) for k in args.keeps.split(",")]:
            for slot, sd in slots.items():
                alpha = np.where((row_in_session == sd["row"])[:, None], members[m.name], np.nan)
                w, has_pos, _ = gating.gated_weights(
                    alpha,
                    vol,
                    keep=keep,
                    coverage_floor=spec.construction.coverage_floor,
                    direction=float(spec.construction.direction),
                )
                turn = turnover_per_session(w, has_pos, trade, bps)

                def stat(fwd, w=w, has_pos=has_pos, m=m, turn=turn):
                    d = timing_series(
                        w,
                        fwd,
                        has_pos,
                        trade,
                        bars_per_session=bps,
                        warmup_sessions=cfg.warmup_sessions,
                        memory_sessions=m.slot_history_sessions,
                    )
                    x = d[np.isfinite(d)]
                    return {
                        "bp": float(x.mean() * 1e4),
                        "E": float(x.mean() * 1e4 / turn),
                        "t": float(hac_mean_test(d).t),
                    }

                base = {"member": m.name, "keep": keep, "slot": slot, "turnover": turn}
                rec = {
                    "residual_runner": stat(
                        np.where(row_in_session[:, None] == sd["row"], fwd_res, np.nan)
                    ),
                    "raw_15m": stat(raw15[slot]),
                }
                print(json.dumps({**base, "reconcile": rec}), flush=True)
                curve = []
                for k in range(1, len(sd["times"])):
                    fwd = point_fwd(n, bps, sd["row"], sd["shift"], sd["grid"], sd["ref"], k)
                    cov = float(np.isfinite(fwd[has_pos & trade]).mean())
                    curve.append({"time": sd["times"][k], "coverage": cov, **stat(fwd)})
                    print(json.dumps({**base, **curve[-1]}), flush=True)
                out.append({**base, "reconcile": rec, "curve": curve})
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
