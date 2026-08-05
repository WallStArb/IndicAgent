"""Todo 243/253 follow-up: does Phase 167's live Validation Gate 1 (cross_sectional_relative_value,
`ctf_momentum_decile_ls` construction, 15m) survive the corrected CTF batch-join?

`services/cross_sectional_spread_tracker.py` ranks the entire construction on one feature,
`ctf_momentum`, read from `feature_vectors.ctf_momentum` (`_PANEL_SQL_BACKFILL`). Todo 243
confirmed that column is populated via a lookahead-leaking HTF join for every 5m/15m/1h row
(`_build_ctf_series` + `bisect_right`, selecting the still-forming HTF bar, not the last
completed one). The already-recorded Gate 1 verdict (`logs/construction_verdicts/
gate1_latest.json`, 2026-07-27, gate1_passes=true) was measured entirely against that leaked
column -- unmeasured until now is whether it survives the fix
(`_rekey_ctf_series_to_actual_close()`, applied to `backfill_feature_factory.py` 2026-08-03).

DIAGNOSTIC TIER ONLY (todo 253) -- NOT a substitute for an authoritative re-verification.
`forward_returns` (the table Gate 1's production code reads) has zero rows in the OOS holdout
window (`bar_ts >= alpha.validation.oos_start`) at any tf -- confirmed structural, not a bug:
Phase 141.1's OOS holdout enforcement makes it impossible for the normal pipeline to ever write
there (`docs/plans/OOS-EVAL-PROTOCOL.md`). This script instead computes `return_fast`/
`return_slow` ON THE FLY from raw `market_data_ohlcv_tradeable` opens via
`forward_log_return()` (imported unmodified from `forward_return_writer.py`) -- the exact
pattern `scripts/ops/corpus/ops_oos_holdout_eval.py` already uses for the protocol's own
sanctioned "interim diagnostic scorer", instead of inventing a new one. This is DELIBERATELY not
byte-identical to what the authoritative pipeline would produce: `forward_return_writer.py` also
applies suspect-value flagging and cross-symbol corroboration
(`_apply_cross_symbol_corroboration`) before persisting, which this on-the-fly recomputation does
not replicate. Good enough for a first-look diagnostic; not a promotion-grade re-verification.

This script does NOT touch `feature_vectors`, `forward_returns`, or `construction_spreads` --
strictly read-only. It rebuilds the construction's own panel and re-runs its own Gate 1 pure
functions (imported unmodified from `cross_sectional_spread_tracker.py` -- no gate math is
reimplemented here) entirely in memory, substituting a corrected `ctf_momentum` series computed
the same way the SPY single-symbol pilots did (`_build_ctf_series` +
`_rekey_ctf_series_to_actual_close`, both already-fixed, already-tested production functions
from `backfill_feature_factory.py`), generalized here from one symbol to the full equity
universe this construction actually ranks over.

CADENCE NOTE (do not run this without reading `docs/plans/OOS-EVAL-PROTOCOL.md` first):
the protocol's diagnostic-tier scorer "may be run more freely" than the authoritative one, but
its OWN cadence rule still applies: its output must never be used to tune any in-sample
parameter. This script's purpose is a one-time read of whether a already-applied,
already-committed bug fix (todo 243) changes the verdict -- not a repeatable check-and-tune loop.

Turnover continuity: processes the FULL panel history (not just the OOS window) in
`bar_ts` order, exactly like `execute()`'s `--backfill` mode, then restricts to
`bar_ts >= alpha.validation.oos_start` only when building Gate 1's input rows -- matching
`_run_evaluate_gate`'s `_GATE_ROWS_SQL` filter and preserving turnover continuity into the
first OOS bar (backfill mode has no predecessor only at the true start of history, not at the
OOS boundary).

Usage: .venv/bin/python scripts/analysis/phase167_gate1_ctf_join_fix_reverify_15m.py
"""

from __future__ import annotations

import bisect
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402

from services.backfill_feature_factory import (  # noqa: E402
    _build_ctf_series,
    _fetch_bars_from_db,
    _rekey_ctf_series_to_actual_close,
)
from services.cross_sectional_spread_tracker import (  # noqa: E402
    _build_panel_by_bar,
    _flatten_gate_rows,
    decile_legs,
    evaluate_spread_gate,
    mean_gross_spread_over_bars,
    net_spread_by_cost_bps,
    one_way_turnover,
    shuffled_ranking_null_p,
    spread_from_legs,
    validate_construction_config,
)
from services.forward_return_writer import forward_log_return  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_TF = "15m"
_HTF_TF = "1h"
_CONSTRUCTION_NAME = "ctf_momentum_decile_ls"

