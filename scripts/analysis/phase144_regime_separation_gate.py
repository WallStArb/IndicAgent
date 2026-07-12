#!/usr/bin/env python3
"""Phase 144 D-05 acceptance gate: TLT per-symbol HMM vs `rates` cross-sectional
regime IC separation (docs/research/fable-2026-07-07-phase144-conditioning-decision.md
Section 6 Input 1, falsifiers F1/F2).

This is the widened Step 1 protocol from todo 026, re-scoped to compare TLT's
per-symbol HMM regime labels (regime_scope='symbol_hmm') against the NEW `rates`
cross-sectional group's labels (regime_scope='cross_sectional', symbol='POOLED',
regime IN the curve_credit tier vocabulary) -- the first time this comparison can
run clean, since before Phase 144's regime_group routing shipped, TLT's per-symbol
HMM could only be measured against the contaminated equity cross-sectional label.

The exact SQL for this gate was NOT pre-registered anywhere (RESEARCH.md Open
Question 3) -- writing it fresh against feature_ic_scores.regime_scope is this
script's own deliverable. Design choices, since none were prescribed:

  - Separation metric: "spread" = max(mean_ic) - min(mean_ic) across a side's
    regime labels, matching todo 026 Step 2(c)'s own terminology ("cross-sectional
    range (0.0457) vs per-symbol HMM range (0.0327)"). Classified against todo
    026's bands: gap < 0.01 deficient, 0.01-0.05 ambiguous, > 0.05 adequate.
  - Signed check ("correct sign", used by F1/F2): only meaningful for the
    per-symbol HMM side, whose label vocabulary (trending_up/transition_up/
    ranging/transition_down/trending_down, see regime_writer.py's
    _build_label_map) has a natural bullish/bearish pairing. Signed gap =
    mean_ic(trending_up) - mean_ic(trending_down), matching the exact metric
    todo 026 originally reported (SPY +0.024 "correct", TLT -0.003 "inverted").
    The rates cross-sectional vocabulary (steep/flat/inverted x wide/tight, see
    curve_credit.py) has no equivalent natural up/down pairing, so only the
    unsigned spread is computed for that side -- sign coherence there is a
    qualitative read of the printed per-label table, not a single boolean.

HARD PRECONDITION (D-07/D-08): this script's measurement queries must never run
against a stale or in-flight corpus. STEP 0 checks for the existence of any
feature_ic_scores row carrying a `rates` cross-sectional regime label -- that
label set can only exist after Phase 144's ic_engine regime_group routing
(Plan 05) has actually run against a rebuilt corpus, so its absence is proof the
corpus predates the routing fix or the corpus-wide BH-FDR write from the current
rebuild has not landed yet. This is a freshness check on live data, not a
hardcoded row count or date (D-08).

Usage:
    .venv/bin/python scripts/analysis/phase144_regime_separation_gate.py
    .venv/bin/python scripts/analysis/phase144_regime_separation_gate.py --tf 5m 1h
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

_GAP_DEFICIENT = 0.01
_GAP_ADEQUATE = 0.05

_TLT_SYMBOL = "TLT"

# curve_credit.py's 6-label tier vocabulary (3 curve tiers x 2 credit tiers).
# Rows carrying any of these labels under regime_scope='cross_sectional' can only
# exist after Phase 144's ic_engine regime_group routing has run -- used as the
# STEP 0 freshness marker.
_RATES_CROSS_SECTIONAL_LABELS: tuple[str, ...] = (
    "steep_tight",
    "steep_wide",
    "flat_tight",
    "flat_wide",
    "inverted_tight",
    "inverted_wide",
)

# regime_writer.py's K=5 per-symbol HMM label vocabulary (_build_label_map).
_LABEL_TRENDING_UP = "trending_up"
_LABEL_TRENDING_DOWN = "trending_down"


def _dsn() -> str:
    """Build a psycopg2 DSN from env vars, matching CLAUDE.md's documented
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent convention."""
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB", "indicagent")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _connect() -> Any:
    conn = psycopg2.connect(_dsn())
    conn.autocommit = False
    return conn


def check_precondition(conn: Any) -> tuple[bool, str]:
    """STEP 0 -- precondition check (D-07/D-08).

    Returns (is_fresh, evidence). is_fresh=False means: do not run STEP 1-3's
    measurement queries against this corpus, record BLOCKED-ON-143.1-07 instead.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT regime, count(*) AS n, max(computed_at) AS latest
            FROM feature_ic_scores
            WHERE regime_scope = 'cross_sectional'
              AND regime = ANY(%(labels)s)
            GROUP BY regime
            ORDER BY regime
            """,
            {"labels": list(_RATES_CROSS_SECTIONAL_LABELS)},
        )
        rates_rows = cur.fetchall()

        cur.execute("SELECT max(computed_at) AS latest, count(*) AS n FROM feature_ic_scores")
        overall_latest, overall_n = cur.fetchone()

    if not rates_rows:
        evidence = (
            f"Zero feature_ic_scores rows found with regime_scope='cross_sectional' and a "
            f"rates-vocabulary regime label ({', '.join(_RATES_CROSS_SECTIONAL_LABELS)}). "
            f"This label set can only exist after Phase 144's ic_engine regime_group routing "
            f"(Plan 05) has run against a rebuilt corpus. Overall feature_ic_scores state: "
            f"{overall_n} rows, max(computed_at)={overall_latest}."
        )
        return False, evidence

    evidence = (
        f"Found {len(rates_rows)} rates-vocabulary regime labels in feature_ic_scores: "
        f"{[(r[0], r[1], str(r[2])) for r in rates_rows]}. Overall feature_ic_scores state: "
        f"{overall_n} rows, max(computed_at)={overall_latest}."
    )
    return True, evidence


def _fetch_mean_ic_by_tf_regime(
    conn: Any,
    *,
    symbol: str,
    regime_scope: str,
    is_pooled: bool,
    regimes: tuple[str, ...] | None,
    tfs: list[str] | None,
) -> list[dict]:
    """Fetch mean(ic_value) grouped by (tf, regime) for one side of the comparison."""
    where = ["symbol = %(symbol)s", "regime_scope = %(regime_scope)s", "is_pooled = %(is_pooled)s"]
    params: dict[str, Any] = {
        "symbol": symbol,
        "regime_scope": regime_scope,
        "is_pooled": is_pooled,
    }
    if regimes is not None:
        where.append("regime = ANY(%(regimes)s)")
        params["regimes"] = list(regimes)
    if tfs:
        where.append("tf = ANY(%(tfs)s)")
        params["tfs"] = tfs

    sql = f"""
        SELECT tf, regime, avg(ic_value) AS mean_ic, count(*) AS n
        FROM feature_ic_scores
        WHERE {" AND ".join(where)}
        GROUP BY tf, regime
        ORDER BY tf, regime
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def _spread_by_tf(rows: list[dict]) -> dict[str, dict]:
    """Group rows by tf, compute spread = max(mean_ic) - min(mean_ic) per tf."""
    by_tf: dict[str, list[dict]] = {}
    for row in rows:
        by_tf.setdefault(row["tf"], []).append(row)

    result: dict[str, dict] = {}
    for tf, tf_rows in by_tf.items():
        ics = [float(r["mean_ic"]) for r in tf_rows if r["mean_ic"] is not None]
        if not ics:
            continue
        max_row = max(tf_rows, key=lambda r: r["mean_ic"])
        min_row = min(tf_rows, key=lambda r: r["mean_ic"])
        result[tf] = {
            "spread": float(max_row["mean_ic"]) - float(min_row["mean_ic"]),
            "max_regime": max_row["regime"],
            "max_ic": float(max_row["mean_ic"]),
            "min_regime": min_row["regime"],
            "min_ic": float(min_row["mean_ic"]),
            "n_labels": len(tf_rows),
            "labels": {r["regime"]: {"mean_ic": float(r["mean_ic"]), "n": r["n"]} for r in tf_rows},
        }
    return result


