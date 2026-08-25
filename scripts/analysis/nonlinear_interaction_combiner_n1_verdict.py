"""Reads every N1 result JSON written by nonlinear_interaction_combiner_n1_test.py, applies the
BH-FDR correction across the full 6-test family (2 arms x 3 tfs), and prints the pre-registered
PASS/FAIL/AMBIGUOUS verdict per docs/research/measurement-nonlinear-interaction-combiner.md's
"Falsification criterion" for Test N1.

Per-arm verdict (criteria 1-3 evaluated using that arm's own 3 timeframe results; the design's
"same sign at at least 2 of the 3 timeframes" language names timeframes within one arm, not
across arms). Criterion 4 (BH-FDR) is applied globally across all 6 tests, since the design's own
preamble states "2 arms x 3 timeframes = 6 tests in the BH-FDR family" -- one shared correction,
not two 3-test families. Overall N1 verdict: PASS if EITHER arm independently clears all 5
criteria using its own 3 tfs plus the shared family-wide FDR/guardrail checks -- the design does
not spell out cross-arm combination explicitly (both arms test the same underlying hypothesis,
N1-b is a refinement of N1-a), so this script states that interpretation here rather than
silently picking one.

Usage (run after all 6 base (arm, tf) combinations have been produced by the test script):
    .venv/bin/python scripts/analysis/nonlinear_interaction_combiner_n1_verdict.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.intelligence.statistics.ic_math import apply_bh_fdr  # noqa: E402

_ARMS = ["a", "b"]
_TFS = ["15m", "1h", "1d"]
_FDR_ALPHA = 0.05
_MAGNITUDE_FLOOR = 0.005
_MIN_TFS_SAME_SIGN = 2


def main() -> None:
    out_dir = Path("docs/analysis")
    results: dict[tuple[str, str], dict] = {}
    missing = []
    for arm in _ARMS:
        for tf in _TFS:
            path = out_dir / f"n1_{tf}_{arm}.json"
            if not path.exists():
                missing.append(str(path))
                continue
            with open(path) as f:
                results[(arm, tf)] = json.load(f)

    if missing:
        print("Missing result files -- verdict cannot be computed until all 6 exist:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)

    # Criterion 4: BH-FDR across the full 6-test family, one shared correction.
    ordered_keys = [(arm, tf) for arm in _ARMS for tf in _TFS]
    p_values = [results[k]["p_value"] for k in ordered_keys]
    reject, p_corrected = apply_bh_fdr(p_values, alpha=_FDR_ALPHA)
    fdr_survives = dict(zip(ordered_keys, reject, strict=True))
    fdr_p_corrected = dict(zip(ordered_keys, p_corrected, strict=True))

    print(f"{'=' * 100}\nN1 -- full 6-test family, BH-FDR alpha={_FDR_ALPHA}\n{'=' * 100}")
    print(
        f"{'arm':<6}{'tf':<6}{'point_diff':>12}{'ci_lower':>12}{'p_raw':>10}{'p_fdr':>10}"
        f"{'fdr_survives':>14}{'g1':>6}{'g2':>6}"
    )
    for k in ordered_keys:
        r = results[k]
        print(
            f"{k[0]:<6}{k[1]:<6}{r['point_diff']:>12.4f}{r['ci_lower']:>12.4f}"
            f"{r['p_value']:>10.4f}{fdr_p_corrected[k]:>10.4f}"
            f"{str(fdr_survives[k]):>14}{str(r['g1_breach']):>6}{str(r['g2_breach']):>6}"
        )

    any_guardrail_breach = any(r["g1_breach"] or r["g2_breach"] for r in results.values())
    if any_guardrail_breach:
        print(
            "\nGUARDRAIL BREACH somewhere in the family -- per the pre-registered design, the "
            "affected run(s) are VOID, not reported as a number. Investigate before any verdict."
        )

    print(f"\n{'=' * 100}\nPer-arm verdict\n{'=' * 100}")
    overall_pass = False
    for arm in _ARMS:
        arm_results = {tf: results[(arm, tf)] for tf in _TFS}
        crit1 = {tf: r["ci_lower"] > 0 for tf, r in arm_results.items()}
        crit2 = {tf: r["point_diff"] >= _MAGNITUDE_FLOOR for tf, r in arm_results.items()}
        signs = {
            tf: (1 if r["point_diff"] > 0 else -1 if r["point_diff"] < 0 else 0)
            for tf, r in arm_results.items()
        }
        sign_counts: dict[int, int] = {}
        for s in signs.values():
            sign_counts[s] = sign_counts.get(s, 0) + 1
        dominant_sign, dominant_count = max(sign_counts.items(), key=lambda kv: kv[1])
        crit3 = dominant_sign != 0 and dominant_count >= _MIN_TFS_SAME_SIGN
        crit4 = all(fdr_survives[(arm, tf)] for tf in _TFS)
        crit5 = not any(arm_results[tf]["g1_breach"] or arm_results[tf]["g2_breach"] for tf in _TFS)

        arm_pass = all([any(crit1.values()), any(crit2.values()), crit3, crit4, crit5])
        # Stricter reading: PASS requires the criteria to hold on the SAME clearing test(s), not
        # independently-satisfied-somewhere-in-the-arm. Report both the lenient (any) and strict
        # (per-tf-simultaneous) view so a borderline case is visible, not hidden by which reading
        # was picked.
        crit1_and_2_same_tf = {tf: crit1[tf] and crit2[tf] for tf in _TFS}
        n_tfs_clearing_both = sum(crit1_and_2_same_tf.values())
        strict_pass = n_tfs_clearing_both >= _MIN_TFS_SAME_SIGN and crit3 and crit4 and crit5

        print(f"\nN1-{arm}:")
        print(f"  Criterion 1 (ci_lower>0):        {crit1}")
        print(f"  Criterion 2 (point_diff>=0.005): {crit2}")
        print(
            f"  Criterion 3 (same sign >=2/3 tf): dominant_sign={dominant_sign} count={dominant_count} -> {'CLEAR' if crit3 else 'FAIL'}"
        )
        print(
            f"  Criterion 4 (BH-FDR survives):    {[fdr_survives[(arm, tf)] for tf in _TFS]} -> {'CLEAR' if crit4 else 'FAIL'}"
        )
        print(f"  Criterion 5 (guardrails clean):   {'CLEAR' if crit5 else 'FAIL'}")
        print(
            f"  STRICT verdict (>=2/3 tfs simultaneously clear crit 1+2, plus 3/4/5): {'PASS' if strict_pass else 'FAIL'}"
        )

        if strict_pass:
            overall_pass = True

    print(f"\n{'=' * 100}")
    if overall_pass:
        print(
            "OVERALL N1 VERDICT: PASS (at least one arm clears all 5 pre-registered criteria, "
            "strict reading). Per the design's Outcome semantics: genuine non-linear structure "
            "exists beyond capped linear combination. Next step is NOT promotion -- it is a SHAP "
            "/ gain-attribution pass to name the interacting pairs, per the doc's own PASS "
            "semantics."
        )
    else:
        print(
            "OVERALL N1 VERDICT: FAIL (no arm clears all 5 pre-registered criteria under the "
            "strict same-tf-simultaneous reading). Per the design's Outcome semantics: the "
            "combiner's linearity is not the binding constraint. nonlinear_interaction_combiner "
            "is dead as stated -- data-edge-source-thesis.md's Scorecard and this doc's own "
            "Status block need updating to reflect this, not left at 'most promising open "
            "thread.'"
        )
    print(f"{'=' * 100}")


if __name__ == "__main__":
    main()
