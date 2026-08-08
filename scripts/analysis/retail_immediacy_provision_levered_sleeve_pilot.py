#!/usr/bin/env python3
"""retail_immediacy_provision levered-sleeve sharpening pilot -- Trade Construction
candidate, pre-registered design: docs/research/data-edge-source-thesis.md, "Retail
Immediacy Provision" section, "Statistic pinned 2026-08-07" addendum.

Mechanism: leveraged/inverse ETF issuers must rebalance into the close, price-
insensitive, sized by the day's own move. That flow lands on the underlying (which IS
in this universe), not on the (absent) levered products themselves.

Falsification bar (binary, pre-registered, no post-hoc magnitude judgment call):
per (symbol, RTH session day), co_movement = prior_return * last_bar_return, fed
straight into gate_math.frame_gate_passes (pnl_r_values=co_movement, cluster_ids=day)
-- one call per group, symbols pooled within a group. The levered-sleeve group must
PASS (ci_lower > 0) AND the no-sleeve control group must NOT pass. Any other outcome
falsifies the mechanism. BH-FDR is not applied on top -- only 2 pre-specified groups,
not a multi-cell sweep (see the pre-registration addendum for why that's a decision,
not a shortcut).

Read-only diagnostic -- no writes, no config_state changes, exit code always 0
(informational).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas_market_calendars as mcal  # noqa: E402
import structlog  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db, _fetch_bars_from_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.statistics.gate_math import frame_gate_passes  # noqa: E402

setup_service_logging("logs/retail_immediacy_provision_levered_sleeve_pilot.log")
_logger = structlog.get_logger(__name__)

_TF = "5m"
_ET = ZoneInfo("America/New_York")
_RTH_OPEN_ET = time(9, 30)
_RTH_CLOSE_ET = time(16, 0)

_LEVERED_GROUP = ["XLF", "XLE", "SMH", "XBI", "GDX", "TLT", "IWM", "QQQ", "SPY"]
_CONTROL_GROUP = ["SCHD", "SDOG", "USMV", "QUAL", "MUB", "PFF", "DBA"]


def _session_windows(start: datetime, end: datetime) -> dict[str, tuple[datetime, datetime]]:
    """NYSE RTH open/close per calendar date (ET), honoring half-days.

    Reuses the same pandas_market_calendars mechanism src/core/bar_normalizer.py's
    _slots_nyse already relies on for session boundaries -- no new calendar logic.
    Returns {date_iso: (session_open_utc, session_close_utc)}.
    """
    cal = mcal.get_calendar("NYSE")
    schedule = cal.schedule(
        start_date=start.astimezone(_ET).date().isoformat(),
        end_date=end.astimezone(_ET).date().isoformat(),
        tz="America/New_York",
    )
    windows: dict[str, tuple[datetime, datetime]] = {}
    for _, row in schedule.iterrows():
        day = row["market_open"].date()
        day_open = datetime.combine(day, _RTH_OPEN_ET, tzinfo=_ET)
        pmc_close_et = row["market_close"].astimezone(_ET)
        full_close = datetime.combine(day, _RTH_CLOSE_ET, tzinfo=_ET)
        day_close = pmc_close_et if pmc_close_et.hour < 16 else full_close
        windows[day.isoformat()] = (day_open.astimezone(UTC), day_close.astimezone(UTC))
    return windows


def _co_movements_for_symbol(
    bars: list[dict], windows: dict[str, tuple[datetime, datetime]]
) -> dict[str, float]:
    """One co_movement observation per session day this symbol has >=3 RTH bars for.

    prior_return excludes the final bar (not self-referential); last_bar_return is the
    final bar's own open->close move. Days with <3 bars (can't separate "prior" from
    "last") are skipped, not defaulted.
    """
    by_day: dict[str, list[dict]] = {}
    for b in bars:
        day_iso = b["ts"].astimezone(_ET).date().isoformat()
        window = windows.get(day_iso)
        if window is None:
            continue
        session_open, session_close = window
        if session_open <= b["ts"] < session_close:
            by_day.setdefault(day_iso, []).append(b)

    result: dict[str, float] = {}
    for day_iso, day_bars in by_day.items():
        if len(day_bars) < 3:
            continue
        day_bars.sort(key=lambda b: b["ts"])
        first_open = day_bars[0]["open"]
        second_last_close = day_bars[-2]["close"]
        last_open = day_bars[-1]["open"]
        last_close = day_bars[-1]["close"]
        if first_open <= 0 or second_last_close <= 0 or last_open <= 0:
            continue
        prior_return = _ln(second_last_close / first_open)
        last_bar_return = _ln(last_close / last_open)
        result[day_iso] = prior_return * last_bar_return
    return result


def _ln(x: float) -> float:
    import math

    return math.log(x)


def _run_group(
    label: str,
    symbols: list[str],
    conn,
    windows: dict[str, tuple[datetime, datetime]],
    *,
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
) -> tuple[bool, float, float, int]:
    pnl_r_values: list[float] = []
    cluster_ids: list[str] = []
    for symbol in symbols:
        bars = _fetch_bars_from_db(conn, symbol, _TF)
        co_moves = _co_movements_for_symbol(bars, windows)
        for day_iso, co_move in co_moves.items():
            pnl_r_values.append(co_move)
            cluster_ids.append(day_iso)

    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_r_values, cluster_ids, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
    )
    n_clusters = len(set(cluster_ids))
    verdict = "PASS" if passes else "no effect / fails"
    print(
        f"{label}: n_obs={len(pnl_r_values)} n_days={n_clusters} "
        f"ci=[{ci_lower:.8f}, {ci_upper:.8f}] -> {verdict}"
    )
    return bool(passes), ci_lower, ci_upper, len(pnl_r_values)


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    apr_dict = apr._cache

    min_n = int(_cfg(apr_dict, "alpha.scoring.min_strategy_n", 30))
    bootstrap_max_n = int(_cfg(apr_dict, "alpha.scoring.bootstrap_max_n", 5000))
    bootstrap_batch = int(_cfg(apr_dict, "alpha.scoring.bootstrap_batch", 1000))
    bootstrap_random_state = int(_cfg(apr_dict, "alpha.scoring.bootstrap_random_state", 42))

    print("retail_immediacy_provision levered-sleeve sharpening pilot -- tf=5m")
    print(
        f"min_n={min_n} bootstrap_max_n={bootstrap_max_n} "
        f"bootstrap_batch={bootstrap_batch} bootstrap_random_state={bootstrap_random_state}"
    )
    print(f"levered group ({len(_LEVERED_GROUP)}): {', '.join(_LEVERED_GROUP)}")
    print(f"control group ({len(_CONTROL_GROUP)}): {', '.join(_CONTROL_GROUP)}")

    print("\nBuilding NYSE RTH session windows (full available range) ...")
    now = datetime.now(UTC)
    windows = _session_windows(datetime(2005, 1, 1, tzinfo=UTC), now)
    print(f"  {len(windows)} NYSE trading days in range")

    print(
        "\n--- Falsification bar: co_movement = prior_return * last_bar_return, "
        "day-clustered bootstrap per group ---\n"
    )

    levered_passes, levered_lo, levered_hi, levered_n = _run_group(
        "LEVERED",
        _LEVERED_GROUP,
        conn,
        windows,
        min_n=min_n,
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
    )
    control_passes, control_lo, control_hi, control_n = _run_group(
        "CONTROL",
        _CONTROL_GROUP,
        conn,
        windows,
        min_n=min_n,
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
    )

    print(
        "\nVerdict rule (pre-registered, binary): levered group must PASS "
        "(ci_lower > 0) AND control group must NOT pass."
    )
    if levered_passes and not control_passes:
        print(
            "RESULT: MECHANISM SURVIVES -- levered-sleeve close-rebalance flow is a live candidate."
        )
    else:
        print(
            "RESULT: DEAD -- levered-sleeve mechanism falsified by this pilot's own pre-registered bar."
        )

    conn.close()


if __name__ == "__main__":
    main()
