#!/usr/bin/env python3
"""dealer_hedging_flow options-expiry calendar screen -- Trade Construction candidate,
pre-registered design: docs/research/data-edge-source-thesis.md, "Dealer Hedging Flow"
section, "Statistic pinned 2026-08-08" addendum.

Mechanism: options dealers net long gamma must trade against price moves to stay
delta-neutral (sell strength, buy weakness), mechanically dampening intraday mean
reversion. That gamma exposure is sized by open interest that changes discretely at
monthly expiry -- so mean-reversion strength should fade in the sessions immediately
after expiry vs. immediately before, and that fade should concentrate in heavily-
optioned underlyings, not show up in negligibly-optioned ones. This is a cheap OHLCV
screen gating whether an options-chain data source is worth paying for -- not a
substitute for the real dealer-gamma-exposure version.

Falsification bar (binary, pre-registered, no post-hoc magnitude judgment call):
per (symbol, expiry-month), delta = mean(mean_reversion_proxy, POST 3 sessions) -
mean(mean_reversion_proxy, PRE 3 sessions incl. expiry Friday), fed into
gate_math.frame_gate_passes (pnl_r_values=delta, cluster_ids=expiry_month). The
heavily-optioned group must PASS (ci_lower > 0) AND the negligibly-optioned control
group must NOT. Any other outcome falsifies the mechanism.

Read-only diagnostic -- no writes, no config_state changes, exit code always 0.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas_market_calendars as mcal  # noqa: E402
import structlog  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db, _fetch_bars_from_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.statistics.gate_math import frame_gate_passes  # noqa: E402

setup_service_logging("logs/dealer_hedging_flow_expiry_calendar_pilot.log")
_logger = structlog.get_logger(__name__)

_TF = "5m"
_ET = ZoneInfo("America/New_York")
_RTH_OPEN_ET = time(9, 30)
_RTH_CLOSE_ET = time(16, 0)
_MIN_BARS_PER_SESSION = 30

_HEAVY_GROUP = ["SPY", "QQQ", "IWM", "TLT", "GLD", "SMH"]
_CONTROL_GROUP = ["SDOG", "SPHB", "CIBR", "IPO", "QUAL"]


def _third_fridays(start: datetime, end: datetime) -> list[datetime]:
    """3rd Friday of every month in [start, end] -- standard equity/index options expiry."""
    result = []
    d = start.astimezone(_ET).date().replace(day=1)
    end_date = end.astimezone(_ET).date()
    while d <= end_date:
        fridays_seen = 0
        for day in range(1, 29):
            candidate = d.replace(day=day)
            if candidate.weekday() == 4:  # Friday
                fridays_seen += 1
                if fridays_seen == 3:
                    if start.astimezone(_ET).date() <= candidate <= end_date:
                        result.append(datetime.combine(candidate, time(0, 0), tzinfo=_ET))
                    break
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


def _session_windows(cal, start: datetime, end: datetime) -> list[tuple]:
    """NYSE RTH open/close per trading day (ET, half-day aware). Returns sorted list of
    (date, session_open_utc, session_close_utc).
    """
    schedule = cal.schedule(
        start_date=start.astimezone(_ET).date().isoformat(),
        end_date=end.astimezone(_ET).date().isoformat(),
        tz="America/New_York",
    )
    windows = []
    for _, row in schedule.iterrows():
        day = row["market_open"].date()
        day_open = datetime.combine(day, _RTH_OPEN_ET, tzinfo=_ET)
        pmc_close_et = row["market_close"].astimezone(_ET)
        full_close = datetime.combine(day, _RTH_CLOSE_ET, tzinfo=_ET)
        day_close = pmc_close_et if pmc_close_et.hour < 16 else full_close
        windows.append((day, day_open.astimezone(UTC), day_close.astimezone(UTC)))
    windows.sort(key=lambda w: w[0])
    return windows


def _lag1_autocorr(returns: np.ndarray) -> float | None:
    if len(returns) < 4:
        return None
    x0, x1 = returns[:-1], returns[1:]
    if np.std(x0) < 1e-12 or np.std(x1) < 1e-12:
        return None
    corr = float(np.corrcoef(x0, x1)[0, 1])
    return None if np.isnan(corr) else corr


def _proxy_by_date(bars: list[dict], windows: list[tuple]) -> dict:
    """mean_reversion_proxy = -1 * lag-1 autocorr of 5m RTH returns, per trading day."""
    by_day: dict = {}
    win_by_date = {d: (o, c) for d, o, c in windows}
    for b in bars:
        day = b["ts"].astimezone(_ET).date()
        window = win_by_date.get(day)
        if window is None:
            continue
        session_open, session_close = window
        if session_open <= b["ts"] < session_close:
            by_day.setdefault(day, []).append(b)

    result: dict = {}
    for day, day_bars in by_day.items():
        if len(day_bars) < _MIN_BARS_PER_SESSION:
            continue
        day_bars.sort(key=lambda b: b["ts"])
        closes = np.array([b["close"] for b in day_bars], dtype=float)
        if np.any(closes <= 0):
            continue
        rets = np.diff(np.log(closes))
        autocorr = _lag1_autocorr(rets)
        if autocorr is not None:
            result[day] = -1.0 * autocorr
    return result


def _deltas_for_symbol(
    proxy_by_date: dict, expiries: list[datetime], all_dates: list
) -> dict[str, float]:
    """One delta per expiry-month this symbol has full PRE+POST coverage for."""
    sorted_dates = sorted(all_dates)
    deltas: dict[str, float] = {}
    for expiry in expiries:
        expiry_date = expiry.date()
        if expiry_date not in sorted_dates:
            continue
        idx = sorted_dates.index(expiry_date)
        # Expiry Friday itself is EXCLUDED from both buckets (corrected 2026-08-08): SPX/NDX/
        # RUT index options (the dominant, most liquid market on these underlyings) are
        # AM-settled off Friday's opening print, so Friday is a same-day transition -- lumping
        # it into PRE mislabels a post-unwind morning as pre-unwind. PRE = the 3 sessions before
        # expiry week's Friday; POST = the 3 sessions after.
        pre_dates = sorted_dates[max(0, idx - 3) : idx]  # 3 before expiry Friday
        post_dates = sorted_dates[idx + 1 : idx + 4]  # 3 after
        if len(pre_dates) < 3 or len(post_dates) < 3:
            continue
        pre_vals = [proxy_by_date[d] for d in pre_dates if d in proxy_by_date]
        post_vals = [proxy_by_date[d] for d in post_dates if d in proxy_by_date]
        if len(pre_vals) < 3 or len(post_vals) < 3:
            continue
        month_key = f"{expiry_date.year:04d}-{expiry_date.month:02d}"
        deltas[month_key] = float(np.mean(post_vals) - np.mean(pre_vals))
    return deltas


def _run_group(
    label: str,
    symbols: list[str],
    conn,
    cal,
    expiries: list[datetime],
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
        if not bars:
            continue
        start = bars[0]["ts"]
        end = bars[-1]["ts"]
        windows = _session_windows(cal, start, end)
        proxy_by_date = _proxy_by_date(bars, windows)
        all_dates = [d for d, _o, _c in windows]
        deltas = _deltas_for_symbol(proxy_by_date, expiries, all_dates)
        for month_key, delta in deltas.items():
            pnl_r_values.append(delta)
            cluster_ids.append(month_key)

    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_r_values, cluster_ids, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
    )
    n_clusters = len(set(cluster_ids))
    verdict = "PASS" if passes else "no effect / fails"
    print(
        f"{label}: n_obs={len(pnl_r_values)} n_expiry_months={n_clusters} "
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

    print("dealer_hedging_flow expiry calendar pilot -- tf=5m")
    print(
        f"min_n={min_n} bootstrap_max_n={bootstrap_max_n} "
        f"bootstrap_batch={bootstrap_batch} bootstrap_random_state={bootstrap_random_state}"
    )
    print(f"heavy group ({len(_HEAVY_GROUP)}): {', '.join(_HEAVY_GROUP)}")
    print(f"control group ({len(_CONTROL_GROUP)}): {', '.join(_CONTROL_GROUP)}")

    cal = mcal.get_calendar("NYSE")
    now = datetime.now(UTC)
    expiries = _third_fridays(datetime(2005, 1, 1, tzinfo=UTC), now)
    print(f"\n{len(expiries)} monthly expiry Fridays in range")

    print(
        "\n--- Falsification bar: delta = mean(proxy, POST) - mean(proxy, PRE), "
        "day-clustered [by expiry-month] bootstrap per group ---\n"
    )

    heavy_passes, _heavy_lo, _heavy_hi, _heavy_n = _run_group(
        "HEAVY",
        _HEAVY_GROUP,
        conn,
        cal,
        expiries,
        min_n=min_n,
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
    )
    control_passes, _control_lo, _control_hi, _control_n = _run_group(
        "CONTROL",
        _CONTROL_GROUP,
        conn,
        cal,
        expiries,
        min_n=min_n,
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
    )

    print(
        "\nVerdict rule (pre-registered, binary): heavy-optioned group must PASS "
        "(ci_lower > 0) AND control group must NOT pass."
    )
    if heavy_passes and not control_passes:
        print(
            "RESULT: MECHANISM SURVIVES -- dealer gamma-exposure calendar effect is a live candidate."
        )
    else:
        print(
            "RESULT: DEAD -- dealer hedging flow calendar screen falsified by its own pre-registered bar."
        )

    conn.close()


if __name__ == "__main__":
    main()