# Live config_state values, confirmed 2026-08-04 (same query pattern the SPY pilot scripts use).
_RSI_MID_PERIOD = 14  # feature.period.rsi.mid
_DECILE_FRACTION = 0.10  # alpha.construction.decile_fraction
_NULL_SHUFFLES = 40  # alpha.construction.null_shuffles
_NULL_P_THRESHOLD = 0.05  # alpha.construction.null_p_threshold
_COST_BPS = [1, 3, 5, 10]  # alpha.construction.cost_hurdle_bps_round_trip
_MIN_N = 30  # alpha.scoring.min_strategy_n
_BOOTSTRAP_MAX_N = 5000  # alpha.scoring.bootstrap_max_n
_BOOTSTRAP_BATCH = 1000  # alpha.scoring.bootstrap_batch
_BOOTSTRAP_RANDOM_STATE = 42  # alpha.scoring.bootstrap_random_state
_OOS_START = datetime.fromisoformat("2025-12-24T05:15:00+00:00")  # alpha.validation.oos_start
_LOOKAHEAD_FAST = 1  # alpha.ic.lookahead.15m.fast
_LOOKAHEAD_SLOW = 5  # alpha.ic.lookahead.15m.slow

# Equity universe: same asset_class/active filter cross_sectional_spread_tracker uses.
_SYMBOLS_SQL = """
    SELECT DISTINCT symbol FROM instruments
    WHERE is_active = true AND contract_details->>'asset_class' = 'equity'
    ORDER BY symbol
"""


@dataclass(frozen=True)
class _MinimalConfig:
    rsi_mid_period: int


def _join_ctf_momentum(ctf_by_ts: dict, ltf_bar_ts: list) -> dict:
    """Verbatim mechanic of FeatureFactory.compute_batch's bisect join
    (feature_factory.py:6923-6935) -- ctf_momentum only (index 0). Does NOT fall back to
    0.0 for idx < 0 -- correct for a live compute_batch call (every LTF row must get SOME
    value), but a diagnostic re-verification should exclude un-joinable rows rather than
    inject a fabricated zero into the ranking. Returns {bar_ts: ctf_momentum} for only the
    bar_ts values that joined successfully.
    """
    ctf_ts_list = sorted(ctf_by_ts.keys())
    out = {}
    for bar_ts in ltf_bar_ts:
        idx = bisect.bisect_right(ctf_ts_list, bar_ts) - 1
        if idx >= 0:
            out[bar_ts] = ctf_by_ts[ctf_ts_list[idx]][0]
    return out


def _returns_by_bar_ts(ltf_bars: list[dict]) -> dict:
    """Compute return_fast/return_slow ON THE FLY via forward_log_return(), matching
    ops_oos_holdout_eval.py's pattern -- no forward_returns table dependency (todo 253).
    DIAGNOSTIC TIER: does not replicate forward_return_writer.py's suspect-value/
    cross-symbol-corroboration corrections."""
    bar_ts_list = [b["ts"] for b in ltf_bars]
    opens = np.array([b["open"] for b in ltf_bars], dtype=float)
    fast = forward_log_return(opens, _LOOKAHEAD_FAST)
    slow = forward_log_return(opens, _LOOKAHEAD_SLOW)
    return {
        bar_ts: (float(f) if not np.isnan(f) else None, float(s) if not np.isnan(s) else None)
        for bar_ts, f, s in zip(bar_ts_list, fast, slow, strict=True)
    }


