#!/usr/bin/env python3
"""S1 grouping comparison: sector labels against causal price clusters (the FactorSpec
docstring's table). Read-only; runs on a saved 1d Panel (research.panel.save) and reports, over
2013 onward: residual breadth (participation ratio), within-label-group residual correlation
for label groups of at least 5 names and for the near-duplicate groups of 2-4 names, and for
clusters the within-cluster residual correlation over the 252 sessions after each refit.

The label arm uses today's labels as captured in the panel, so it has look-ahead the cluster
arm does not; the label yardstick also favors the label arm (it scores it on its own groups).
"""

from __future__ import annotations

import argparse
import functools
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from scripts.analysis.residual_breadth_diagnostic import breadth, group_ids  # noqa: E402
from src.intelligence.research import panel as panel_mod  # noqa: E402
from src.intelligence.research.factors import FactorSpec, residual_returns  # noqa: E402
from src.intelligence.statistics.correlation import pairwise_corr  # noqa: E402

_MIN_COVERAGE = 0.8
_BAND = 0.15
_NEXT_YEAR = 252


def label_grouping(labels, r_w, market_x, min_rows, min_size):
    return group_ids(labels, min_size)


def within(res: np.ndarray, members: list[int]) -> float | None:
    x = res[:, members]
    ok = np.isfinite(x).all(axis=1)
    if ok.sum() < _NEXT_YEAR or len(members) < 2:
        return None
    return float(np.corrcoef(x[ok].T)[np.triu_indices(len(members), 1)].mean())


def report(name: str, res: np.ndarray, labels: tuple[str, ...], recent: np.ndarray) -> None:
    rec = res[recent]
    keep = np.isfinite(rec).mean(axis=0) >= _MIN_COVERAGE
    b = breadth(pairwise_corr(rec[:, keep], 100))
    size = Counter(labels)
    big, small = [], []
    for lab, n in size.items():
        if not lab or n < 2:
            continue
        v = within(rec, [i for i, x in enumerate(labels) if x == lab])
        if v is not None:
            (big if n >= 5 else small).append(v)
    print(
        f"{name:16s} breadth {b['n_eff']:6.1f} | label groups >=5: mean {np.mean(big):+.3f} "
        f"max|.| {np.max(np.abs(big)):.3f} | groups of 2-4: mean {np.mean(small):+.3f} "
        f"max {np.max(small):+.3f} outside {sum(abs(v) > _BAND for v in small)}/{len(small)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("panel", type=Path, help="saved 1d panel directory")
    parser.add_argument("--since", default="2013-01-01")
    args = parser.parse_args()
    p = panel_mod.load(args.panel)
    if not p.sectors:
        raise SystemExit("panel has no captured sectors")
    r = panel_mod.bar_returns(p)
    recent = p.timestamps >= np.datetime64(args.since)
    spec = FactorSpec()
    labels = p.sectors
    report(
        "labels min 5",
        residual_returns(r, spec=spec, grouping=functools.partial(label_grouping, labels)).residual,
        labels,
        recent,
    )
    for min_size in (5, 10):
        fit = residual_returns(r, spec=FactorSpec(min_group_size=min_size))
        report(f"clusters min {min_size}", fit.residual, labels, recent)
        start = int(np.argmax(recent))
        vals = []
        for p_row, g in zip(fit.refit_rows, fit.groups):
            if p_row < start:
                continue
            nxt = fit.residual[p_row : p_row + _NEXT_YEAR]
            for gid in np.unique(g[g >= 0]):
                v = within(nxt, list(np.flatnonzero(g == gid)))
                if v is not None:
                    vals.append(v)
        print(
            f"  within-cluster residual corr, next {_NEXT_YEAR} sessions: mean {np.mean(vals):+.3f} "
            f"p5 {np.percentile(vals, 5):+.3f} p95 {np.percentile(vals, 95):+.3f} n {len(vals)}"
        )


if __name__ == "__main__":
    main()
