#!/usr/bin/env python3
"""Todo 167 falsifier gate: equity per-symbol HMM vs `equity` cross-sectional (breadth_vol)
regime IC separation.

Sibling of `scripts/analysis/phase144_regime_separation_gate.py` (Phase 144's D-05 gate for
`rates`/TLT), generalized from a single-symbol comparison to equity's ~50-symbol universe --
`services/ic_engine.py`'s regime-group routing has silently replaced every equity-routed
symbol's per-symbol HMM IC measurement with cross-sectional measurement since equity's regime
group was first enabled, and unlike `rates`, this choice was never falsifier-tested (todo 167).

Same reused machinery, no new statistics invented: `feature_ic_scores.mean(ic_value)` grouped
by (tf, regime), spread = max - min across a side's regime labels, classified against todo
026's bands (< 0.01 deficient, 0.01-0.05 ambiguous, > 0.05 adequate). `equity`'s per-symbol HMM
side has a natural bullish/bearish pairing (trending_up/trending_down, same vocabulary as
rates); the cross-sectional side uses breadth_vol's 9-label vocabulary
({low,mid,high}_{bull,bear,neutral}, `src/intelligence/regime_signals/breadth_vol.py`), which
has no single natural up/down pair -- only the unsigned spread is computed for that side, same
convention as the rates gate.

Generalization the rates gate didn't need to make (equity has ~50 symbols, not 1): this script
reports the FULL per-symbol distribution, not just an aggregate, and pre-registers a majority
rule for the F1-equivalent verdict (documented in `render_verdict`'s docstring) -- this
aggregation choice is this script's own deliverable, exactly as the rates gate's docstring
flagged its own design choices as not prescribed anywhere else.

HARD PRECONDITION: this script's measurement queries must never run against a stale or
in-flight corpus. STEP 0 checks for the existence of ANY feature_ic_scores row carrying
regime_scope='symbol_hmm' for an equity symbol -- confirmed zero as of 2026-07-21 (todo 167),
and will stay zero until migration 262's dual_write_symbol_hmm=true flag (equity) is picked up
by a fresh ic_engine run. Absence of such rows is proof this gate cannot run yet, not a
hardcoded row count or date.

Usage:
    .venv/bin/python scripts/analysis/equity_regime_separation_gate.py
    .venv/bin/python scripts/analysis/equity_regime_separation_gate.py --tf 15m 1h
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
_F1_MAJORITY_FRACTION = 0.5  # this script's own pre-registered aggregation choice, see docstring

_LABEL_TRENDING_UP = "trending_up"
_LABEL_TRENDING_DOWN = "trending_down"

# breadth_vol.py's 9-label vocabulary ({low,mid,high} x {bull,bear,neutral}).
_EQUITY_CROSS_SECTIONAL_LABELS: tuple[str, ...] = (
    "low_bull",
    "low_bear",
    "low_neutral",
    "mid_bull",
    "mid_bear",
    "mid_neutral",
    "high_bull",
    "high_bear",
    "high_neutral",
)


def _dsn() -> str:
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


def _fetch_equity_symbols(conn: Any) -> list[str]:
    """Symbols actually routed to the `equity` regime_group, derived from instrument_tags --
    never hardcoded (CLAUDE.md). NOTE: this is NOT the same set as
    `instruments.contract_details->>'asset_class'='equity'` -- that column marks ETF-wrapper
    instrument type, not regime-group routing. `services/ic_engine.py`'s `_resolve_symbol_routing`
    matches a symbol to a group by instrument_tags prefix (`alpha.regime.groups`'s
    `tag_filter`, `eq_*`/`intl_*` for equity), and several `asset_class='equity'` ETFs (TLT,
    GLD, FXA, HYG, ...) are actually tagged fi_*/commodity_*/fx_* and route elsewhere. Using
    the wrong filter here would silently measure the wrong symbols entirely -- confirmed by
    hand during this script's own development (2026-07-27): the asset_class filter returned
    29/80 symbols with STALE pre-migration-262 symbol_hmm rows (leftover from those symbols
    never being suppressed in the first place, since they were never routed to equity's
    cross-sectional group) while SPY -- routed to equity -- correctly showed zero, exactly
    matching todo 167's original finding.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT symbol FROM instrument_tags
            WHERE tag LIKE 'eq\\_%' OR tag LIKE 'intl\\_%'
            ORDER BY symbol
            """)
        return [row[0] for row in cur.fetchall()]


def check_precondition(conn: Any, equity_symbols: list[str]) -> tuple[bool, str]:
    """STEP 0 -- precondition check, same discipline as the rates gate (D-07/D-08)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(DISTINCT symbol) AS n_symbols, count(*) AS n_rows, max(computed_at) AS latest
            FROM feature_ic_scores
            WHERE regime_scope = 'symbol_hmm' AND symbol = ANY(%(symbols)s)
            """,
            {"symbols": equity_symbols},
        )
        n_symbols, n_rows, latest = cur.fetchone()

    if not n_rows:
        evidence = (
            f"Zero feature_ic_scores rows found with regime_scope='symbol_hmm' for any of "
            f"{len(equity_symbols)} active equity symbols. This can only exist after migration "
            f"262's dual_write_symbol_hmm=true (equity) has been picked up by a fresh "
            f"ic_engine run -- config loads once at process startup, so the currently in-flight "
            f"todo 183 recompute (started before migration 262) will NOT produce these rows. "
            f"Re-run this script after the next ic_engine run completes."
        )
        return False, evidence

    evidence = (
        f"Found {n_rows} symbol_hmm-scope rows across {n_symbols}/{len(equity_symbols)} equity "
        f"symbols, max(computed_at)={latest}."
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
        }
    return result


def _signed_trend_gap_by_tf(rows: list[dict]) -> dict[str, float]:
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


def render_verdict(
    per_symbol_signed_gap: dict[str, dict[str, float]],
    cross_sectional_spreads: dict[str, dict],
) -> str:
    """F1/F2-equivalent verdict, generalized to equity's ~50-symbol universe.

    F1 (this script's own majority-rule generalization, pre-registered here since no
    equivalent exists elsewhere): per tf, if >= _F1_MAJORITY_FRACTION of measured equity
    symbols individually show signed_gap >= 0.01 with correct (positive) sign, per-symbol
    HMM demonstrably carries real conditioning power for equity as a group -- demotion
    premise fails for that tf, keep per-symbol HMM live (or dual-write) for equity there.
    F2: else (majority not reached) -- if the equity cross-sectional label's own spread ALSO
    lands in the deficient band, equity has no valid conditioning axis via either mechanism
    on that tf.
    """
    lines = ["\n=== Todo 167 Falsifier Verdict (equity, majority-rule generalization) ==="]

    if not per_symbol_signed_gap:
        lines.append(
            "No equity symbol has both trending_up/trending_down symbol_hmm rows -- "
            "cannot evaluate F1. Verdict: INCONCLUSIVE, do not act."
        )
        return "\n".join(lines)

    all_tfs = sorted({tf for gaps in per_symbol_signed_gap.values() for tf in gaps})
    f1_triggered_tfs = []
    for tf in all_tfs:
        gaps_this_tf = [gaps[tf] for gaps in per_symbol_signed_gap.values() if tf in gaps]
        n_correct_sign_adequate = sum(1 for g in gaps_this_tf if g >= _GAP_DEFICIENT)
        frac = n_correct_sign_adequate / len(gaps_this_tf) if gaps_this_tf else 0.0
        median_gap = sorted(gaps_this_tf)[len(gaps_this_tf) // 2] if gaps_this_tf else 0.0
        lines.append(
            f"  tf={tf:<4} n_symbols={len(gaps_this_tf)} "
            f"frac_correct_sign_adequate={frac:.2f} median_signed_gap={median_gap:+.4f}"
        )
        if frac >= _F1_MAJORITY_FRACTION:
            f1_triggered_tfs.append(tf)

    if f1_triggered_tfs:
        lines.append(
            f"F1 TRIGGERED for tf(s) {f1_triggered_tfs}: a majority of equity symbols "
            f"individually show per-symbol HMM signed_gap >= 0.01 with correct sign. Demotion "
            f"premise fails for those tf(s) -- per-symbol HMM carries real conditioning power "
            f"for equity as a group; do not treat cross-sectional-only as settled there."
        )
    else:
        lines.append(
            "F1 NOT triggered on any tf: no tf shows a majority of equity symbols with an "
            "adequate, correctly-signed per-symbol HMM gap."
        )

    if not cross_sectional_spreads:
        lines.append("F2 CANNOT be evaluated: no equity cross-sectional rows found.")
    else:
        f2_triggered_tfs = [
            tf for tf, info in cross_sectional_spreads.items() if info["spread"] < _GAP_DEFICIENT
        ]
        for tf, info in sorted(cross_sectional_spreads.items()):
            band = classify_band(info["spread"])
            lines.append(f"  equity cross_sectional tf={tf}: spread={info['spread']:+.4f} [{band}]")
        if f2_triggered_tfs:
            lines.append(
                f"F2 TRIGGERED for tf(s) {f2_triggered_tfs}: equity cross-sectional label ALSO "
                f"deficient (spread < 0.01) on those tf(s) -- neither mechanism separates IC "
                f"there."
            )
        else:
            lines.append(
                "F2 NOT triggered: equity cross-sectional label clears the deficient band."
            )

    return "\n".join(lines)


def run_measurement(conn: Any, equity_symbols: list[str], tfs: list[str] | None) -> None:
    per_symbol_signed_gap: dict[str, dict[str, float]] = {}
    per_symbol_spreads: dict[str, dict[str, dict]] = {}

    for symbol in equity_symbols:
        rows = _fetch_mean_ic_by_tf_regime(
            conn, symbol=symbol, regime_scope="symbol_hmm", is_pooled=False, regimes=None, tfs=tfs
        )
        if not rows:
            continue
        signed = _signed_trend_gap_by_tf(rows)
        if signed:
            per_symbol_signed_gap[symbol] = signed
        spreads = _spread_by_tf(rows)
        if spreads:
            per_symbol_spreads[symbol] = spreads

    cross_sectional_rows = _fetch_mean_ic_by_tf_regime(
        conn,
        symbol="POOLED",
        regime_scope="cross_sectional",
        is_pooled=True,
        regimes=_EQUITY_CROSS_SECTIONAL_LABELS,
        tfs=tfs,
    )
    cross_sectional_spreads = _spread_by_tf(cross_sectional_rows)

    print(
        f"\nMeasured symbol_hmm rows for {len(per_symbol_signed_gap)}/{len(equity_symbols)} equity symbols."
    )
    print("\nequity cross-sectional (regime_scope=cross_sectional, POOLED):")
    for tf, info in sorted(cross_sectional_spreads.items()):
        band = classify_band(info["spread"])
        print(
            f"  tf={tf:<4} spread={info['spread']:+.4f} [{band}] "
            f"max={info['max_regime']}({info['max_ic']:+.4f}) min={info['min_regime']}({info['min_ic']:+.4f})"
        )

    print(render_verdict(per_symbol_signed_gap, cross_sectional_spreads))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tf", nargs="*", default=None, help="Timeframe(s) to measure")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip STEP 0 precondition check. DANGEROUS -- only for testing against known data.",
    )
    args = parser.parse_args()

    conn = _connect()
    try:
        equity_symbols = _fetch_equity_symbols(conn)
        is_fresh, evidence = check_precondition(conn, equity_symbols)
        print("=== STEP 0: Precondition Check ===")
        print(evidence)

        if not is_fresh and not args.force:
            print("\nBLOCKED-ON-NEXT-IC-ENGINE-RUN")
            print(
                "Migration 262 (equity dual_write_symbol_hmm=true) has not yet been picked up "
                "by a fresh ic_engine run. Re-run this script once that run completes."
            )
            sys.exit(1)

        if not is_fresh and args.force:
            print("\n--force set: proceeding despite failed precondition check. NOT RECOMMENDED.")

        run_measurement(conn, equity_symbols, args.tf)
    finally:
        conn.rollback()  # read-only script; never commit
        conn.close()


if __name__ == "__main__":
    main()