def _run_gate1(panel_rows: list[dict], label: str) -> dict:
    """Full Gate 1 pipeline over an in-memory panel, mirroring
    `CrossSectionalSpreadTracker._execute_inner`'s `process_bar` (backfill mode) +
    `_run_evaluate_gate` exactly, using ONLY imported production pure functions."""
    validate_construction_config(_DECILE_FRACTION, _COST_BPS, _NULL_SHUFFLES, 0.50)

    grouped: dict = {}
    for row in panel_rows:
        grouped.setdefault(row["bar_ts"], []).append(row)
    ordered_bar_ts = sorted(grouped.keys())

    prior_long: frozenset = frozenset()
    prior_short: frozenset = frozenset()
    construction_rows = []
    n_skipped_degenerate = 0
    for bar_ts in ordered_bar_ts:
        rows = grouped[bar_ts]
        symbols = [r["symbol"] for r in rows]
        feature_values = [r["ctf_momentum"] for r in rows]
        legs = decile_legs(symbols, feature_values, _DECILE_FRACTION)
        if legs is None:
            n_skipped_degenerate += 1
            continue
        short_leg, long_leg = legs
        cur_long, cur_short = frozenset(long_leg), frozenset(short_leg)
        returns_fast = {r["symbol"]: r["return_fast"] for r in rows}
        returns_slow = {r["symbol"]: r["return_slow"] for r in rows}
        gross_fast = spread_from_legs(returns_fast, long_leg, short_leg)
        gross_slow = spread_from_legs(returns_slow, long_leg, short_leg)
        turnover = one_way_turnover(prior_long, prior_short, cur_long, cur_short)
        net_fast = net_spread_by_cost_bps(gross_fast, turnover, _COST_BPS)
        net_slow = net_spread_by_cost_bps(gross_slow, turnover, _COST_BPS)
        construction_rows.append(
            {
                "bar_ts": bar_ts,
                "cluster_id": bar_ts.date(),
                "gross_spread_fast": gross_fast,
                "gross_spread_slow": gross_slow,
                "one_way_turnover": turnover,
                "net_spread_fast_by_cost_bps": net_fast,
                "net_spread_slow_by_cost_bps": net_slow,
            }
        )
        prior_long, prior_short = cur_long, cur_short

    oos_rows = [
        r
        for r in construction_rows
        if r["bar_ts"] >= _OOS_START and r["one_way_turnover"] is not None
    ]
    oos_flattened = _flatten_gate_rows(oos_rows, _COST_BPS)
    oos_verdicts = evaluate_spread_gate(
        oos_flattened, _MIN_N, _BOOTSTRAP_MAX_N, _BOOTSTRAP_BATCH, _BOOTSTRAP_RANDOM_STATE
    )

    oos_panel_rows = [r for r in panel_rows if r["bar_ts"] >= _OOS_START]
    null_by_scale = {}
    for scale, return_col in (("fast", "return_fast"), ("slow", "return_slow")):
        panel_by_bar = _build_panel_by_bar(oos_panel_rows, return_col)
        observed_mean, observed_n = mean_gross_spread_over_bars(panel_by_bar, _DECILE_FRACTION)
        if observed_mean is None:
            raise RuntimeError(f"[{label}] no eligible OOS bars for scale={scale!r}")
        null_p, null_mean, null_std, null_n = shuffled_ranking_null_p(
            panel_by_bar, _DECILE_FRACTION, observed_mean, _NULL_SHUFFLES, _BOOTSTRAP_RANDOM_STATE
        )
        assert null_n == observed_n, f"[{label}] null/observed eligible-bar mismatch"
        null_by_scale[scale] = {"null_p": null_p, "observed_mean": observed_mean, "n": null_n}

    binding_cost_bps = max(_COST_BPS)
    binding_by_scale = {v["scale"]: v for v in oos_verdicts if v["cost_bps"] == binding_cost_bps}
    fast_binding = binding_by_scale.get("fast")
    slow_binding = binding_by_scale.get("slow")
    fast_passes = bool(fast_binding is not None and fast_binding["passes"] is True)
    slow_passes = bool(slow_binding is not None and slow_binding["passes"] is True)
    fast_null_clears = null_by_scale["fast"]["null_p"] < _NULL_P_THRESHOLD
    slow_null_clears = null_by_scale["slow"]["null_p"] < _NULL_P_THRESHOLD
    gate1_passes = fast_passes and slow_passes and fast_null_clears and slow_null_clears

    return {
        "label": label,
        "gate1_passes": gate1_passes,
        "n_construction_rows": len(construction_rows),
        "n_skipped_degenerate": n_skipped_degenerate,
        "n_oos_rows": len(oos_rows),
        "n_oos_day_clusters": len({r["cluster_id"] for r in oos_flattened}),
        "binding_cost_bps": binding_cost_bps,
        "fast_binding": fast_binding,
        "slow_binding": slow_binding,
        "fast_null_p": null_by_scale["fast"]["null_p"],
        "slow_null_p": null_by_scale["slow"]["null_p"],
    }


