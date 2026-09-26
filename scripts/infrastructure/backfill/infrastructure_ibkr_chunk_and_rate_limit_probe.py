"""IBKR historical-data chunk-size and rate-limit ceiling probe.

Two long-standing constants in `src/providers/ibkr.py` govern backfill throughput:
`_MAX_CHUNK_DAYS` (per-request duration ceiling per timeframe) and
`_IBKR_HIST_RATE_LIMIT` (requests per 10-minute sliding window, currently 55, APR-tagged
`[conventional]` in migration 276 -- i.e. inherited developer convention, never independently
measured against this account). This script measures both directly, once, against real
zero-row symbols already queued for backfill (todo 259) -- a successful test IS real backfill
progress, a failed one writes nothing (fetch_historical_bars only returns bars on success;
store_bars is a no-op on an empty list).

Phase 2 measures one timeframe's rate ceiling (--rate-timeframe, --rate-ceilings). IBKR's
documented hard pacing rules (60 requests per 10 minutes) bind bars of 30 seconds or less; for bars
of a minute or more the hard limit was lifted and only a soft, load-balancing slowdown applies
(checked 2026-09-26). So 1d can be tested above 60, ascending, stopping at the first ceiling that
draws any throttling, and reading latency for the soft slowdown. The 2026-08-06 run tested only up
to 62 because the 60 rule was then assumed to bind every bar size.

This script does NOT modify production APR config (`config_state`) -- it patches the
in-process module constants for the duration of this one run only, and prints a
recommendation at the end. Applying any discovered headroom to production is a separate,
deliberate step.

Usage: .venv/bin/python scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py
       [--only 15m,4h] [--skip-chunks] [--skip-rate-limit]
       [--rate-timeframe 1d] [--rate-ceilings 90,120,180] [--cooldown-s 620]

--only restricts Phase 1 to the given comma-separated timeframes (still one bounded tier
each, edit _CHUNK_TEST_TIERS to change the tier itself) -- for targeted follow-up escalation
without re-running already-confirmed timeframes. --skip-rate-limit omits Phase 2 entirely.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (  # noqa: E402
    _load_ibkr_rate_limit_config,
    connect_db,
    store_bars,
)
from src.config.settings import Settings, get_active_contracts  # noqa: E402
from src.providers import IBKRProvider, ibkr  # noqa: E402

_PROBE_CLIENT_ID = 44  # dedicated, distinct from 41 (in-flight)/43 (reserved for real batch)

# Chunk-size test tiers, one per timeframe actually used by the backfill pipeline
# (_TF_MINUTES in the main script). Run 1 (2026-08-06) tested only 1d/1h and found real
# headroom (364d default -> 1825d/1095d both succeeded cleanly) -- that run also caught and
# fixed a real bug (fetch_historical_bars's chunked-request branch never converted "N D" to
# "N Y" past 365 days, unlike the continuous-contract branch; see git history same date).
# User-requested full sweep (2026-08-06): checked each timeframe's actual APR provenance
# tag in migration 192 before picking a tier, not just repeating the same guess --
#   1m:  [rca_analysis] "IBKR per-request limit ~7 days" -- a real tested boundary already.
#        Testing anyway per "test them all"; expect this to fail and confirm the existing
#        6d default is correctly tight, not to find new headroom.
#   5m:  [rca_analysis] "Verified 90D succeeds, 180D times out" -- real bracketed boundary,
#        89D already deliberately close to the known failure point. Testing 150D to narrow
#        the known 90-180 gap, not searching blind.
#   15m: [initial_estimate] "has not had a re-verification probe... possibly under-tuned" --
#        migration 192's own text flags this as the real unknown. Testing boldly (180D,
#        matching the doc's own suggested case: "15m bars are less dense than 5m").
#   4h:  [initial_estimate] "Not re-verified alongside 5m/1h" -- same untested bucket as 15m.
#   1h:  [rca_analysis] but only verified AT the current default (364D), never past it.
#        Run 1 already confirmed 1095D works cleanly -- pushing further this time to a full
#        20yr (7300D) single-shot: if IBKR accepts it, 1h drops to 1 request/symbol instead
#        of ~7.
#   1d:  [rca_analysis] same situation as 1h. Run 1 confirmed 1825D -- testing the full
#        20yr (7300D) single-shot here too, same reasoning.
# Run 1 (2026-08-06): 1d/1h only, found headroom at 1825d/1095d, caught+fixed the
# days-vs-years duration_str bug. Run 2: all 6 timeframes, one bounded tier each -- 1m/5m/
# 15m/4h/1d all confirmed clean, 1h's full-20yr (7300d) tier genuinely failed (0 bars,
# 375s) -- 1h's real production value should stay at run 1's confirmed-good 1095d, not this
# tier. Run 3 (this escalation, user-requested): 15m and 4h's run-2 results looked
# under-tested relative to the others -- 4h succeeded in just 0.5s for 432 bars, far lighter
# than every other successful test, suggesting real headroom was left on the table by
# matching its tier to 15m's rather than scaling to 4h's much lower bar density. Escalating
# both past the 365-day threshold this time (exercises the same "N Y" duration-string path
# that already proved out for 1d's full-range success).
# 1h deliberately has NO entry here: run 2 tested a full 20yr single-shot (7300d) and it
# genuinely FAILED (0 bars, 375s of retries, "API historical data query cancelled"). Keeping
# a known-failing tier as a live dict entry would silently re-run and re-fail it on every
# future default invocation of this script for no new information -- 1h's confirmed-good
# production value is 1095d (3yr, from run 1), applied directly in migration 302, not
# re-tested here. Use --only to add a fresh 1h escalation (e.g. something between the
# confirmed-good 1095d and confirmed-bad 7300d) if that gap is ever worth narrowing.
_CHUNK_TEST_TIERS = {
    "1m": 14,  # vs 6d default -- expect failure, confirms the existing boundary is real
    "5m": 150,  # vs 89d default -- narrows the known 90D-good/180D-bad window
    "15m": 400,  # vs 59d default (180d confirmed run 2) -- crosses the 365d threshold
    "4h": 1095,  # vs 29d default (180d confirmed run 2) -- matches 1h's confirmed-good 3yr
    #  tier; 4h is less dense than 1h so should tolerate at least as much
    "1d": 7300,  # vs 364d default -- full 20yr single-shot attempt (run 2: confirmed clean)
}


def _bars_to_dicts(bars: list) -> list[dict]:
    """OHLCVBar -> the dict shape store_bars expects. Shared by both phases below."""
    return [
        {
            "timestamp": b.timestamp,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "source": b.source,
        }
        for b in bars
    ]


async def _pick_probe_symbols(settings: Settings, n: int, timeframe: str | None = None) -> list:
    """Return n Instrument objects for symbols currently missing OHLCV data, preferring
    large/liquid names for a clean signal.

    timeframe, if given, checks for missing rows in THAT timeframe specifically rather than
    "any timeframe at all" -- required once earlier probe runs (or the real backfill) have
    given most symbols SOME data: a symbol with only 1d rows still has zero 15m rows, and an
    "any data at all" check would silently exclude it, returning an empty candidate pool
    with no error (found 2026-08-06, run 4 -- Phase 1 printed a phase header then went
    straight to an empty summary, no test lines, no traceback)."""
    conn = connect_db(settings)
    try:
        with conn.cursor() as cur:
            if timeframe:
                cur.execute(
                    "SELECT i.symbol FROM instruments i WHERE i.is_active = true "
                    "AND NOT EXISTS (SELECT 1 FROM market_data_ohlcv m "
                    "WHERE m.symbol = i.symbol AND m.timeframe = %s) "
                    "ORDER BY i.symbol",
                    (timeframe,),
                )
            else:
                cur.execute(
                    "SELECT i.symbol FROM instruments i WHERE i.is_active = true "
                    "AND NOT EXISTS (SELECT 1 FROM market_data_ohlcv m WHERE m.symbol = i.symbol) "
                    "ORDER BY i.symbol"
                )
            zero_row = {r[0] for r in cur.fetchall()}
    finally:
        conn.close()

    if not zero_row:
        raise RuntimeError(
            f"No candidate symbols found (timeframe={timeframe!r}) -- every active "
            "instrument already has data here. Check market_data_ohlcv before re-running."
        )

    preferred = ["MSFT", "GOOGL", "AMD", "GS", "UNH", "AVGO", "NVDA", "META", "COST", "BAC"]
    ordered = [s for s in preferred if s in zero_row]
    ordered += sorted(zero_row - set(ordered))

    contracts = {c.symbol: c for c in get_active_contracts(settings, dimension="compute")}
    picked = [contracts[s] for s in ordered[:n] if s in contracts]
    if len(picked) < n:
        raise RuntimeError(
            f"Only found {len(picked)}/{n} candidate symbols (timeframe={timeframe!r}) -- "
            "check the zero-row pool isn't exhausted."
        )
    return picked


async def _phase1_chunk_size_test(
    provider: IBKRProvider, settings: Settings, conn, tiers: dict[str, int]
) -> dict:
    """For each tf in tiers, widen _MAX_CHUNK_DAYS and run one real fetch on a dedicated
    symbol, requesting EXACTLY wide_days of range so the chunking loop makes exactly one
    chunk attempt (a failing/retrying tier costs at most _RETRY_COUNT retries on ONE chunk,
    not repeated retries across many chunks in a larger range). Returns
    {tf: {"symbol", "success", "elapsed_s", "bars", "error"}}."""
    print("\n=== PHASE 1: chunk-size headroom test ===")
    results: dict = {}
    now = datetime.now(UTC)

    # One symbol per timeframe, picked against THAT timeframe's own zero-row set -- not a
    # single batch pick checked against "any data at all" (see _pick_probe_symbols docstring
    # for why that silently broke once earlier runs left most symbols with SOME data).
    for tf, wide_days in tiers.items():
        instrument = (await _pick_probe_symbols(settings, 1, timeframe=tf))[0]
        original = ibkr._MAX_CHUNK_DAYS.get(tf)
        print(f"\n--- {tf}: {instrument.symbol}, chunk_days {original} -> {wide_days} ---")
        ibkr._MAX_CHUNK_DAYS[tf] = wide_days
        start_time = time.monotonic()
        error_text = None
        bars = []
        try:
            qualified = await provider.qualify_instrument(instrument)
            if not qualified:
                error_text = "qualify_instrument failed"
            else:
                bars = await provider.fetch_historical_bars(
                    symbol=instrument.symbol,
                    timeframe=tf,
                    start=now - timedelta(days=wide_days),
                    end=now,
                )
        except Exception as exc:  # noqa: BLE001 -- probe script, report and continue
            error_text = f"{type(exc).__name__}: {exc}"
        finally:
            ibkr._MAX_CHUNK_DAYS[tf] = original  # restore immediately regardless of outcome

        elapsed = time.monotonic() - start_time
        n_stored = 0
        if bars:
            n_stored = store_bars(conn, _bars_to_dicts(bars), instrument.symbol, tf)

        results[tf] = {
            "symbol": instrument.symbol,
            "success": bool(bars) and error_text is None,
            "elapsed_s": round(elapsed, 1),
            "bars": n_stored,
            "error": error_text,
        }
        verdict = "OK" if results[tf]["success"] else "FAILED"
        print(
            f"    {verdict} -- {n_stored} bars stored, {elapsed:.1f}s"
            + (f", error={error_text}" if error_text else "")
        )

    return results


async def _phase2_rate_limit_test(
    provider: IBKRProvider,
    settings: Settings,
    *,
    timeframe: str,
    ceilings: list[int],
    cooldown_s: float,
) -> list[dict]:
    """Measure IBKR's pushback at each requests-per-window ceiling for one timeframe.

    For each ceiling (ascending) the timeframe gets its own limit of that ceiling
    (ibkr._IBKR_HIST_RATE_LIMIT_BY_TF), then `ceiling` one-year requests fire across distinct
    active symbols as fast as that limit allows. Pushback is read two ways: Error 162 throttling
    counted by ibkr._hist_throttle_count (fetch_historical_bars retries a throttled chunk and
    returns [] rather than raising, so exceptions alone cannot see it), and request latency,
    which is how IBKR's soft load-balancing slowdown for bars of a minute or more shows up.
    Stops at the first ceiling with any throttling. Waits cooldown_s between ceilings so each
    starts with an empty IBKR window. Nothing is stored and no APR value changes.
    """
    print(f"\n=== PHASE 2: rate-limit ceilings for {timeframe}: {ceilings} ===")
    contracts = [
        c
        for c in get_active_contracts(settings, dimension="backfill")
        if c.asset_class.value == "equity"
    ]
    qualified = []
    for instrument in contracts:
        if len(qualified) >= max(ceilings):
            break
        if await provider.qualify_instrument(instrument):
            qualified.append(instrument)
    if len(qualified) < max(ceilings):
        print(f"  only {len(qualified)} symbols qualified; requests will repeat symbols")

    saved_overrides = dict(ibkr._IBKR_HIST_RATE_LIMIT_BY_TF)
    results: list[dict] = []
    try:
        for i, ceiling in enumerate(sorted(ceilings)):
            if i:
                print(f"  cooldown {cooldown_s:.0f}s so the next ceiling starts on an empty window")
                await asyncio.sleep(cooldown_s)
            ibkr._IBKR_HIST_RATE_LIMIT_BY_TF[timeframe] = ceiling
            ibkr._tf_rate_limiters.pop(timeframe, None)
            throttles_before = ibkr._hist_throttle_count
            latencies: list[float] = []
            n_empty = 0
            now = datetime.now(UTC)
            started = time.monotonic()
            for k in range(ceiling):
                instrument = qualified[k % len(qualified)]
                t0 = time.monotonic()
                bars = await provider.fetch_historical_bars(
                    symbol=instrument.symbol,
                    timeframe=timeframe,
                    start=now - timedelta(days=364),
                    end=now,
                )
                latencies.append(time.monotonic() - t0)
                n_empty += not bars
            latencies.sort()
            result = {
                "ceiling": ceiling,
                "requests": ceiling,
                "elapsed_s": round(time.monotonic() - started, 1),
                "throttled": ibkr._hist_throttle_count - throttles_before,
                "empty": n_empty,
                "latency_median_s": round(latencies[len(latencies) // 2], 2),
                "latency_p90_s": round(latencies[int(len(latencies) * 0.9)], 2),
            }
            results.append(result)
            print(f"  {result}")
            if result["throttled"]:
                print("  throttling observed; higher ceilings not tested")
                break
    finally:
        ibkr._IBKR_HIST_RATE_LIMIT_BY_TF.clear()
        ibkr._IBKR_HIST_RATE_LIMIT_BY_TF.update(saved_overrides)
        ibkr._tf_rate_limiters.pop(timeframe, None)
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description="IBKR chunk-size/rate-limit probe")
    parser.add_argument(
        "--only", default="", help="Comma-separated timeframes to test in Phase 1 (default: all)"
    )
    parser.add_argument(
        "--skip-rate-limit", action="store_true", help="Skip Phase 2 (rate-limit ceiling test)"
    )
    parser.add_argument("--skip-chunks", action="store_true", help="Skip Phase 1 (chunk-size test)")
    parser.add_argument(
        "--rate-timeframe", default="1d", help="Timeframe whose rate limit Phase 2 measures"
    )
    parser.add_argument(
        "--rate-ceilings",
        default="60",
        help="Comma-separated requests-per-window ceilings for Phase 2, tested ascending",
    )
    parser.add_argument(
        "--cooldown-s",
        type=float,
        default=620.0,
        help="Seconds between Phase 2 ceilings (IBKR's window is 600s)",
    )
    args = parser.parse_args()

    tiers = dict(_CHUNK_TEST_TIERS)
    if args.only:
        wanted = {tf.strip() for tf in args.only.split(",") if tf.strip()}
        tiers = {tf: d for tf, d in tiers.items() if tf in wanted}

    settings = Settings()
    conn = connect_db(settings)
    provider = IBKRProvider(
        host=settings.ib_host, port=settings.ib_port, client_id=_PROBE_CLIENT_ID
    )

    _load_ibkr_rate_limit_config(settings)
    connected = await provider.connect()
    if not connected:
        print("FAILED to connect to IBKR Gateway -- aborting probe.")
        return

    try:
        chunk_results = (
            {}
            if args.skip_chunks
            else await _phase1_chunk_size_test(provider, settings, conn, tiers)
        )
        rate_results = None
        if not args.skip_rate_limit:
            rate_results = await _phase2_rate_limit_test(
                provider,
                settings,
                timeframe=args.rate_timeframe,
                ceilings=[int(c) for c in args.rate_ceilings.split(",") if c.strip()],
                cooldown_s=args.cooldown_s,
            )
    finally:
        await provider.disconnect()
        conn.close()

    print("\n" + "=" * 70)
    print("PROBE SUMMARY")
    print("=" * 70)
    original_defaults = {"1m": 6, "5m": 89, "15m": 59, "4h": 29, "1h": 364, "1d": 364}
    for tf, r in chunk_results.items():
        tier = tiers[tf]
        default = original_defaults.get(tf)
        verdict = "headroom confirmed" if r["success"] else "no headroom (or transient failure)"
        print(
            f"  {tf}: {default}d -> {tier}d tested -- {verdict} ({r['symbol']}, {r['bars']} bars)"
        )
        if not r["success"] and r["error"]:
            print(f"       error: {r['error']}")

    if rate_results is None:
        print("\n  Rate limit test skipped (--skip-rate-limit).")
        return

    clean = [r for r in rate_results if not r["throttled"]]
    print(f"\n  Rate limit ({args.rate_timeframe}):")
    for r in rate_results:
        print(f"    {r}")
    if clean:
        best = max(r["ceiling"] for r in clean)
        print(
            f"  Highest clean ceiling: {best} per window. Before setting "
            f"infra.ibkr.rate_limit_max_requests_by_tf, check latency did not climb with the "
            f"ceiling (IBKR's soft slowdown) and keep a margin below {best}."
        )
    else:
        print("  Throttled at the lowest ceiling tested: keep the shared limit.")

    print(
        "\nNo production config was changed by this script. Review before applying any "
        "chunk-size or rate-limit changes to infra.ibkr.* APR keys."
    )


if __name__ == "__main__":
    asyncio.run(main())
