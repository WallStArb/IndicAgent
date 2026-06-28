#!/usr/bin/env python3
"""
Corpus Progress Monitor - live progress display for v3.0 corpus pipeline.

Version: 1.0
Status: current
Last Updated: 2026-06-28

Monitors all 6 steps of the v3.0 corpus pipeline:
1. feature_factory (bars → feature_vectors)
2. regime_writer (HMM per-symbol regimes)
3. forward_return_writer (executable returns)
4. ic_engine (Information Coefficient computation)
5. ensemble_trainer (weighted ensemble construction)
6. alpha_publisher (alpha_events emission)

Usage:
    python scripts/ops/corpus/ops_corpus_progress.py
"""

import subprocess
from datetime import datetime

EXPECTED_TFS = {"5m", "15m", "1h", "1d"}
PSQL = "PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent"
N_ETF_SYMBOLS = 58


def query(sql: str) -> list[list[str]]:
    cmd = f"{PSQL} -t -A -F'|' -c \"{sql}\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    rows = [line.split("|") for line in result.stdout.strip().splitlines() if line.strip()]
    return rows


def scalar(sql: str, default: str = "0") -> str:
    rows = query(sql)
    return rows[0][0] if rows else default


def bar(done: int, total: int, width: int = 40) -> str:
    filled = int(width * done / total) if total else 0
    return "#" * filled + "-" * (width - filled)


def step_bar(label: str, done: int, total: int) -> str:
    pct = done / total * 100 if total else 0
    return f"  [{bar(done, total)}] {pct:5.1f}%  {label}"


def main() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print()
    print(f"  v3.0 Corpus Pipeline Progress — {now}")
    print(f"  {'─' * 60}")

    # ------------------------------------------------------------------
    # Step 1 — Feature Factory: feature_vectors rows
    # ------------------------------------------------------------------
    fv_symbols = int(scalar("SELECT COUNT(DISTINCT symbol) FROM feature_vectors"))
    fv_pairs = int(scalar("SELECT COUNT(DISTINCT (symbol, tf)) FROM feature_vectors"))
    total_pairs = N_ETF_SYMBOLS * len(EXPECTED_TFS)
    print(
        step_bar(
            f"Step 1  Feature Factory   {fv_symbols}/{N_ETF_SYMBOLS} symbols, {fv_pairs}/{total_pairs} pairs",
            fv_pairs,
            total_pairs,
        )
    )

    # ------------------------------------------------------------------
    # Step 2 — Regime Writer: feature_vectors rows with regime filled
    # ------------------------------------------------------------------
    regime_pairs = int(
        scalar("SELECT COUNT(DISTINCT (symbol, tf)) FROM feature_vectors WHERE regime IS NOT NULL")
    )
    regime_symbols = int(
        scalar("SELECT COUNT(DISTINCT symbol) FROM feature_vectors WHERE regime IS NOT NULL")
    )
    print(
        step_bar(
            f"Step 2  Regime Writer     {regime_symbols}/{N_ETF_SYMBOLS} symbols, {regime_pairs}/{total_pairs} pairs",
            regime_pairs,
            total_pairs,
        )
    )

    # ------------------------------------------------------------------
    # Step 3 — Forward Return Writer: feature_vectors rows with return_fast filled
    # ------------------------------------------------------------------
    fwd_pairs = int(
        scalar(
            "SELECT COUNT(DISTINCT (symbol, tf)) FROM feature_vectors WHERE return_fast IS NOT NULL"
        )
    )
    fwd_symbols = int(
        scalar("SELECT COUNT(DISTINCT symbol) FROM feature_vectors WHERE return_fast IS NOT NULL")
    )
    print(
        step_bar(
            f"Step 3  Forward Returns   {fwd_symbols}/{N_ETF_SYMBOLS} symbols, {fwd_pairs}/{total_pairs} pairs",
            fwd_pairs,
            total_pairs,
        )
    )

    # ------------------------------------------------------------------
    # Step 4 — IC Engine: feature_ic_scores rows
    # ------------------------------------------------------------------
    ic_rows = int(scalar("SELECT COUNT(*) FROM feature_ic_scores WHERE is_pooled = false"))
    ic_symbols = int(
        scalar("SELECT COUNT(DISTINCT symbol) FROM feature_ic_scores WHERE is_pooled = false")
    )
    # Expected: 58 symbols × 4 TFs × 3 regimes × 4 lookaheads × ~54 features (varies by FDR)
    # Use symbols as proxy
    print(
        step_bar(
            f"Step 4  IC Engine         {ic_symbols}/{N_ETF_SYMBOLS} symbols  ({ic_rows:,} scores)",
            ic_symbols,
            N_ETF_SYMBOLS,
        )
    )

    # ------------------------------------------------------------------
    # Step 5 — Ensemble Trainer: ensemble_weights + ensemble_alpha
    # ------------------------------------------------------------------
    ew_rows = int(scalar("SELECT COUNT(*) FROM ensemble_weights"))
    ea_rows = int(scalar("SELECT COUNT(*) FROM ensemble_alpha"))
    ew_done = 1 if ew_rows > 0 else 0
    print(
        step_bar(
            f"Step 5  Ensemble Trainer  {ew_rows:,} weights  {ea_rows:,} alpha rows", ew_done, 1
        )
    )

    # ------------------------------------------------------------------
    # Step 6 — Alpha Publisher: alpha_events
    # ------------------------------------------------------------------
    ae_rows = int(scalar("SELECT COUNT(*) FROM alpha_events"))
    ae_done = 1 if ae_rows > 0 else 0
    print(step_bar(f"Step 6  Alpha Publisher   {ae_rows:,} events", ae_done, 1))

    print()

    # ------------------------------------------------------------------
    # Current step detail
    # ------------------------------------------------------------------
    if regime_pairs < total_pairs and fv_pairs >= total_pairs:
        print("  Active: Step 2 — Regime Writer")
        regime_done_syms = [
            r[0]
            for r in query(
                "SELECT DISTINCT symbol FROM feature_vectors WHERE regime IS NOT NULL ORDER BY symbol"
            )
        ]
        regime_pending = [
            r[0]
            for r in query(
                "SELECT DISTINCT symbol FROM feature_vectors WHERE regime IS NULL ORDER BY symbol LIMIT 10"
            )
        ]
        if regime_done_syms:
            print(f"  Done ({len(regime_done_syms)}): {', '.join(regime_done_syms)}")
        if regime_pending:
            print(
                f"  Next up: {', '.join(regime_pending[:5])}{'...' if len(regime_pending) > 5 else ''}"
            )
        print()
    elif fwd_pairs < total_pairs and regime_pairs >= total_pairs:
        print("  Active: Step 3 — Forward Return Writer")
    elif ic_symbols < N_ETF_SYMBOLS and fwd_pairs >= total_pairs:
        print("  Active: Step 4 — IC Engine")
    elif ew_rows == 0 and ic_symbols >= N_ETF_SYMBOLS:
        print("  Active: Step 5 — Ensemble Trainer")
    elif ae_rows == 0 and ew_rows > 0:
        print("  Active: Step 6 — Alpha Publisher")
    elif ae_rows > 0:
        print("  Pipeline COMPLETE")
    else:
        print("  Active: Step 1 — Feature Factory")
    print()


if __name__ == "__main__":
    main()