def _signed_trend_gap_by_tf(rows: list[dict]) -> dict[str, float]:
    """trending_up - trending_down signed gap per tf (per-symbol HMM side only)."""
    by_tf: dict[str, dict[str, float]] = {}
    for row in rows:
        by_tf.setdefault(row["tf"], {})[row["regime"]] = (
            float(row["mean_ic"]) if row["mean_ic"] is not None else None
        )
    result = {}
    for tf, labels in by_tf.items():
        up = labels.get(_LABEL_TRENDING_UP)
        down = labels.get(_LABEL_TRENDING_DOWN)
        if up is not None and down is not None:
            result[tf] = up - down
    return result


def classify_band(gap: float) -> str:
    magnitude = abs(gap)
    if magnitude < _GAP_DEFICIENT:
        return "deficient"
    if magnitude <= _GAP_ADEQUATE:
        return "ambiguous"
    return "adequate"


def _print_side_table(title: str, spreads: dict[str, dict]) -> None:
    print(f"\n{title}")
    if not spreads:
        print("  (no rows)")
        return
    for tf, info in sorted(spreads.items()):
        band = classify_band(info["spread"])
        print(
            f"  tf={tf:<4} spread={info['spread']:+.4f} [{band}] "
            f"max={info['max_regime']}({info['max_ic']:+.4f}) "
            f"min={info['min_regime']}({info['min_ic']:+.4f}) "
            f"n_labels={info['n_labels']}"
        )
        for regime, stats in sorted(info["labels"].items()):
            print(f"      {regime:<16} mean_ic={stats['mean_ic']:+.4f} n={stats['n']}")


