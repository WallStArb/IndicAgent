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
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg

from src.config.settings import Settings
from src.intelligence.concept_registry_service import (
    ConceptNotFoundError,
    ConceptRegistryService,
)
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


def _registry_outcome(rows: list[dict]) -> tuple[bool, float | None, float, int, float]:
    """Pure helper: reduce per-stratum verdicts to one registry-recordable outcome.

    won = any stratum verdict is WIN (F2: recipe validity is earned by winning
    anywhere; per-stratum champions stay facts in ensemble_weights).
    eval_metric = mean challenger ic_ci_lower over WIN strata only (D-15 citation
    rule: ic_ci_lower, never ic_value; a WIN-FDR-VETO stratum is not a promotable
    win and contributes nothing). eval_n = challenger n_independent summed over ALL
    compared strata (the evidence mass this comparison consumed, win or lose).
    Returns: (won, eval_metric, eval_n, win_strata_count, win_only_n)
    """
    win_ci_lowers = []
    win_strata_count = 0
    win_only_n_sum = 0.0
    eval_n_sum = 0.0

    for r in rows:
        n_indep = r.get("n_independent")
        if n_indep is not None:
            eval_n_sum += n_indep

        if r["verdict"] == "WIN":
            win_strata_count += 1
            ci_lower = r.get("ic_ci_lower")
            if ci_lower is not None:
                win_ci_lowers.append(ci_lower)
            if n_indep is not None:
                win_only_n_sum += n_indep

    eval_n = float(eval_n_sum)
    won = win_strata_count > 0
    if won and not win_ci_lowers:
        # Should be unreachable: a WIN verdict requires ic_ci_lower to have been
        # non-None (the win rule itself consumes it upstream). If this ever
        # fires, `won` and the recorded eval_metric would silently disagree
        # with win_strata_count -- crash loudly instead (Phase 160 review
        # finding 3).
        raise ValueError(
            f"won=True (win_strata_count={win_strata_count}) but no stratum "
            "contributed a non-None ic_ci_lower -- win/loss bookkeeping is "
            "inconsistent, refusing to record"
        )
    if not won:
        return False, None, eval_n, win_strata_count, float(win_only_n_sum)
    return (
        True,
        float(sum(win_ci_lowers) / len(win_ci_lowers)),
        eval_n,
        win_strata_count,
        float(win_only_n_sum),
    )


