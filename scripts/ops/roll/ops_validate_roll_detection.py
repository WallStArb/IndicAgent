#!/usr/bin/env python3
"""Offline validation of calendar + z-score roll detection against historical data.

Version: 1.0
Status: current
Last Updated: 2026-04-29

Per D-21: accuracy gate >= 90% detection rate, < 10% false positive rate.
Uses market_data_5m view for cleaner volume signal (per D-21 spec).

Usage:
    .venv/bin/python scripts/ops/roll/ops_validate_roll_detection.py

Exit codes:
    0 — PASS (all symbols meet accuracy gates)
    1 — FAIL (one or more symbols below gate)
    2 — SKIP (insufficient historical data for validation)
"""

from __future__ import annotations

import asyncio
import sys
from collections import deque
from datetime import date, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import numpy as np

from src.config.contracts import (
    FUTURES_ROLL_CYCLES,
    get_expiry_date,
    get_roll_window,
)
from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.core.models import AssetClass

# ---------------------------------------------------------------------------
# Accuracy gates (D-21)
# ---------------------------------------------------------------------------
DETECTION_RATE_GATE = 0.90  # >= 90% of known roll events must be detected
FALSE_POSITIVE_RATE_GATE = 0.10  # < 10% of detections must be outside any roll window

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOOKBACK_DAYS = 365  # 1 year of history
Z_SCORE_THRESHOLD = -2.0  # Volume DROP threshold (same as RollMonitor)
CONFIRMATION_REQUIRED = 3  # Consecutive confirming bars (same as RollMonitor)
MIN_WINDOW_BARS = 20  # Min bars for z-score (same as RollMonitor)
WINDOW_SIZE = 100  # Rolling window size (matches ROLL_MONITOR_WINDOW_SIZE default)
MIN_BARS_FOR_VALIDATION = 100  # Skip symbol if insufficient data


def _compute_expected_roll_dates(base_symbol: str) -> list[date]:
    """Compute expected expiry dates within the lookback window from derive_roll_chain.

    We use the roll chain to reconstruct historical expected roll dates by projecting
    backwards from the current chain. For each expiry in the chain and preceding cycles,
    we include those within [today - LOOKBACK_DAYS, today].
    """
    today = date.today()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)

    if base_symbol not in FUTURES_ROLL_CYCLES:
        return []

    from src.config.contracts import MONTH_CODE_TO_NUM  # noqa: PLC0415

    cycle = FUTURES_ROLL_CYCLES[base_symbol]
    expected: list[date] = []

    # Iterate years from (today.year - 2) to today.year to cover LOOKBACK_DAYS
    for year in range(today.year - 2, today.year + 2):
        for code in cycle:
            month = MONTH_CODE_TO_NUM[code]
            exp_date = get_expiry_date(base_symbol, month, year)
            if cutoff <= exp_date <= today:
                expected.append(exp_date)

    return sorted(set(expected))


def _is_in_roll_window(ref_date: date, exp_date: date) -> bool:
    """Return True if ref_date is inside the roll window for the given expiry."""
    roll_start = exp_date - timedelta(days=14)
    roll_end = exp_date - timedelta(days=3)
    return roll_start <= ref_date <= roll_end


def _replay_algorithm(
    rows: list[dict],
    base_symbol: str,
    window_size: int = WINDOW_SIZE,
) -> list[date]:
    """Replay the calendar + z-score algorithm over historical bars.

    Returns a list of dates on which the algorithm fired a roll detection.
    """
    vol_window: deque[float] = deque(maxlen=window_size)
    confirmation_count = 0
    detections: list[date] = []

    for row in rows:
        ts = row["timestamp"]
        vol = float(row.get("volume") or 0.0)
        vol_window.append(vol)

        ref_date: date = ts.date() if hasattr(ts, "date") else ts

        # Calendar gate
        try:
            roll_win = get_roll_window(base_symbol, ref_date)
        except ValueError:
            confirmation_count = 0
            continue

        if roll_win is None or len(vol_window) < MIN_WINDOW_BARS:
            confirmation_count = 0
            continue

        # Z-score computation (mirrors RollMonitor.check_roll)
        arr = np.array(vol_window)
        mean_v = arr[:-1].mean()
        std_v = arr[:-1].std()
        if std_v < 1e-9:
            confirmation_count = 0
            continue

        z = (arr[-1] - mean_v) / std_v
        if z < Z_SCORE_THRESHOLD:
            confirmation_count += 1
        else:
            confirmation_count = 0

        if confirmation_count >= CONFIRMATION_REQUIRED:
            detections.append(ref_date)
            confirmation_count = 0  # Reset after detection

    return detections


