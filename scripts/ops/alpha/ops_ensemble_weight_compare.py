#!/usr/bin/env python3
"""
ops_ensemble_weight_compare.py — D-12 win-decision comparison gate.

Reads `alpha_ensemble_ic` for two `weight_version`s (a champion and a challenger) at
each version's own deterministic latest `scored_at` vintage (D-142A-R2's "never a
rolling time-window subtraction" pattern, applied per weight_version instead of
globally — mirrors `ops_ensemble_ic_gate.py`'s EIC-04 `_GATE_SQL` shape), reads only
the pooled cross-sectional rows (`symbol = 'POOLED'`, `is_pooled = true`; Plan 01
populates these), and applies D-10's win rule independently per (tf, regime) stratum:

    challenger beats champion iff (challenger.ic_ci_lower > champion.ic_ci_upper)
        AND challenger.walk_forward_stable is True

Both conditions are ANDed — `walk_forward_stable = False` vetoes even a
non-overlapping-CI win. Promotion is reported per-stratum (D-11): there is no forced
single global winner, so a mixed outcome (challenger wins 1h/trending, champion holds
5m/ranging) is expected and directly expressible.

D-14: every reported stratum whose `regime` is not the `'_pooled'` aggregate-across-
regime sentinel (the convention already used by `feature_ic_scores.regime` — see
`services/ensemble_trainer.py`'s `regime != '_pooled'` filter) is tagged with the HMM
regime-label look-ahead caveat (todo 026/034), so promoted weight_versions on
regime-stratified cells are re-validatable once the causal HMM refit lands. D-13: this
known risk is carried forward, not remediated, in this phase.

`alpha.ensemble_ic.gate_lookahead` (APR, already seeded by migration 195 for EIC-04)
selects the single lookahead scale compared per stratum, so the comparison never mixes
CI intervals measured at different lookahead horizons within one (tf, regime) row.

This is a report, not a single boolean gate (unlike `ops_ensemble_ic_gate.py`): exit
code is always 0, mirroring `ops_ensemble_ic_diagnosis.py`'s "informational, not a
gate" convention, since promotion here is per-stratum and multi-valued.

Usage:
    python scripts/ops/alpha/ops_ensemble_weight_compare.py --champion v1 --challenger v1_shrunk
"""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg

from src.config.settings import Settings
from src.intelligence.statistics.ic_math import apply_bh_fdr, fisher_z_difference_p

# D-14: aggregate-across-regime sentinel already used by feature_ic_scores.regime (see
# ensemble_trainer.py's `WHERE ... regime != '_pooled'` filter). alpha_ensemble_ic's 9
# live cross-sectional regime labels never take this literal value today, but the check
# is written generically so the caveat is correct if/when an aggregate-across-regime row
# is ever added to alpha_ensemble_ic.
_POOLED_REGIME_SENTINEL = "_pooled"

_D14_REGIME_CAVEAT = "HMM regime-label look-ahead caveat (todo 026/034) -- re-validate once fixed"

# D-15: winner's-curse caveat (measurement-ic-engine.md OQ7, resolved todo 069 /
# docs/research/fable-2026-07-09-ensemble-winners-curse-peer-group.md). There is no
# defensible shrinkage peer group at ensemble-variant grain -- the decision is a pairwise
# CI-ordering test per stratum, not a k-way argmax, and 2-3 correlated, non-exchangeable
# variants are not an empirical-Bayes population. The resolved fix decomposes into: (a)
# across-strata multiplicity, corrected below via BH-FDR (alpha.ensemble.compare_fdr_alpha);
# (b) post-selection reporting bias on the winner's point IC, corrected by citing
# ic_ci_lower (not ic_value) until an OOS confirmation exists. This caveat is retained on
# every WIN verdict as the citation rule, not as an open question anymore.
_D15_WINNERS_CURSE_CAVEAT = (
    "winner's-curse: cite ic_ci_lower, not ic_value, as the in-sample estimate; "
    "OOS confirmation via ensemble_ic_engine.py over the untouched holdout is required "
    "before citing this champion's IC in any downstream evidence chain (todo 069, "
    "docs/research/fable-2026-07-09-ensemble-winners-curse-peer-group.md)"
)