def render_verdict(
    tlt_signed_gap_by_tf: dict[str, float],
    rates_spreads: dict[str, dict],
) -> str:
    """F1/F2 falsifier verdict per the Fable decision doc's decision tree.

    F1: TLT per-symbol HMM signed gap (trending_up - trending_down) >= 0.01 with
        correct (positive) sign -> demotion premise fails, keep per-symbol HMM
        live for rates (no demotion).
    F2: else (default demotion holds) -- if the rates cross-sectional label's own
        spread ALSO lands in the deficient band (< 0.01), rates has no valid
        conditioning axis via either mechanism -> triggers the factor-augmented
        HMM challenger (option c) build, pending volatility_pct's own
        substitution-gate status (not evaluated by this script).
    """
    lines = ["\n=== F1/F2 Falsifier Verdict ==="]

    if not tlt_signed_gap_by_tf:
        lines.append(
            "TLT per-symbol HMM trending_up/trending_down pair not found in any tf -- "
            "cannot evaluate F1. Verdict: INCONCLUSIVE, do not act."
        )
        return "\n".join(lines)

    f1_triggered_tfs = [tf for tf, gap in tlt_signed_gap_by_tf.items() if gap >= _GAP_DEFICIENT]
    for tf, gap in sorted(tlt_signed_gap_by_tf.items()):
        band = classify_band(gap)
        sign = "correct (up>down)" if gap > 0 else "inverted (down>=up)"
        lines.append(f"  TLT symbol_hmm tf={tf}: signed_gap={gap:+.4f} [{band}, {sign}]")

    if f1_triggered_tfs:
        lines.append(
            f"F1 TRIGGERED for tf(s) {f1_triggered_tfs}: TLT per-symbol HMM shows gap >= 0.01 "
            f"with correct sign. Demotion premise fails for those tf(s) -- do NOT demote "
            f"per-symbol HMM to shadow for rates on this evidence; keep it live."
        )
    else:
        lines.append(
            "F1 NOT triggered on any tf: TLT per-symbol HMM stays deficient/inverted, "
            "matching the original 2026-07-02 finding. Default decision (b) demotion holds."
        )
        if not rates_spreads:
            lines.append(
                "F2 CANNOT be evaluated: no rates cross-sectional rows found for TLT. "
                "Verdict: INCONCLUSIVE on F2, do not act."
            )
        else:
            f2_triggered_tfs = [
                tf for tf, info in rates_spreads.items() if info["spread"] < _GAP_DEFICIENT
            ]
            for tf, info in sorted(rates_spreads.items()):
                band = classify_band(info["spread"])
                lines.append(
                    f"  rates cross_sectional tf={tf}: spread={info['spread']:+.4f} [{band}]"
                )
            if f2_triggered_tfs:
                lines.append(
                    f"F2 TRIGGERED for tf(s) {f2_triggered_tfs}: rates cross-sectional label "
                    f"ALSO deficient (spread < 0.01) on those tf(s) -- (b) leaves rates with no "
                    f"valid conditioning axis there. This is the pre-registered build trigger for "
                    f"the factor-augmented HMM challenger (option c), PENDING confirmation that "
                    f"volatility_pct has not separately passed its own substitution gate for "
                    f"rates (not evaluated by this script)."
                )
            else:
                lines.append(
                    "F2 NOT triggered: rates cross-sectional label clears the deficient band "
                    "on all measured tf(s). Decision (b) stands as designed -- demote per-symbol "
                    "HMM to shadow for rates, stratify on the cross-sectional rates label instead. "
                    "No challenger build needed."
                )

    return "\n".join(lines)