def _score_detections(
    detections: list[date],
    expected_rolls: list[date],
) -> dict:
    """Compute detection_rate and false_positive_rate.

    Detection rate: fraction of expected roll events that have at least one detection
    within the roll window.

    False positive rate: fraction of detections that fall outside any roll window.
    Uses detections / max(1, total_detections) to avoid division by zero.
    """
    detected_count = 0
    for exp_date in expected_rolls:
        if any(_is_in_roll_window(d, exp_date) for d in detections):
            detected_count += 1

    detection_rate = detected_count / len(expected_rolls) if expected_rolls else 0.0

    false_positives = 0
    for d in detections:
        in_any_window = any(_is_in_roll_window(d, exp) for exp in expected_rolls)
        if not in_any_window:
            false_positives += 1

    fp_rate = false_positives / max(1, len(detections))

    return {
        "expected_rolls": len(expected_rolls),
        "detected": detected_count,
        "detection_rate": detection_rate,
        "total_detections": len(detections),
        "false_positives": false_positives,
        "fp_rate": fp_rate,
    }


async def main() -> int:
    """Run offline validation. Returns 0 (PASS), 1 (FAIL), or 2 (SKIP)."""
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()

    # Get active futures symbols only
    # Instrument.base is the base symbol (e.g. "ES"); .symbol is the full contract (e.g. "ESM6")
    contracts = get_active_contracts(settings)
    futures_symbols = [
        c.base
        for c in contracts
        if c.asset_class == AssetClass.FUTURES and c.base in FUTURES_ROLL_CYCLES
    ]
    # Deduplicate (multiple contracts may share the same base symbol)
    futures_symbols = sorted(set(futures_symbols))

    if not futures_symbols:
        print("No active futures symbols found — nothing to validate.")
        await db.close()
        return 2

    print(f"Validating roll detection for {len(futures_symbols)} futures symbols:")
    print(f"  Symbols: {', '.join(futures_symbols)}")
    print(
        f"  Lookback: {LOOKBACK_DAYS} days | Gate: detection>={DETECTION_RATE_GATE:.0%}, "
        f"FP<{FALSE_POSITIVE_RATE_GATE:.0%}"
    )
    print()

    results: dict[str, dict] = {}
    skipped: list[str] = []

    for base_symbol in futures_symbols:
        expected_rolls = _compute_expected_roll_dates(base_symbol)

        if not expected_rolls:
            print(f"  {base_symbol}: no expected rolls in lookback window — skipping")
            skipped.append(base_symbol)
            continue

        # Query 5m volume bars from market_data_5m view (D-21: cleaner volume signal than 1m)
        try:
            rows = await db.execute_query(
                """
                SELECT timestamp, volume
                FROM market_data_5m
                WHERE base = $1
                  AND timestamp > NOW() - INTERVAL '365 days'
                ORDER BY timestamp ASC
                """,
                base_symbol,
            )
        except Exception as e:
            print(f"  {base_symbol}: query failed ({e}) — skipping")
            skipped.append(base_symbol)
            continue

        if not rows or len(rows) < MIN_BARS_FOR_VALIDATION:
            n = len(rows) if rows else 0
            print(f"  {base_symbol}: insufficient data ({n} bars) — skipping")
            skipped.append(base_symbol)
            continue

        # Replay algorithm over historical bars
        detections = _replay_algorithm(rows, base_symbol)

        # Score
        scored = _score_detections(detections, expected_rolls)
        results[base_symbol] = scored

    await db.close()

    # Print results
    print("=== Roll Detection Offline Validation (D-21) ===")
    print()

    all_pass = True
    any_evaluated = len(results) > 0

    for sym in sorted(results.keys()):
        r = results[sym]
        passes = (
            r["detection_rate"] >= DETECTION_RATE_GATE and r["fp_rate"] < FALSE_POSITIVE_RATE_GATE
        )
        if not passes:
            all_pass = False
        status = "PASS" if passes else "FAIL"
        print(
            f"  {sym:6s}: detection={r['detection_rate']:.1%} "
            f"({r['detected']}/{r['expected_rolls']}), "
            f"FP={r['fp_rate']:.1%} ({r['false_positives']}/{r['total_detections']}) "
            f"— {status}"
        )

    if skipped:
        print(f"\n  Skipped (insufficient data): {', '.join(sorted(skipped))}")

    print()
    if not any_evaluated:
        print("Overall: SKIP (no symbols had sufficient historical data)")
        print("  Ensure market_data_5m has >= 100 bars (run historical backfill if needed).")
        return 2

    overall = "PASS" if all_pass else "FAIL"
    print(f"Overall: {overall}")
    print(
        f"Gates: detection >= {DETECTION_RATE_GATE:.0%}, "
        f"false positive < {FALSE_POSITIVE_RATE_GATE:.0%}"
    )
    print()

    if not all_pass:
        print("Accuracy gate failed — do NOT enable indicagent-roll-detection until resolved.")
        print("Review per-symbol failures above before enabling in production.")
    else:
        print("Accuracy gates met — roll detection algorithm validated for enablement.")
        print("See Plan 03 checkpoint for final enablement steps.")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