async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="D-12 ensemble weight_version A/B comparison")
    parser.add_argument("--champion", required=True, help="Champion weight_version (e.g. v1)")
    parser.add_argument(
        "--challenger", required=True, help="Challenger weight_version (e.g. v1_shrunk)"
    )
    parser.add_argument(
        "--challenger-concept",
        default=None,
        help=(
            "concept_registry name (domain=ensemble_strategy) for the challenger "
            "recipe, e.g. e2_mean_variance. weight_version is a data-scoping epoch "
            "tag (migration 224) and cannot identify the recipe, so it is stated "
            "explicitly here. Omit to run report-only (no registry write). An "
            "unknown name is a hard failure (exit 1) validated before any registry "
            "write, not a report-only warning (todo 118 L-4)."
        ),
    )
    parser.add_argument(
        "--champion-concept",
        default=None,
        help="concept_registry name for the champion recipe (informational, for the transition notes).",
    )
    parser.add_argument(
        "--corpus-build-ref",
        default=None,
        help=(
            "Corpus build identity for invariant 2's re-evaluation guard. Defaults "
            "to the challenger weight_version (the WEIGHT_EPOCH is the corpus-build "
            "identity, derived from TRAINING_WINDOW_END)."
        ),
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

            # todo 118 L-3 scope note: this script's overall report is always exit 0
            # (the module docstring's stated contract, unlike ops_ensemble_ic_gate.py's
            # single boolean gate) -- these three report-only failure paths (missing
            # gate_lookahead, missing compare_fdr_alpha, the alpha_ensemble_ic query
            # failure) predate the registry path entirely and are deliberately left
            # at `return 0` here. L-3 only hardens the registry block further below
            # (every failure print there now returns 1); changing report-only exit
            # semantics is a separate behavioural change, out of scope for this plan.
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
        # todo 118 L-6: fdr_correction_applied records whether the BH-FDR machinery
        # actually ran this round (p_raw_list non-empty). `won` is already gated on
        # bh_reject via _final_verdict's WIN rule, so this flag is not re-deriving
        # that decision -- it asserts the correction ran at all, so the service's
        # new fail-closed guard can distinguish "ran and vetoed" from "never ran",
        # making "the caller forgot to run it" structurally impossible to promote
        # through regardless of what a future caller claims about `won`.
        fdr_correction_applied = bool(p_raw_list)
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

        if args.challenger_concept:
            outcome_rows = [
                {
                    "verdict": (
                        "HOLD"
                        if stratum_data[key]["win"] is None
                        else _final_verdict(
                            stratum_data[key]["win"], stratum_data[key]["bh_reject"]
                        )
                    ),
                    "ic_ci_lower": challenger_by_stratum[key]["ic_ci_lower"],
                    "n_independent": challenger_by_stratum[key]["n_independent"],
                }
                for key in strata
            ]
            won, eval_metric, eval_n, win_strata_count, win_only_n = _registry_outcome(outcome_rows)
            corpus_build_ref = args.corpus_build_ref or args.challenger

            async with pool.acquire() as conn:
                # L-4: validate champion concept existence before any write
                if args.champion_concept:
                    champion_exists = await conn.fetchval(
                        "SELECT COUNT(*) FROM concept_registry "
                        "WHERE domain = 'ensemble_strategy' AND name = $1",
                        args.champion_concept,
                    )
                    if champion_exists == 0:
                        print()
                        print(
                            f"REGISTRY: FAILED - unknown champion concept '{args.champion_concept}'"
                        )
                        return 1

                # L-4: validate challenger concept existence before any write -- the
                # symmetric check the champion gets above. This is the primary
                # defence; the ConceptNotFoundError catch further below stays in
                # place as defence-in-depth.
                challenger_exists = await conn.fetchval(
                    "SELECT COUNT(*) FROM concept_registry "
                    "WHERE domain = 'ensemble_strategy' AND name = $1",
                    args.challenger_concept,
                )
                if challenger_exists == 0:
                    print()
                    print(
                        f"REGISTRY: FAILED - unknown challenger concept '{args.challenger_concept}'"
                    )
                    return 1

                apr_keys = [
                    "alpha.concept_registry.ensemble_strategy_min_promotion_consecutive",
                    "alpha.concept_registry.ensemble_strategy_min_new_observations",
                    "alpha.concept_registry.ensemble_strategy_min_observations",
                ]
                placeholders = ", ".join(f"${i + 1}" for i in range(len(apr_keys)))
                apr_rows = await conn.fetch(
                    f"SELECT config_key, config_value FROM config_state "
                    f"WHERE config_key IN ({placeholders})",
                    *apr_keys,
                )
                apr = {r["config_key"]: r["config_value"] for r in apr_rows}
                if len(apr) != 3:
                    print()
                    print(
                        "REGISTRY: FAILED - alpha.concept_registry.* gate keys missing "
                        "from config_state; apply migration 233 before recording."
                    )
                    return 1

                service = ConceptRegistryService()
                try:
                    decision = await service.record_comparison_outcome(
                        conn,
                        domain="ensemble_strategy",
                        name=args.challenger_concept,
                        won=won,
                        eval_metric=eval_metric,
                        eval_n=eval_n,
                        corpus_build_ref=corpus_build_ref,
                        default_min_promotion_consecutive=int(
                            apr[
                                "alpha.concept_registry.ensemble_strategy_min_promotion_consecutive"
                            ]
                        ),
                        default_min_new_observations=float(
                            apr["alpha.concept_registry.ensemble_strategy_min_new_observations"]
                        ),
                        default_min_gate_n=float(
                            apr["alpha.concept_registry.ensemble_strategy_min_observations"]
                        ),
                        fdr_passed=fdr_correction_applied,
                        notes=(
                            f"A/B vs champion "
                            f"{args.champion_concept or args.champion} "
                            f"(weight_versions {args.champion} vs {args.challenger}). "
                            f"invariant 6; win_strata={win_strata_count} "
                            f"win_only_n={win_only_n} total_strata={len(strata)} "
                            f"gate_n={eval_n}. "
                            "Invariant-6 exception applies: human-authored candidate; "
                            "this OOS A/B on live corpus runs is the domain's "
                            "documented evidentiary substitute for a live shadow "
                            "period (docs/research/"
                            "concept-unified-registry.md, Invariant 6)."
                        ),
                    )
                except ConceptNotFoundError as error:
                    print()
                    print(f"REGISTRY: FAILED - {error}")
                    return 1

                # L-6/T-170-04: the service's fail-closed FDR guard tripped -- this
                # run's win determination could not be proven to have survived
                # multiplicity correction. Halt loudly (exit 1) instead of falling
                # through to the M-6 annotation write and the win-shaped summary
                # line below, so an automated caller cannot mistake this for a
                # recorded outcome.
                if decision.action == "blocked_fdr_unverified":
                    print()
                    print(
                        f"REGISTRY: BLOCKED - concept={args.challenger_concept} "
                        f"won={won} fdr_passed={fdr_correction_applied} -- "
                        "concept_gate.fdr_required is true and multiplicity "
                        "correction was not proven to have survived this round "
                        "(todo 118 L-6)"
                    )
                    return 1

                # M-6: append-only concept_annotation for every recording action
                if decision.action in ("record_win", "record_loss", "promote"):
                    concept_id = await conn.fetchval(
                        "SELECT concept_id FROM concept_registry "
                        "WHERE domain = 'ensemble_strategy' AND name = $1",
                        args.challenger_concept,
                    )
                    annotation_content = (
                        f"action={decision.action} won={won} "
                        f"eval_metric={eval_metric} eval_n={eval_n} "
                        f"win_strata_count={win_strata_count} "
                        f"corpus_build_ref={corpus_build_ref}"
                    )
                    await conn.execute(
                        "INSERT INTO concept_annotation "
                        "(concept_id, annotation_type, content, source, valid_from) "
                        "VALUES ($1, 'observation', $2, 'empirical', $3)",
                        concept_id,
                        annotation_content,
                        datetime.now(UTC),
                    )

            print()
            print(
                f"REGISTRY: concept={args.challenger_concept} won={won} "
                f"eval_metric={eval_metric} eval_n={eval_n} "
                f"corpus_build_ref={corpus_build_ref} -> action={decision.action}"
                + (
                    f" baseline_metric={decision.baseline_metric}"
                    if decision.action == "promote"
                    else ""
                )
            )

        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