def run_measurement(conn: Any, tfs: list[str] | None) -> None:
    tlt_rows = _fetch_mean_ic_by_tf_regime(
        conn,
        symbol=_TLT_SYMBOL,
        regime_scope="symbol_hmm",
        is_pooled=False,
        regimes=None,
        tfs=tfs,
    )
    rates_rows = _fetch_mean_ic_by_tf_regime(
        conn,
        symbol="POOLED",
        regime_scope="cross_sectional",
        is_pooled=True,
        regimes=_RATES_CROSS_SECTIONAL_LABELS,
        tfs=tfs,
    )

    tlt_spreads = _spread_by_tf(tlt_rows)
    tlt_signed = _signed_trend_gap_by_tf(tlt_rows)
    rates_spreads = _spread_by_tf(rates_rows)

    _print_side_table("TLT per-symbol HMM (regime_scope=symbol_hmm)", tlt_spreads)
    _print_side_table("rates cross-sectional (regime_scope=cross_sectional, POOLED)", rates_spreads)

    print(render_verdict(tlt_signed, rates_spreads))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tf",
        nargs="*",
        default=None,
        help="Timeframe(s) to measure (default: all tfs present in feature_ic_scores)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Skip the STEP 0 precondition check and run the measurement anyway. "
            "DANGEROUS: violates D-07 single-writer discipline if the corpus rebuild "
            "is still in flight -- only use for testing against a known-complete corpus."
        ),
    )
    args = parser.parse_args()

    conn = _connect()
    try:
        is_fresh, evidence = check_precondition(conn)
        print("=== STEP 0: Precondition Check ===")
        print(evidence)

        if not is_fresh and not args.force:
            print("\nBLOCKED-ON-143.1-07")
            print(
                "The 143.1-07 corpus rebuild has not yet landed rows carrying the new "
                "regime_group routing (Phase 144 Plan 05). Per D-07 (single-writer "
                "discipline), this gate does NOT run its measurement queries against "
                "this corpus. Re-run this script once the rebuild completes."
            )
            sys.exit(1)

        if not is_fresh and args.force:
            print("\n--force set: proceeding despite failed precondition check. NOT RECOMMENDED.")

        run_measurement(conn, args.tf)
    finally:
        conn.rollback()  # read-only script; never commit
        conn.close()


if __name__ == "__main__":
    main()
