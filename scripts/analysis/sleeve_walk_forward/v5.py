"""V5: canary controls over every S1 refit (pre-registration section 10).

Definitions, pinned 2026-09-24 before any S1 output on the official snapshot was read:

1. Detection. canary_acausal_placebo is ln(close[i+2] / close[i+1]). The executable label for
   lookahead h is ln(open[i+h+1] / open[i+1]), which contains the placebo's whole span only when
   h >= 2; the h = 1 label shares just the overnight gap close[i+1] -> open[i+2]. So the gate is
   the smallest configured lookahead >= 2 (the containing lookahead): at every refit, in every
   pooled row at it that is `reliable`, ic_sign = +1 and ic_ci_lower > 0. One miss fails V5.
   Every lookahead's hit rate is reported. Corrected 2026-09-25 after the first official run:
   the definition pinned 2026-09-24 gated on the fast (h = 1) lookahead on the mistaken premise
   that it contained the placebo, and failed on 12 of 362 small rare-label cells (pre-reg 12.1).
2. Noise rate. The noise canaries (canary_noise_gaussian, canary_noise_uniform,
   canary_near_constant) pooled over every refit: among rows carrying a passes_fdr flag, the
   share with passes_fdr = true must not exceed fdr_alpha, tested one-sided binomial; V5 fails
   when that p < 0.05. Rows of one feature across lookaheads are positively correlated, so the
   binomial test is anti-conservative, the strict direction for this gate. The CI-gate pass
   share is reported, never gating. canary_constant is reported only (a constant has no rank IC).
3. Never weighted. No canary_* feature appears in any refit's fitted equity stratum.

Run: python -m scripts.analysis.sleeve_walk_forward.v5 --in S1.pkl [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scipy.stats import binomtest

from scripts.analysis.sleeve_walk_forward.refit import ic_engine_config
from scripts.analysis.sleeve_walk_forward.results import RefitOutput

PLACEBO = "canary_acausal_placebo"
NOISE = ("canary_noise_gaussian", "canary_noise_uniform", "canary_near_constant")
_TF = "1d"
_P_FAIL = 0.05


def containing_lookahead(lookaheads: list[int]) -> int:
    """Smallest lookahead whose open-to-open label spans the placebo's close[i+1] -> close[i+2]."""
    return min(h for h in lookaheads if h >= 2)


def check_refits(refits: list[RefitOutput], fast: int, fdr_alpha: float) -> dict:
    """`fast` is the gated (containing) lookahead; the name is kept for the report keys."""
    placebo_misses: list[dict] = []
    placebo_by_h: dict[int, list[int]] = {}
    noise = {f: {"n_flagged": 0, "n_fdr": 0, "n_rows": 0, "n_ci": 0} for f in NOISE}
    constant_rows = 0
    weighted: list[dict] = []
    for refit in refits:
        date = str(refit.refit_date)
        for r in refit.ic_rows:
            f = r["feature_name"]
            if f == PLACEBO and r["reliable"] is True:
                h = int(r["lookahead_bars"])
                hit = r["ic_sign"] == 1 and r["ic_ci_lower"] is not None and r["ic_ci_lower"] > 0
                c = placebo_by_h.setdefault(h, [0, 0])
                c[0] += hit
                c[1] += 1
                if h == fast and not hit:
                    placebo_misses.append(
                        {"refit": date, "regime": r["regime"], "ic_value": r["ic_value"]}
                    )
            elif f in NOISE:
                n = noise[f]
                n["n_rows"] += 1
                n["n_ci"] += bool(r.get("passes_ci_gate"))
                if r.get("passes_fdr") is not None:
                    n["n_flagged"] += 1
                    n["n_fdr"] += r["passes_fdr"] is True
            elif f == "canary_constant":
                constant_rows += 1
        for label, s in refit.strata.items():
            bad = [f for f in s.feature_names if f.startswith("canary_")]
            if bad:
                weighted.append({"refit": date, "stratum": label, "features": bad})

    k = sum(n["n_fdr"] for n in noise.values())
    m = sum(n["n_flagged"] for n in noise.values())
    noise_p = binomtest(k, m, fdr_alpha, alternative="greater").pvalue if m else 1.0
    n_placebo_fast = placebo_by_h.get(fast, [0, 0])[1]
    detection_ok = n_placebo_fast > 0 and not placebo_misses
    noise_ok = m > 0 and noise_p >= _P_FAIL
    return {
        "n_refits": len(refits),
        "detection_ok": detection_ok,
        "placebo_fast_cells": n_placebo_fast,
        "placebo_misses": placebo_misses,
        "placebo_hit_rate_by_lookahead": {
            str(h): {"hits": c[0], "cells": c[1]} for h, c in sorted(placebo_by_h.items())
        },
        "noise_ok": noise_ok,
        "noise_fdr_passes": k,
        "noise_fdr_flagged": m,
        "noise_fdr_rate": k / m if m else None,
        "noise_binomial_p": noise_p,
        "fdr_alpha": fdr_alpha,
        "noise_by_feature": noise,
        "canary_constant_rows": constant_rows,
        "never_weighted_ok": not weighted,
        "weighted_canaries": weighted,
        "v5_pass": detection_ok and noise_ok and not weighted,
    }


def main(argv: list[str] | None = None) -> int:
    from scripts.analysis.sleeve_walk_forward.run import _load
    from scripts.analysis.sleeve_walk_forward.snapshot import load_snapshot

    parser = argparse.ArgumentParser(description="V5: canary controls over S1 refits")
    parser.add_argument("--in", dest="input", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("logs/phase179"))
    args = parser.parse_args(argv)
    obj = _load(args.input, allow_drift=False)
    payload = obj["payload"]
    snap = load_snapshot(Path(payload["snapshot"]))
    config = ic_engine_config(snap.apr)
    fast = containing_lookahead(list(config.lookaheads_for(_TF).values()))
    out = {
        "s1": str(args.input),
        "git_commit": obj["git_commit"],
        **check_refits(payload["refits"], fast, config.fdr_alpha),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"v5_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(path)
    print(
        f"V5: {'PASS' if out['v5_pass'] else 'FAIL'} detection={out['detection_ok']} "
        f"({out['placebo_fast_cells']} fast cells, {len(out['placebo_misses'])} misses) "
        f"noise_fdr={out['noise_fdr_passes']}/{out['noise_fdr_flagged']} "
        f"p={out['noise_binomial_p']:.3g} never_weighted={out['never_weighted_ok']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