def main() -> None:
    print("=" * 80)
    print("DIAGNOSTIC TIER ONLY -- see module docstring. Not a promotion-grade re-verification.")
    print("Computes OOS returns on the fly (forward_log_return against raw bars) -- does NOT")
    print("replicate forward_return_writer.py's suspect-value/corroboration corrections.")
    print("=" * 80 + "\n")

    settings = Settings()
    conn = psycopg.connect(settings.database_url)
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute(_SYMBOLS_SQL)
        symbols = [r[0] for r in cur.fetchall()]
    print(f"Equity universe: {len(symbols)} symbols")

    config = _MinimalConfig(rsi_mid_period=_RSI_MID_PERIOD)

    leaked_rows: list[dict] = []
    corrected_rows: list[dict] = []
    for i, symbol in enumerate(symbols, 1):
        htf_bars = _fetch_bars_from_db(conn, symbol, _HTF_TF)
        ltf_bars = _fetch_bars_from_db(conn, symbol, _TF)
        if len(htf_bars) < 2 or len(ltf_bars) < 2:
            continue

        old_ctf_by_ts = _build_ctf_series(htf_bars, config)
        new_ctf_by_ts = _rekey_ctf_series_to_actual_close(old_ctf_by_ts, _TF, _HTF_TF)
        ltf_bar_ts = [b["ts"] for b in ltf_bars]
        leaked_ctf = _join_ctf_momentum(old_ctf_by_ts, ltf_bar_ts)
        corrected_ctf = _join_ctf_momentum(new_ctf_by_ts, ltf_bar_ts)
        returns_by_ts = _returns_by_bar_ts(ltf_bars)

        for bar_ts in ltf_bar_ts:
            fast_ret, slow_ret = returns_by_ts.get(bar_ts, (None, None))
            if fast_ret is None or slow_ret is None:
                continue
            if bar_ts in leaked_ctf:
                leaked_rows.append(
                    {
                        "symbol": symbol,
                        "bar_ts": bar_ts,
                        "ctf_momentum": leaked_ctf[bar_ts],
                        "return_fast": fast_ret,
                        "return_slow": slow_ret,
                    }
                )
            if bar_ts in corrected_ctf:
                corrected_rows.append(
                    {
                        "symbol": symbol,
                        "bar_ts": bar_ts,
                        "ctf_momentum": corrected_ctf[bar_ts],
                        "return_fast": fast_ret,
                        "return_slow": slow_ret,
                    }
                )

        if i % 20 == 0 or i == len(symbols):
            print(f"  built panel for {i}/{len(symbols)} symbols")

    conn.close()
    print(
        f"\nLeaked panel: {len(leaked_rows)} rows. Corrected panel: {len(corrected_rows)} rows.\n"
    )

    print("=" * 80)
    print("LEAKED join (original ctf_momentum, on-the-fly returns)")
    print("=" * 80)
    leaked_result = _run_gate1(leaked_rows, "leaked, on-the-fly returns")
    print(json.dumps(leaked_result, default=str, indent=2))

    print("\n" + "=" * 80)
    print("CORRECTED join (fixed ctf_momentum, on-the-fly returns)")
    print("=" * 80)
    corrected_result = _run_gate1(corrected_rows, "corrected join, on-the-fly returns")
    print(json.dumps(corrected_result, default=str, indent=2))

    out_dir = Path("logs/construction_verdicts")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (
        f"gate1_ctf_join_reverify_15m_DIAGNOSTIC_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.write_text(
        json.dumps(
            {
                "tier": "diagnostic-only, on-the-fly returns, see module docstring",
                "leaked": leaked_result,
                "corrected": corrected_result,
            },
            default=str,
            indent=2,
        )
    )
    print(f"\nWrote {out_path}")

    print("\n" + "=" * 80)
    print(
        f"DIAGNOSTIC VERDICT: leaked-join gate1_passes={leaked_result['gate1_passes']} -> "
        f"corrected-join gate1_passes={corrected_result['gate1_passes']}"
    )
    print("NOT authoritative -- see module docstring's DIAGNOSTIC TIER ONLY note.")
    print("=" * 80)


if __name__ == "__main__":
    main()
