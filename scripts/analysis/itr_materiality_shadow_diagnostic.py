#!/usr/bin/env python3
"""Phase 175's D-03 shadow-mode diagnostic (todo 380, plan 04).

READ-ONLY. Performs zero writes anywhere -- no mutating SQL statement of any kind
appears in this file outside a comment (T-175-17, P175-03's static grep gate).

Reports what breadth-universe and peer-pool membership WOULD change if
services/cross_sectional_regime_model.py switched its `_load_tags_by_symbol` stopgap
(source='human' only, todo 379) to `human OR materiality-eligible empirical`
(TagCalibrator's Pass 4 evidence, is_materiality_eligible -- services/tag_calibrator.py).

This is the artifact the user and the cross-AI reviewers (D-03, D-07) judge before any
consumer query is ever allowed to change -- it is the gate, not a step on the way to
one. Cutting either consumer (breadth_vol.py, cross_sectional_regime_model.py) over to
the materiality-filtered query is explicitly a separate, later phase gated on this
diagnostic's findings; this script does not modify either consumer and does not decide
that question.

Six seeded [initial_estimate] thresholds (migration 346, alpha.tag_calibrator.
materiality.*) gate the statistical side of is_materiality_eligible. The sign-stability
gate in particular carries a deliberate discrete step at n=1008 (a symbol below that
sample count has only three evaluable windows and must show 3-of-3 sign agreement,
while a symbol at or above it needs only 3-of-4 -- a hard jump at one specific sample
count, not a gradual slide; see plan 03's R-07 resolution, docstring on
services.tag_calibrator.decide_materiality). Binary pass/fail counts cannot tell a
future reviewer whether that gate is too strict or about right; the distribution of how
close the FAILING rows came can. This script's GATE ATTRIBUTION and NEAR MISS sections
exist to turn a future loosen/tighten/leave-alone recalibration decision into an
evidence-based one, and are the actual protection against a conservative
[initial_estimate] gate silently hiding real signal (T-175-22b) -- they are not
optional detail, do not drop them as scope.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db  # noqa: E402
from services.cross_sectional_regime_model import (  # noqa: E402
    _DEFAULT_GROUPS_JSON,
    _parse_group_configs,
    _resolve_group_symbols,
)
from services.tag_calibrator import is_materiality_eligible  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_MATERIALITY_PREFIX = "alpha.tag_calibrator.materiality."
_GATE_NAMES = (
    "sample_n",
    "partial_loading",
    "ci_low",
    "incremental_r2",
    "sign_stability",
    "null_arm",
)
_SCALAR_GATES = ("sample_n", "partial_loading", "ci_low", "incremental_r2")

# ---------------------------------------------------------------------------
# Pure functions -- no DB, no I/O
# ---------------------------------------------------------------------------


def build_tag_arms(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Split instrument_tags_active rows into (baseline_by_symbol, candidate_by_symbol).

    baseline: source='human' rows only -- reproduces the live stopgap's admission set.
    candidate: baseline rows PLUS source='empirical' rows where
    is_materiality_eligible(row) is True -- imported from services.tag_calibrator, never
    re-derived here (D-02's "one measurement engine, N read-time cutoffs").

    source='ai' (or any other source) never contributes to either arm. A candidate is
    always a superset of baseline by construction, at the tag level and therefore at the
    symbol-resolution level too (see membership_delta's removed-always-empty invariant).
    """
    baseline: dict[str, set[str]] = {}
    candidate: dict[str, set[str]] = {}
    for row in rows:
        source = row.get("source")
        symbol = row["symbol"]
        tag = row["tag"]
        if source == "human":
            baseline.setdefault(symbol, set()).add(tag)
            candidate.setdefault(symbol, set()).add(tag)
        elif source == "empirical" and is_materiality_eligible(row):
            candidate.setdefault(symbol, set()).add(tag)
    return baseline, candidate


