#!/usr/bin/env python3
"""Validate RollComputeAgent by replaying market_data_ohlcv bars through RollMonitor.

Deterministic backtest — no dependency on system_events or agent uptime.
Replays actual historical 1m bars through the algorithm and validates:
  1. Roll detected within known window
  2. Zero false positives in 30-day pre-window
  3. No double-fire within cooldown period

Usage:
    .venv/bin/python production/scripts/roll_backtest.py

Exit codes:
    0 = all checks passed
    1 = one or more checks failed
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncpg

from services.roll_compute_agent import RollMonitor
from src.config.settings import Settings

# ---------------------------------------------------------------------------
# Known historical rolls to validate.
# H6 → M6 quarterly transition — all equity index futures roll simultaneously
# (~2026-03-19 expiry, roll window approximately 2026-03-05 to 2026-03-16).
# ---------------------------------------------------------------------------
KNOWN_ROLLS: list[dict] = [
    {
        "base_symbol": "ES",
        "old_contract": "ESH6",
        "new_contract": "ESM6",
        "roll_window_start": datetime(2026, 3, 10, tzinfo=UTC),
        "roll_window_end": datetime(2026, 3, 21, tzinfo=UTC),
    },
    {
        "base_symbol": "NQ",
        "old_contract": "NQH6",
        "new_contract": "NQM6",
        "roll_window_start": datetime(2026, 3, 10, tzinfo=UTC),
        "roll_window_end": datetime(2026, 3, 21, tzinfo=UTC),
    },
    {
        "base_symbol": "RTY",
        "old_contract": "RTYH6",
        "new_contract": "RTYM6",
        "roll_window_start": datetime(2026, 3, 10, tzinfo=UTC),
        "roll_window_end": datetime(2026, 3, 21, tzinfo=UTC),
    },
    {
        "base_symbol": "YM",
        "old_contract": "YMH6",
        "new_contract": "YMM6",
        "roll_window_start": datetime(2026, 3, 10, tzinfo=UTC),
        "roll_window_end": datetime(2026, 3, 21, tzinfo=UTC),
    },
]


# ---------------------------------------------------------------------------
# Bar loading
# ---------------------------------------------------------------------------


async def load_bars(
    conn: asyncpg.Connection,
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Load 1m bars from market_data_ohlcv ordered by timestamp ascending."""
    rows = await conn.fetch(
        """
        SELECT timestamp, volume
        FROM market_data_ohlcv
        WHERE symbol = $1
          AND timeframe = '1m'
          AND timestamp >= $2
          AND timestamp < $3
        ORDER BY timestamp ASC
        """,
        symbol,
        start,
        end,
    )
    return [{"ts": r["timestamp"], "volume": float(r["volume"])} for r in rows]


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def replay_through_monitor(
    monitor: RollMonitor,
    base_symbol: str,
    bars: list[dict],
) -> list[datetime]:
    """Feed bars through RollMonitor and return list of detection timestamps."""
    detections: list[datetime] = []
    for bar in bars:
        monitor.update_volume(base_symbol, bar["volume"])
        if monitor.check_roll(base_symbol, bar["ts"]):
            detections.append(bar["ts"])
    return detections


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------


def validate_detection_in_window(
    detections: list[datetime],
    window_start: datetime,
    window_end: datetime,
    base_symbol: str,
) -> tuple[bool, str]:
    """Assert at least one detection falls within the known roll window."""
    in_window = [d for d in detections if window_start <= d <= window_end]
    if in_window:
        return True, f"detected at {in_window[0].isoformat()}"
    if detections:
        return False, f"detected but outside window: {[d.isoformat() for d in detections]}"
    return False, "no detection found — algorithm missed the roll"


def validate_no_false_positives(
    detections: list[datetime],
    pre_window_start: datetime,
    pre_window_end: datetime,
    base_symbol: str,
) -> tuple[bool, str]:
    """Assert no detections in the 30-day pre-window period."""
    false_positives = [d for d in detections if pre_window_start <= d < pre_window_end]
    if false_positives:
        return (
            False,
            f"{len(false_positives)} false positive(s): {[d.isoformat() for d in false_positives]}",
        )
    return True, "zero false positives"


def validate_no_double_fire(
    detections: list[datetime],
    cooldown_minutes: int,
) -> tuple[bool, str]:
    """Assert no two detections are closer than cooldown_minutes apart."""
    sorted_d = sorted(detections)
    for i in range(1, len(sorted_d)):
        gap = (sorted_d[i] - sorted_d[i - 1]).total_seconds() / 60
        if gap < cooldown_minutes:
            return (
                False,
                (
                    f"double-fire: {sorted_d[i - 1].isoformat()} and "
                    f"{sorted_d[i].isoformat()} ({gap:.0f}m apart, cooldown={cooldown_minutes}m)"
                ),
            )
    return True, f"no double-fire ({len(sorted_d)} detection(s) total)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def validate_known_roll(
    conn: asyncpg.Connection,
    settings: Settings,
    roll: dict,
) -> tuple[int, int]:
    """Validate a single known roll entry. Returns (passed_checks, failed_checks)."""
    base = roll["base_symbol"]
    old_contract = roll["old_contract"]

    print(f"\n--- {base}: {old_contract} -> {roll['new_contract']} ---")

    # Load bars from 30 days before roll window through roll window end
    pre_start = roll["roll_window_start"] - timedelta(days=30)
    bars = await load_bars(conn, old_contract, pre_start, roll["roll_window_end"])

    if len(bars) < 100:
        print(
            f"  [SKIP] Only {len(bars)} bars found for {old_contract} — insufficient data"
        )
        # Insufficient data counts as a failure for graduation purposes
        return 0, 1

    print(
        f"  Loaded {len(bars)} bars ({pre_start.date()} -> {roll['roll_window_end'].date()})"
    )

    # Fresh RollMonitor per symbol — no state bleed between symbols
    monitor = RollMonitor(settings)
    detections = replay_through_monitor(monitor, base, bars)

    pre_window_end = roll["roll_window_start"]

    passed = 0
    failed = 0

    # Check 1: Detection in window
    ok, msg = validate_detection_in_window(
        detections, roll["roll_window_start"], roll["roll_window_end"], base
    )
    passed += int(ok)
    failed += int(not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] Detection in window: {msg}")

    # Check 2: No false positives in 30-day pre-window
    ok, msg = validate_no_false_positives(detections, pre_start, pre_window_end, base)
    passed += int(ok)
    failed += int(not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] No false positives: {msg}")

    # Check 3: No double-fire within cooldown
    ok, msg = validate_no_double_fire(detections, settings.roll_monitor_cooldown_min)
    passed += int(ok)
    failed += int(not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] No double-fire: {msg}")

    return passed, failed


async def main() -> None:
    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)

    total_passed = 0
    total_failed = 0

    print("=" * 60)
    print("RollComputeAgent Backtest -- Bar Replay Validation")
    print("=" * 60)

    for roll in KNOWN_ROLLS:
        p, f = await validate_known_roll(conn, settings, roll)
        total_passed += p
        total_failed += f

    await conn.close()

    print(f"\n{'=' * 60}")
    print(f"Results: {total_passed} passed, {total_failed} failed")
    print(f"{'=' * 60}")

    if total_failed > 0:
        print("\nFAILED -- do NOT enable RollComputeAgent")
        sys.exit(1)
    else:
        print("\nPASSED -- safe to enable RollComputeAgent")
        print("Run: sudo systemctl enable --now indicagent-roll-compute.service")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
