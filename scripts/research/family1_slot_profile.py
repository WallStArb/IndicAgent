"""Family 1 per-slot profile (exploration, outside the runner): gross P&L, turnover and E by
slot subset, keep and member. Reuses the runner's panel, residual, member, volatility and E17
timing code and the iteration 2 gated weights (`family1_conviction_gating.py`).

Signal rows are the last 15m bar before a half-hour slot: row 25 is the opening slot (entry at
the 09:30 open from the prior close), row 23 the closing slot (entry 15:30, exit at the close),
rows 1, 3, ..., 21 the slots starting 10:00 through 15:00. Subsets: `each` (every slot), `open`,
`close`, `open+close`, `all`. Reads no forward span, writes no `research_run` row, is not a
verdict (docs/plans/2026-09-29-family1-iteration-3-open-close-slots.md).

    .venv/bin/python scripts/research/family1_slot_profile.py \
        --spec research/specs/family1_h2.yaml --snapshot logs/research/snapshots/panel_<hash> \
        --cache <dir for residuals> --subsets each,open+close,all --keeps 0.5,0.1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).parent))

import family1_conviction_gating as gating  # noqa: E402

from src.intelligence.research import panel as panel_mod  # noqa: E402
from src.intelligence.research import transforms  # noqa: E402
from src.intelligence.research.evaluate import trade_mask  # noqa: E402
from src.intelligence.research.evidence import turnover_per_session  # noqa: E402
from src.intelligence.research.runner import (  # noqa: E402
    FACTOR_SPECS,
    _prepare_panel,
    _vol,
    compute_members,
    compute_residuals,
)
from src.intelligence.research.spec import load_spec_from_file  # noqa: E402
from src.intelligence.research.timing import timing_series  # noqa: E402

OPEN_ROW, CLOSE_ROW = 25, 23


def subset_rows(name: str, bars_per_session: int) -> tuple[int, ...] | None:
    """Signal-row indices within a session for a named subset (None means every row)."""
    if name == "all":
        return None
    named = {"open": (OPEN_ROW,), "close": (CLOSE_ROW,), "open+close": (OPEN_ROW, CLOSE_ROW)}
    if name not in named:
        raise ValueError(f"unknown subset {name!r}; one of all, each, {sorted(named)}")
    return named[name]


def load_residuals(spec, panel, cache: Path | None):
    if cache and (cache / "bar.npy").exists():
        return np.load(cache / "bar.npy"), np.load(cache / "fwd.npy")
    res = compute_residuals(
        panel,
        horizon=spec.horizon,
        factor_spec=FACTOR_SPECS[spec.factor_spec],
        transform=transforms.resolve(spec.panel.transform),
    )
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        np.save(cache / "bar.npy", res.bar)
        np.save(cache / "fwd.npy", res.fwd)
    return res.bar, res.fwd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--cache", default=None, help="directory caching residuals between runs")
    ap.add_argument("--members", default="same_slot_mean5,same_slot_mean20")
    ap.add_argument("--keeps", default="0.5,0.1")
    ap.add_argument("--subsets", default="each,open+close,all")
    ap.add_argument("--out", default=None, help="write the rows as JSON")
    args = ap.parse_args()

    spec = load_spec_from_file(Path(args.spec)).model
    panel, _ = _prepare_panel(
        spec, panel_mod.load(Path(args.snapshot)), source_hash=None, symbols=None
    )
    bps = panel.bars_per_session
    bar, fwd = load_residuals(spec, panel, Path(args.cache) if args.cache else None)
    members = compute_members(spec, bar, bars_per_session=bps)
    vol = _vol(spec, bar, bps)
    cfg = spec.scoring.evaluation_config()
    trade = trade_mask(panel.timestamps, cfg) & panel.valid
    sess_dates = panel.timestamps.reshape(-1, bps)[:, 0].astype("datetime64[D]")
    row_in_session = np.tile(np.arange(bps), trade.shape[0] // bps)
    print(f"names {len(panel.symbols)} sessions {trade.shape[0] // bps}", flush=True)

    rows = []
    for m in spec.members:
        if m.name not in args.members.split(","):
            continue
        for keep in [float(k) for k in args.keeps.split(",")]:
            w, has_pos, _ = gating.gated_weights(
                members[m.name],
                vol,
                keep=keep,
                coverage_floor=spec.construction.coverage_floor,
                direction=float(spec.construction.direction),
            )
            jobs: list[tuple[str, np.ndarray]] = []
            for name in args.subsets.split(","):
                if name == "each":
                    active = sorted(set(row_in_session[has_pos & trade.any(axis=1)]))
                    jobs += [(f"row{i}", has_pos & (row_in_session == i)) for i in active]
                else:
                    sel = subset_rows(name, bps)
                    jobs.append(
                        (name, has_pos if sel is None else has_pos & np.isin(row_in_session, sel))
                    )
            for label, gate in jobs:
                series = timing_series(
                    w,
                    fwd,
                    gate,
                    trade,
                    bars_per_session=bps,
                    warmup_sessions=cfg.warmup_sessions,
                    memory_sessions=m.slot_history_sessions,
                )
                turn = turnover_per_session(w, gate, trade, bps)
                row = {"member": m.name, "keep": keep, "subset": label}
                row.update(gating.summarize(series, turn, sess_dates, cfg.sub_periods))
                rows.append(row)
                print(json.dumps(row), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