def membership_delta(
    baseline_by_symbol: dict[str, set[str]],
    candidate_by_symbol: dict[str, set[str]],
    tag_filter: list[str],
    exclude_symbols: set[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Resolve one regime group's peer symbols under both arms and diff them.

    Symbol resolution delegates entirely to _resolve_group_symbols (imported from
    services.cross_sectional_regime_model, the exact function the live service uses) --
    prefix matching is never reimplemented here. exclude_symbols is applied AFTER
    resolution, exactly as the live group loop applies signal_exclude_symbols.

    Returns (baseline_symbols, candidate_symbols, added, removed) -- added/removed
    sorted. removed is asserted empty: the candidate arm is a strict superset of the
    baseline arm by construction (build_tag_arms only ever adds tags to the candidate
    side), so no group's candidate symbol set can ever lose a symbol the baseline arm
    resolved.
    """
    baseline_symbols = [
        s
        for s in _resolve_group_symbols(baseline_by_symbol, tag_filter)
        if s not in exclude_symbols
    ]
    candidate_symbols = [
        s
        for s in _resolve_group_symbols(candidate_by_symbol, tag_filter)
        if s not in exclude_symbols
    ]
    baseline_set = set(baseline_symbols)
    candidate_set = set(candidate_symbols)
    added = sorted(candidate_set - baseline_set)
    removed = sorted(baseline_set - candidate_set)
    assert not removed, (
        f"membership_delta invariant violated: candidate arm lost symbols {removed} "
        f"that the baseline arm resolved -- the candidate arm must always be a superset."
    )
    return baseline_symbols, candidate_symbols, added, removed


def _is_nan_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _failing_gates(row: dict[str, Any], thresholds: dict[str, Any]) -> list[str] | None:
    """Which of the six gates this row fails (possibly empty -- passes everything), or
    None if the row is unmeasured (any of the six core Pass 4 statistics used by
    services.tag_calibrator.decide_materiality's own NaN-guard is NULL/NaN). Mirrors
    decide_materiality's condition-by-condition checks exactly, reading from persisted
    instrument_tags_active columns rather than a fresh in-run measurement dict.

    null_arm is derived from the persisted null_arm_bh_p (BH-FDR-adjusted p-value)
    against thresholds["null_arm_alpha"] -- statsmodels' multipletests(method="fdr_bh")
    reject array is exactly p_corrected <= alpha for this method (src/intelligence/
    statistics/ic_math.py::apply_bh_fdr), so this reconstructs decide_materiality's
    null_arm_passes_fdr condition without needing the transient reject boolean itself.
    A missing null_arm_bh_p fails the gate (consistent with decide_materiality's own
    bool(None) == False for a missing null_arm_passes_fdr) rather than making the whole
    row unmeasured -- only the six core statistics gate that classification.
    """
    sample_n = row.get("materiality_sample_n")
    pl = row.get("partial_loading")
    pl_ci_low = row.get("partial_loading_ci_low")
    inc_r2 = row.get("incremental_r2")
    n_stable = row.get("sign_stable_windows")
    n_total = row.get("sign_stable_windows_total")

    for value in (sample_n, pl, pl_ci_low, inc_r2, n_stable, n_total):
        if _is_nan_or_none(value):
            return None

    failing: list[str] = []
    if sample_n < thresholds["min_sample_n"]:
        failing.append("sample_n")
    if abs(pl) < thresholds["min_partial_loading"]:
        failing.append("partial_loading")
    if pl_ci_low < thresholds["min_partial_loading_ci_low"]:
        failing.append("ci_low")
    if inc_r2 < thresholds["min_incremental_r2"]:
        failing.append("incremental_r2")
    if (
        n_stable < thresholds["min_sign_stable_windows"]
        or n_total < thresholds["min_sign_stable_windows"]
    ):
        failing.append("sign_stability")
    null_arm_bh_p = row.get("null_arm_bh_p")
    if null_arm_bh_p is None or not (null_arm_bh_p <= thresholds["null_arm_alpha"]):
        failing.append("null_arm")
    return failing


def attribute_gate_failures(
    empirical_rows: list[dict[str, Any]], thresholds: dict[str, Any]
) -> dict[str, dict[str, int]]:
    """Per-gate failure attribution over non-eligible empirical rows.

    Returns a dict keyed by each of the six gate names plus "unmeasured", each gate's
    value a {"count", "sole_failure"} dict: count = rows failing that gate (a row
    failing multiple gates counts under EVERY one, so no binding constraint is hidden);
    sole_failure = rows failing ONLY that gate -- the decision-relevant number, since
    that is the only kind of row a recalibration of that single threshold could ever
    admit. "unmeasured" counts rows with a NULL/NaN core statistic, kept distinct from
    the six gates rather than silently folded into one of them.
    """
    counts = {name: 0 for name in _GATE_NAMES}
    sole = {name: 0 for name in _GATE_NAMES}
    n_unmeasured = 0

    for row in empirical_rows:
        if is_materiality_eligible(row):
            continue
        failing = _failing_gates(row, thresholds)
        if failing is None:
            n_unmeasured += 1
            continue
        for name in failing:
            counts[name] += 1
        if len(failing) == 1:
            sole[failing[0]] += 1

    result = {name: {"count": counts[name], "sole_failure": sole[name]} for name in _GATE_NAMES}
    result["unmeasured"] = n_unmeasured  # type: ignore[assignment]
    return result


def sign_stability_near_miss(
    empirical_rows: list[dict[str, Any]], thresholds: dict[str, Any]
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], int]]:
    """Exact (sign_stable_windows, sign_stable_windows_total) histogram over every
    non-eligible empirical row that fails the sign-stability gate, plus the same
    histogram restricted to rows failing ONLY sign-stability ("rows a sign-stability
    recalibration alone would admit"). Empty dicts, never an error, when no row fails
    the gate. A row that passes (e.g. (3, 3) against the default min_sign_stable_windows
    of 3) never appears in either histogram.
    """
    all_failing: dict[tuple[int, int], int] = {}
    sole_failing: dict[tuple[int, int], int] = {}

    for row in empirical_rows:
        if is_materiality_eligible(row):
            continue
        failing = _failing_gates(row, thresholds)
        if failing is None or "sign_stability" not in failing:
            continue
        key = (int(row["sign_stable_windows"]), int(row["sign_stable_windows_total"]))
        all_failing[key] = all_failing.get(key, 0) + 1
        if len(failing) == 1:
            sole_failing[key] = sole_failing.get(key, 0) + 1

    return all_failing, sole_failing


def _scalar_value(row: dict[str, Any], gate: str) -> Any:
    if gate == "sample_n":
        return row.get("materiality_sample_n")
    if gate == "partial_loading":
        return row.get("partial_loading")
    if gate == "ci_low":
        return row.get("partial_loading_ci_low")
    return row.get("incremental_r2")  # incremental_r2


def _scalar_fails(value: float, gate: str, thresholds: dict[str, Any]) -> bool:
    if gate == "sample_n":
        return value < thresholds["min_sample_n"]
    if gate == "partial_loading":
        return abs(value) < thresholds["min_partial_loading"]
    if gate == "ci_low":
        return value < thresholds["min_partial_loading_ci_low"]
    return value < thresholds["min_incremental_r2"]  # incremental_r2


def gate_value_distributions(
    empirical_rows: list[dict[str, Any]], thresholds: dict[str, Any]
) -> dict[str, dict[str, float | int | None]]:
    """For each of the four scalar gates, order statistics (n, n_unmeasured, min,
    median, max) of the FAILING rows' own statistic values -- no numeric literal used
    as a cut point, these are observed values from the data, not a new threshold. NaN/
    NULL values are excluded from the distribution and counted separately in
    n_unmeasured, never coerced to zero.
    """
    result: dict[str, dict[str, float | int | None]] = {}
    for gate in _SCALAR_GATES:
        values: list[float] = []
        n_unmeasured = 0
        for row in empirical_rows:
            value = _scalar_value(row, gate)
            if _is_nan_or_none(value):
                n_unmeasured += 1
                continue
            if _scalar_fails(value, gate, thresholds):
                values.append(float(value))
        if values:
            sorted_values = sorted(values)
            mid = len(sorted_values) // 2
            if len(sorted_values) % 2:
                median = sorted_values[mid]
            else:
                median = (sorted_values[mid - 1] + sorted_values[mid]) / 2.0
            result[gate] = {
                "n": len(values),
                "n_unmeasured": n_unmeasured,
                "min": min(values),
                "median": median,
                "max": max(values),
            }
        else:
            result[gate] = {
                "n": 0,
                "n_unmeasured": n_unmeasured,
                "min": None,
                "median": None,
                "max": None,
            }
    return result


# ---------------------------------------------------------------------------
# DB layer -- read-only
# ---------------------------------------------------------------------------

_ACTIVE_TAG_ROWS_SQL = """
    SELECT symbol, tag, source, valid_to, passes_materiality, discovery_state,
           partial_loading, partial_loading_ci_low, incremental_r2,
           sign_stable_windows, sign_stable_windows_total, null_arm_bh_p,
           materiality_sample_n
    FROM instrument_tags_active
"""

_LIVE_BASELINE_SQL = (
    "SELECT symbol, array_agg(tag) FROM instrument_tags WHERE source = 'human' GROUP BY symbol"
)

_MATERIALITY_THRESHOLDS_SQL = (
    "SELECT config_key, config_value FROM config_state "
    "WHERE config_key LIKE 'alpha.tag_calibrator.materiality.%'"
)


def _fetch_active_tag_rows(conn: Any) -> list[dict[str, Any]]:
    """One SELECT of the evidence columns FROM instrument_tags_active -- the view,
    never a bare FROM instrument_tags (RESEARCH.md Pitfall 5). Dicts built from
    cur.description, matching the tsmom script's plain-psycopg fetch shape."""
    with conn.cursor() as cur:
        cur.execute(_ACTIVE_TAG_ROWS_SQL)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _fetch_live_baseline(conn: Any) -> dict[str, set[str]]:
    """The LIVE stopgap query, reproduced byte-for-byte -- exactly
    services.cross_sectional_regime_model._load_tags_by_symbol, including the absence
    of any valid_to filter (the live query has none). This is the "today" ground truth
    the view-derived baseline arm is cross-checked against (T-175-18)."""
    with conn.cursor() as cur:
        cur.execute(_LIVE_BASELINE_SQL)
        return {row[0]: set(row[1]) for row in cur.fetchall()}


def _detect_baseline_drift(
    live_baseline: dict[str, set[str]], view_baseline: dict[str, set[str]]
) -> dict[str, tuple[set[str], set[str]]]:
    """Symbol-level diff between the live stopgap query and the view-derived baseline
    arm. Expected empty: human rows are never auto-expired, so every human row has
    valid_to IS NULL and both queries should agree exactly."""
    diffs: dict[str, tuple[set[str], set[str]]] = {}
    for symbol in set(live_baseline) | set(view_baseline):
        live_tags = live_baseline.get(symbol, set())
        view_tags = view_baseline.get(symbol, set())
        if live_tags != view_tags:
            diffs[symbol] = (live_tags, view_tags)
    return diffs


def _fetch_materiality_thresholds(conn: Any) -> dict[str, Any]:
    """SELECT config_key, config_value FROM config_state WHERE config_key LIKE
    'alpha.tag_calibrator.materiality.%' (eleven rows after migration 346). The gate
    functions above consume only the six gate thresholds and ignore null_arm_seed,
    control_factor_series, and the window-geometry keys (sign_stability_window_days,
    sign_stability_window_count) -- built by selecting the keys each function needs
    rather than assuming a fixed row count."""
    with conn.cursor() as cur:
        cur.execute(_MATERIALITY_THRESHOLDS_SQL)
        raw = {row[0]: row[1] for row in cur.fetchall()}
    return {
        "min_sample_n": int(raw[f"{_MATERIALITY_PREFIX}min_sample_n"]),
        "min_partial_loading": float(raw[f"{_MATERIALITY_PREFIX}min_partial_loading"]),
        "min_partial_loading_ci_low": float(
            raw[f"{_MATERIALITY_PREFIX}min_partial_loading_ci_low"]
        ),
        "min_incremental_r2": float(raw[f"{_MATERIALITY_PREFIX}min_incremental_r2"]),
        "min_sign_stable_windows": int(raw[f"{_MATERIALITY_PREFIX}min_sign_stable_windows"]),
        "null_arm_alpha": float(raw[f"{_MATERIALITY_PREFIX}null_arm_alpha"]),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)

    rows = _fetch_active_tag_rows(conn)
    baseline_by_symbol, candidate_by_symbol = build_tag_arms(rows)

    live_baseline = _fetch_live_baseline(conn)
    drift = _detect_baseline_drift(live_baseline, baseline_by_symbol)
    if drift:
        print("\n*** BASELINE DRIFT DETECTED *** -- diagnostic delta is UNTRUSTWORTHY:")
        for symbol, (live_tags, view_tags) in sorted(drift.items()):
            print(f"  {symbol}: live={sorted(live_tags)} view={sorted(view_tags)}")
    else:
        print("\nBaseline cross-check OK: live stopgap query and view-derived arm agree exactly.")

    cfg = load_config_service_sync(conn)
    raw_groups = cfg.get_sync("alpha.regime.groups", _DEFAULT_GROUPS_JSON)
    group_configs = _parse_group_configs(raw_groups)

    thresholds = _fetch_materiality_thresholds(conn)

    empirical_rows = [r for r in rows if r.get("source") == "empirical"]
    eligible_empirical_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in empirical_rows:
        if is_materiality_eligible(row):
            eligible_empirical_by_symbol.setdefault(row["symbol"], []).append(row)

    print(f"\n{'=' * 70}\nMEMBERSHIP DELTA (per enabled regime group)\n{'=' * 70}")
    for group in group_configs:
        group_name = group["name"]
        signal_type = group["signal_type"]
        tag_filter = group.get("signal_tag_filter") or group["tag_filter"]
        exclude_symbols = set(group.get("signal_exclude_symbols", []))

        baseline_symbols, candidate_symbols, added, _removed = membership_delta(
            baseline_by_symbol, candidate_by_symbol, tag_filter, exclude_symbols
        )
        print(f"\n[{group_name}] signal_type={signal_type}")
        print(
            f"  baseline: {len(baseline_symbols)} symbols   "
            f"candidate: {len(candidate_symbols)} symbols"
        )
        print(f"  ADDED ({len(added)}): {added}")
        for symbol in added:
            for row in eligible_empirical_by_symbol.get(symbol, []):
                print(
                    f"    {symbol} tag={row['tag']} "
                    f"partial_loading={row['partial_loading']:.4f} "
                    f"incremental_r2={row['incremental_r2']:.4f} "
                    f"sign_stable={row['sign_stable_windows']}/{row['sign_stable_windows_total']} "
                    f"null_arm_bh_p={row['null_arm_bh_p']:.4f} "
                    f"sample_n={row['materiality_sample_n']}"
                )

    print(f"\n{'=' * 70}\nGATE ATTRIBUTION (non-eligible empirical rows)\n{'=' * 70}")
    attribution = attribute_gate_failures(empirical_rows, thresholds)
    for gate in _GATE_NAMES:
        counts = attribution[gate]
        print(f"  {gate:<18} count={counts['count']:>5}   sole_failure={counts['sole_failure']:>5}")
    n_never_measured = sum(1 for r in empirical_rows if r.get("passes_materiality") is None)
    print(f"  {'unmeasured':<18} count={attribution['unmeasured']:>5}")
    print(f"  never measured this run (passes_materiality IS NULL): {n_never_measured}")

    print(f"\n{'=' * 70}\nNEAR MISS\n{'=' * 70}")
    hist_all, hist_sole = sign_stability_near_miss(empirical_rows, thresholds)
    print(
        "  sign-stability (sign_stable_windows, sign_stable_windows_total) -- " "ALL failing rows:"
    )
    for key, count in sorted(hist_all.items(), key=lambda kv: -kv[1]):
        print(f"    {key}: {count}")
    print(
        "  sign-stability -- rows a sign-stability recalibration ALONE would admit "
        "(fail only this gate):"
    )
    for key, count in sorted(hist_sole.items(), key=lambda kv: -kv[1]):
        print(f"    {key}: {count}")
    print(
        "  Sliding bar: a symbol at the min_sample_n floor can only ever reach three "
        "evaluable windows and therefore needs 3-of-3 agreement, while a full-history "
        "symbol needs 3-of-4 -- deliberate and recorded in plan 03's R-07 resolution "
        "(services.tag_calibrator.decide_materiality's docstring), not a bug."
    )

    distributions = gate_value_distributions(empirical_rows, thresholds)
    for gate in _SCALAR_GATES:
        dist = distributions[gate]
        print(
            f"  {gate:<18} n={dist['n']:>4}  n_unmeasured={dist['n_unmeasured']:>4}  "
            f"min={dist['min']}  median={dist['median']}  max={dist['max']}"
        )

    print(f"\n{'=' * 70}\nSHADOW MODE\n{'=' * 70}")
    print(
        "  No consumer query changed. breadth_vol.py and cross_sectional_regime_model.py "
        "still read source='human' only. Cutting either consumer over to the "
        "materiality-filtered arm is a separate, later phase gated on this report plus "
        "the D-07 cross-AI review and the user's own review."
    )

    conn.close()


if __name__ == "__main__":
    main()
