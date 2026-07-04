#!/usr/bin/env python3
"""
ops_corpus_progress.py — live progress display for v3.0 corpus pipeline

Monitors all 6 steps of the corpus pipeline from feature_factory through alpha_publisher,
showing completion status, row counts, and estimated time remaining.
Run during corpus pipeline execution to monitor progress without querying the database directly.
Requires TimescaleDB with backfill_status tracking enabled.
"""

import subprocess
from datetime import datetime

EXPECTED_TFS = {"5m", "15m", "1h", "1d"}
PSQL = "PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent"


def query(sql: str) -> list[list[str]]:
    cmd = f"{PSQL} -t -A -F'|' -c \"{sql}\""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"query failed: {sql!r}\n{result.stderr}")
    rows = [line.split("|") for line in result.stdout.strip().splitlines() if line.strip()]
    return rows


def scalar(sql: str, default: str = "0") -> str:
    rows = query(sql)
    return rows[0][0] if rows else default


def _n_etf_symbols() -> int:
    """Live active-equity-instrument count — was a hardcoded 58, silently stale once the
    universe grew to 80 (22 new symbols added 2026-07-04, see the full-depth backfill plan)."""
    return int(
        scalar(
            "SELECT COUNT(*) FROM instruments "
            "WHERE is_active AND contract_details->>'asset_class' = 'equity'",
            default="58",
        )
    )


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

    N_ETF_SYMBOLS = _n_etf_symbols()

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
    # Step 3 — Forward Return Writer: forward_returns rows (separate table from
    # feature_vectors — there is no return_fast column on feature_vectors itself;
    # querying that nonexistent column used to error and get silently masked as 0%)
    # ------------------------------------------------------------------
    fwd_pairs = int(
        scalar(
            "SELECT COUNT(DISTINCT (symbol, tf)) FROM forward_returns WHERE return_fast IS NOT NULL"
        )
    )
    fwd_symbols = int(
        scalar("SELECT COUNT(DISTINCT symbol) FROM forward_returns WHERE return_fast IS NOT NULL")
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
    # Current step detail — each step's own completion (step_pairs >= total_pairs,
    # or the row-count check for steps 5/6) gates the next, in strict DAG order.
    # Previously this fell through to "Pipeline COMPLETE" off ae_rows > 0 alone,
    # which is stale rows from a prior run, not evidence steps 1-4 finished this
    # run — the exact silent-wrong-answer this project's principles forbid.
    # ------------------------------------------------------------------
    step1_done = fv_pairs >= total_pairs
    step2_done = regime_pairs >= total_pairs
    step3_done = fwd_pairs >= total_pairs
    step4_done = ic_symbols >= N_ETF_SYMBOLS
    step5_done = ew_rows > 0
    step6_done = ae_rows > 0

    if not step1_done:
        print("  Active: Step 1 — Feature Factory")
    elif not step2_done:
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
    elif not step3_done:
        print("  Active: Step 3 — Forward Return Writer")
    elif not step4_done:
        print("  Active: Step 4 — IC Engine")
    elif not step5_done:
        print("  Active: Step 5 — Ensemble Trainer")
    elif not step6_done:
        print("  Active: Step 6 — Alpha Publisher")
    else:
        print("  Pipeline COMPLETE")
    print()


if __name__ == "__main__":
    main()