# D-12 comparison SQL: two weight_versions, each read at its OWN deterministic latest
# scored_at vintage (GROUP BY weight_version, not a single global max) -- mirrors
# ops_ensemble_ic_gate.py's `latest AS (SELECT max(scored_at) ...)` pattern (D-142A-R2),
# applied per weight_version. Pooled rows only (symbol = 'POOLED' AND is_pooled = true);
# scoped to a single lookahead scale (alpha.ensemble_ic.gate_lookahead, APR) so CIs at
# different lookahead horizons are never compared against each other within one stratum.
# ic_value/n_independent (added for todo 069) feed the per-stratum BH-FDR pass below.
_COMPARE_SQL = """
    WITH latest_per_version AS (
        SELECT weight_version, max(scored_at) AS ts
        FROM alpha_ensemble_ic
        WHERE weight_version IN ($1, $2) AND lookahead = $3
        GROUP BY weight_version
    )
    SELECT ae.weight_version, ae.tf, ae.regime,
           ae.ic_ci_lower, ae.ic_ci_upper, ae.walk_forward_stable,
           ae.ic_value, ae.n_independent
    FROM alpha_ensemble_ic ae
    JOIN latest_per_version lpv
      ON lpv.weight_version = ae.weight_version AND lpv.ts = ae.scored_at
    WHERE ae.symbol = 'POOLED' AND ae.is_pooled = true AND ae.lookahead = $3
"""


def _evaluate_win_rule(
    challenger_ci_lower: float, champion_ci_upper: float, challenger_stable: bool
) -> bool:
    """Pure helper: D-10 win rule.

    Challenger beats champion on a given (tf, regime) stratum iff the challenger's CI
    lower bound is strictly above the champion's CI upper bound (non-overlapping
    confidence intervals -- a real, not noise-level, improvement) AND the challenger is
    walk-forward stable. Both conditions are ANDed: walk_forward_stable=False vetoes
    even a non-overlapping-CI win.
    """
    return bool(challenger_ci_lower > champion_ci_upper) and bool(challenger_stable)


def _regime_caveat(regime: str) -> str:
    """Pure helper: D-14 regime-caveat tag.

    Returns the HMM regime-label look-ahead caveat string for any stratum whose regime
    is not the '_pooled' aggregate-across-regime sentinel, empty string otherwise.
    """
    return "" if regime == _POOLED_REGIME_SENTINEL else _D14_REGIME_CAVEAT


def _winners_curse_flag(verdict: str) -> str:
    """Pure helper: D-15 winner's-curse caveat tag.

    Only a WIN verdict is actionable (it's the one that would drive a promotion), so only
    WIN carries the caveat -- a LOSS, HOLD, or WIN-FDR-VETO doesn't select the challenger's
    IC as a representative estimate of anything (WIN-FDR-VETO in particular already failed
    to survive multiplicity correction, so there is no promotion decision left to caveat).
    """
    return _D15_WINNERS_CURSE_CAVEAT if verdict == "WIN" else ""


def _final_verdict(win: bool, bh_reject: bool | None) -> str:
    """Pure helper: combine the D-10 win rule with BH-FDR multiplicity correction (todo 069).

    win=False -> LOSS regardless of BH. Multiplicity correction can only downgrade a WIN
    that passed the pairwise CI-ordering test; it can never manufacture a win that D-10
    didn't already find.

    win=True, bh_reject=None -> HOLD. The BH p-value was degenerate for this stratum
    (fisher_z_difference_p returns NaN when either side's n_independent <= 3) and was
    excluded from the correction pool -- no verdict can be rendered without it.

    win=True, bh_reject=True -> WIN. Passed both the pairwise test and the corrected
    family-wise multiplicity check.

    win=True, bh_reject=False -> WIN-FDR-VETO. Passed D-10 in isolation but did not
    survive BH-FDR correction for testing multiple (tf, regime) strata in this comparison
    round -- reported as its own verdict, not silently folded into LOSS, since collapsing
    it would hide exactly the multiplicity information this fix exists to surface.
    """
    if not win:
        return "LOSS"
    if bh_reject is None:
        return "HOLD"
    return "WIN" if bh_reject else "WIN-FDR-VETO"


async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="D-12 ensemble weight_version A/B comparison")
    parser.add_argument("--champion", required=True, help="Champion weight_version (e.g. v1)")
    parser.add_argument(
        "--challenger", required=True, help="Challenger weight_version (e.g. v1_shrunk)"
    )
    args = parser.parse_args()

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            try:
                gate_lookahead = await conn.fetchval(
                    "SELECT config_value FROM config_state "
                    "WHERE config_key = 'alpha.ensemble_ic.gate_lookahead'"
                )
                compare_fdr_alpha_raw = await conn.fetchval(
                    "SELECT config_value FROM config_state "
                    "WHERE config_key = 'alpha.ensemble.compare_fdr_alpha'"
                )
            except Exception as error:  # CLAUDE.md: exception variable name is `error`
                print(f"## D-12 Ensemble Weight Compare\n\nFAILED to read APR config: {error}")
                return 0

            if gate_lookahead is None:
                print(
                    "## D-12 Ensemble Weight Compare\n\n"
                    "FAILED: alpha.ensemble_ic.gate_lookahead missing from config_state "
                    "-- seed it via migration 195 before running this comparison."
                )
                return 0

            if compare_fdr_alpha_raw is None:
                print(
                    "## D-12 Ensemble Weight Compare\n\n"
                    "FAILED: alpha.ensemble.compare_fdr_alpha missing from config_state "
                    "-- seed it via migration 213 before running this comparison."
                )
                return 0
            compare_fdr_alpha = float(compare_fdr_alpha_raw)

            try:
                rows = await conn.fetch(
                    _COMPARE_SQL, args.champion, args.challenger, gate_lookahead
                )
            except Exception as error:
                print(
                    f"## D-12 Ensemble Weight Compare\n\nFAILED querying alpha_ensemble_ic: {error}"
                )
                return 0

        champion_by_stratum: dict[tuple[str, str], dict] = {}
        challenger_by_stratum: dict[tuple[str, str], dict] = {}
        for row in rows:
            key = (row["tf"], row["regime"])
            if row["weight_version"] == args.champion:
                champion_by_stratum[key] = row
            elif row["weight_version"] == args.challenger:
                challenger_by_stratum[key] = row

        print("## D-12 Ensemble Weight Compare")
        print()
        print(f"Champion: {args.champion}")
        print(f"Challenger: {args.challenger}")
        print(f"Lookahead (APR alpha.ensemble_ic.gate_lookahead): {gate_lookahead}")
        print(f"BH-FDR alpha (APR alpha.ensemble.compare_fdr_alpha): {compare_fdr_alpha}")
        print()

        if not champion_by_stratum or not challenger_by_stratum:
            print(
                "no comparable strata -- one or both weight_versions have no pooled "
                "alpha_ensemble_ic rows at this lookahead. Run "
                "`python services/ensemble_ic_engine.py --weight-version <version>` for "
                "each version first."
            )
            return 0

        strata = sorted(set(champion_by_stratum) & set(challenger_by_stratum))
        if not strata:
            print(
                "no strata present for BOTH weight_versions -- cannot compare "
                "(champion and challenger cover disjoint (tf, regime) cells)."
            )
            return 0

        # Pass 1: compute the D-10 win rule and the raw difference p-value for every
        # stratum. p_raw is computed for ALL strata (not just D-10 winners) -- BH-FDR
        # must correct across the full family of comparisons this run actually made,
        # not a pre-filtered subset (correcting only D-10 winners would itself be a
        # selection-biased correction). Only fields not already reachable via
        # champion_by_stratum/challenger_by_stratum are stored here -- both stay in
        # scope through pass 3, so CI/stability fields are read from them directly
        # rather than copied.
        stratum_data: dict[tuple[str, str], dict] = {}
        p_raw_list: list[float] = []
        p_raw_index: list[tuple[str, str]] = []
        for tf, regime in strata:
            champion_row = champion_by_stratum[(tf, regime)]
            challenger_row = challenger_by_stratum[(tf, regime)]

            champion_ci_upper = champion_row["ic_ci_upper"]
            challenger_ci_lower = challenger_row["ic_ci_lower"]
            challenger_stable = challenger_row["walk_forward_stable"]

            entry: dict = {"win": None, "p_raw": None, "p_bh": None, "bh_reject": None}
            stratum_data[(tf, regime)] = entry

            if champion_ci_upper is None or challenger_ci_lower is None:
                continue

            win = _evaluate_win_rule(
                challenger_ci_lower, champion_ci_upper, bool(challenger_stable)
            )
            entry["win"] = win

            champion_ic_value = champion_row["ic_value"]
            champion_n = champion_row["n_independent"]
            challenger_ic_value = challenger_row["ic_value"]
            challenger_n = challenger_row["n_independent"]

            if (
                champion_ic_value is not None
                and champion_n is not None
                and challenger_ic_value is not None
                and challenger_n is not None
            ):
                p_raw = fisher_z_difference_p(
                    challenger_ic_value, challenger_n, champion_ic_value, champion_n
                )
                if not math.isnan(p_raw):
                    entry["p_raw"] = p_raw
                    p_raw_list.append(p_raw)
                    p_raw_index.append((tf, regime))

        # Pass 2: ONE BH-FDR correction across every p_raw collected above
        # (alpha.ensemble.compare_fdr_alpha) -- shared apply_bh_fdr() helper mirrors
        # ic_engine.py/ensemble_ic_engine.py/ops_oos_holdout_eval.py's existing
        # corpus-level BH-FDR pattern; results are written straight back into
        # stratum_data in place, the same "mutate the result container" convention
        # ops_oos_holdout_eval.py's _apply_corpus_fdr already uses.
        reject, p_corrected = apply_bh_fdr(p_raw_list, compare_fdr_alpha)
        for idx, key in enumerate(p_raw_index):
            stratum_data[key]["p_bh"] = float(p_corrected[idx])
            stratum_data[key]["bh_reject"] = bool(reject[idx])

        print(
            "| tf | regime | champion_ci | challenger_ci | walk_forward_stable | "
            "p_raw | p_bh | verdict | flag |"
        )
        print("|---|---|---|---|---|---|---|---|---|")
        for tf, regime in strata:
            champion_row = champion_by_stratum[(tf, regime)]
            challenger_row = challenger_by_stratum[(tf, regime)]
            entry = stratum_data[(tf, regime)]
            win = entry["win"]

            verdict = "HOLD" if win is None else _final_verdict(win, entry["bh_reject"])

            flags = [f for f in (_regime_caveat(regime), _winners_curse_flag(verdict)) if f]
            flag = "; ".join(flags)

            champion_ci_str = f"[{champion_row['ic_ci_lower']}, {champion_row['ic_ci_upper']}]"
            challenger_ci_str = (
                f"[{challenger_row['ic_ci_lower']}, {challenger_row['ic_ci_upper']}]"
            )
            p_raw_str = f"{entry['p_raw']:.4f}" if entry["p_raw"] is not None else "n/a"
            p_bh_str = f"{entry['p_bh']:.4f}" if entry["p_bh"] is not None else "n/a"
            print(
                f"| {tf} | {regime} | {champion_ci_str} | {challenger_ci_str} | "
                f"{challenger_row['walk_forward_stable']} | {p_raw_str} | {p_bh_str} | "
                f"{verdict} | {flag} |"
            )

        print()
        print("---")
        print(
            "Verdict is the challenger's outcome vs. the champion, per stratum. "
            "Promotion is per-stratum (D-11) -- no forced single global winner. "
            "WIN-FDR-VETO means the stratum passed the pairwise CI-ordering test (D-10) "
            "but did not survive BH-FDR correction across the strata compared this round -- "
            "it is not a promotable WIN."
        )
        print(
            "Reporting rule (D-15): a promoted champion's citable in-sample IC is "
            "ic_ci_lower, never ic_value. ic_value is upward-biased by selection; the "
            "unbiased estimate is an EnsembleICEngine OOS measurement over the untouched "
            "holdout (docs/plans/OOS-EVAL-PROTOCOL.md), which must be run before this "
            "champion's IC is cited in any downstream evidence chain (cost hurdle, Kelly, "
            "promotion claims)."
        )

        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
