"""Phase 166 D-01a: read-only diagnosis of why the current global stop_atr_mult/
target_r_multiple scalars fail, compared against empirical uncensored MAE/MFE excursion
percentiles per (regime, tf).

D-02's confirmed baseline (verified in code during Phase 166's discussion, not an assumption):
`alpha.frame.hold_max_bars.<regime>.<tf>` IS already empirically calibrated (EIC-02,
`services/ensemble_ic_engine.py::_calibrate_hold_max_bars`, median hold-bars across qualifying
symbols per (regime, tf), CR-02 champion-`weight_version`-gated). `alpha.frame.stop_atr_mult`
(1.5) and `alpha.frame.target_r_multiple` (2.0) are NOT -- single global `[initial_estimate]`
scalars from migration 205/214, never conditioned on regime/tf, never revisited since Phase
142B. This is the real gap this diagnosis measures.

stop_atr_mult/target_r_multiple have no literal IC-decay-curve analog (they are distance/
reward-ratio parameters, not a time-horizon concept like hold_max_bars' scale-walk) --
RESEARCH.md Finding 1/Pitfall 1. The empirically sound substitute used here: `alpha_frames`'
already-collected `counterfactual_mfe`/`counterfactual_mae` (R-units, i.e. multiples of each
frame's own snapshotted stop distance) are rescaled to ATR-units via each row's own
`stop_atr_mult` snapshot (`mae_atr = counterfactual_mae * stop_atr_mult`, since
risk = stop_atr_mult * atr and mae_r = mae_price / risk => mae_atr = mae_price / atr =
mae_r * stop_atr_mult) and compared, per (regime, tf), against the current global scalars.

Four folded caveats disclosed here (all four MUST be read before trusting this diagnosis's
numbers as a calibration input):

  (088) hold_max_bars censoring -- and the analogous risk for stop/target: `counterfactual_mae`
  on `closed_stop` frames is RIGHT-CENSORED at the stop distance (the frame's own stop_price
  bounded how far price could excurse before the frame closed) -- the same confirmed-vs-
  censored ambiguity todo 088 flags for hold_max_bars' median aggregation. This diagnosis
  sidesteps it by measuring MAE only among `closed_target` frames (uncensored: these frames
  never touched the stop, so their observed adverse excursion is a real, unbounded-by-the-stop
  measurement) for stop placement, and MFE only among `closed_max_hold` frames (uncensored:
  these frames never touched stop OR target, so their observed favorable excursion is not
  capped by the target) for target placement. `closed_stop` and `closed_ic_decay` frames are
  excluded from both distributions -- they are not part of either uncensored subpopulation.

  (096) hold horizon vs feature lookahead mismatch -- the stride-bias fix (migration 230,
  `decay_threshold` rescaled 0.1->0.05) landed 2026-07-13. This diagnosis does NOT re-derive
  hold_max_bars' calibration; it CITES the already-verified live fact (RESEARCH.md "State of
  the Art", live-verified via `config_history`: last calibration run 2026-07-19 22:07 UTC,
  `decay_threshold=0.05` -- confirmed post-096-fix) as the baseline-confirmation reference this
  script prints alongside its own stop/target comparison, without recomputing it.

  (172) path-dependent frame statistics order-sensitivity -- this diagnosis computes
  percentile-of-distribution summaries (order-independent over the sample, not a cumulative
  walk), so the same-bar_ts tie-density that broke Gate 2's `c4_max_dd` reproducibility does
  NOT apply to the statistics computed here. Flagged anyway per the phase's own discipline: any
  FUTURE script this phase writes that computes a cumulative/path-dependent statistic over this
  same corpus must aggregate same-bar_ts frames first (todo 172's regression guard).

  (173) ensemble_alpha 1h/1d OOS scoring gap -- this diagnosis is IN-SAMPLE only (bar_ts <
  alpha.validation.oos_start), so it is not directly bounded by the OOS-side 1h/1d gap todo 173
  tracks. Disclosed anyway because the eventual validation gate this diagnosis feeds (a later
  Phase 166 plan) inherits the same 5m/15m-only *OOS* coverage limitation as Gate 1 -- this
  diagnosis's own regime/tf coverage should not be read as implying broader OOS-evaluable
  coverage than the data supports.

Read-only by contract: this script issues SELECT statements only. No INSERT/UPDATE/DELETE, no
ConfigService.set call, anywhere in this file. Filters to the champion `weight_epoch`
('143.1-08-champion' by default, matching `scripts/analysis/score03_gate2_execution_eval.py`'s
`_CHAMPION_WEIGHT_EPOCH`) -- Gate 2 scored this population; the diagnosis of why it failed
should measure against the same population, not a challenger under evaluation.

Usage:
    .venv/bin/python scripts/analysis/diagnose166_frame_calibration.py
    .venv/bin/python scripts/analysis/diagnose166_frame_calibration.py --weight-epoch 143.1-08-champion
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services._batch_utils import cfg as _cfg  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_CHAMPION_WEIGHT_EPOCH = "143.1-08-champion"

_DEFAULT_STOP_MAE_PERCENTILE = 90.0
_DEFAULT_TARGET_MFE_PERCENTILE = 50.0

_CURRENT_GLOBAL_SCALARS = {"stop_atr_mult": 1.5, "target_r_multiple": 2.0}

# Uncensored subpopulations (088 alignment): closed_stop and closed_ic_decay frames are
# excluded from both distributions by _summarize_excursions -- see module docstring caveat (088).
_STOP_PLACEMENT_STATUS = "closed_target"
_TARGET_PLACEMENT_STATUS = "closed_max_hold"

# bar_ts < $2 (in-sample side, per RESEARCH.md Finding 6 / OOS-EVAL-PROTOCOL.md holdout
# discipline -- this diagnosis never touches the OOS window). weight_epoch = $1 restricts to
# the champion population Gate 2 actually scored. counterfactual_mae/mfe/stop_atr_mult IS NOT
# NULL implicitly excludes 'open' frames (those columns are only populated at frame close).
_IN_SAMPLE_QUERY_SQL = """
    SELECT regime, tf, status, stop_atr_mult, counterfactual_mae, counterfactual_mfe
    FROM alpha_frames
    WHERE weight_epoch = $1
      AND bar_ts < $2
      AND regime IS NOT NULL
      AND stop_atr_mult IS NOT NULL
      AND counterfactual_mae IS NOT NULL
      AND counterfactual_mfe IS NOT NULL
"""


def _summarize_excursions(
    rows: list[dict[str, Any]],
    stop_mae_percentile: float = _DEFAULT_STOP_MAE_PERCENTILE,
    target_mfe_percentile: float = _DEFAULT_TARGET_MFE_PERCENTILE,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Per-(regime, tf) MAE/MFE percentile summary from the two uncensored subpopulations.

    Stop placement: `stop_mae_percentile`-th percentile of abs(counterfactual_mae) * stop_atr_mult
    (rescaled R-units -> ATR-units) among `closed_target` frames only -- these frames never
    touched the stop, so their observed adverse excursion is a real, uncensored measurement of
    how far against the position price moved before the target hit (088 alignment: `closed_stop`
    frames are RIGHT-CENSORED at the stop distance and are excluded here).

    Target placement: `target_mfe_percentile`-th percentile of counterfactual_mfe (R-units,
    NOT rescaled -- this is already a direct empirical estimate of a target_r_multiple) among
    `closed_max_hold` frames only -- these frames never touched stop or target, so their
    observed favorable excursion is not capped by the current target (088 alignment: any frame
    that DID hit the target would itself be right-censored at target_r_multiple).

    `closed_ic_decay` frames (and any other status) contribute to neither distribution -- they
    are not part of either uncensored subpopulation.

    Returns a dict keyed by (regime, tf) with n_qualifying counts and percentile values (None
    when a cell has zero qualifying frames for that side -- never a fabricated 0.0).
    """
    stop_excursions: dict[tuple[str, str], list[float]] = {}
    target_excursions: dict[tuple[str, str], list[float]] = {}

    for row in rows:
        key = (row["regime"], row["tf"])
        status = row["status"]
        if status == _STOP_PLACEMENT_STATUS:
            mae_atr = abs(row["counterfactual_mae"]) * row["stop_atr_mult"]
            stop_excursions.setdefault(key, []).append(mae_atr)
        elif status == _TARGET_PLACEMENT_STATUS:
            mfe_r = row["counterfactual_mfe"]
            target_excursions.setdefault(key, []).append(mfe_r)
        # closed_stop (right-censored, 088) and closed_ic_decay: excluded from both.

    summary: dict[tuple[str, str], dict[str, Any]] = {}
    for key in set(stop_excursions) | set(target_excursions):
        stop_vals = stop_excursions.get(key, [])
        target_vals = target_excursions.get(key, [])
        summary[key] = {
            "n_stop_qualifying": len(stop_vals),
            "n_target_qualifying": len(target_vals),
            "stop_atr_mult_percentile": (
                float(np.percentile(stop_vals, stop_mae_percentile)) if stop_vals else None
            ),
            "target_r_multiple_percentile": (
                float(np.percentile(target_vals, target_mfe_percentile)) if target_vals else None
            ),
            "stop_mae_percentile_used": stop_mae_percentile,
            "target_mfe_percentile_used": target_mfe_percentile,
        }
    return summary


def _compare_to_current(
    summary: dict[tuple[str, str], dict[str, Any]],
    current_global: dict[str, float] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Per-cell delta between the empirical excursion percentile and the current global scalar.

    A positive `stop_delta` means the empirical stop distance is WIDER than the current global
    1.5 ATR (the current stop is too tight for this cell); negative means narrower (too wide).
    Same sign convention for `target_delta` against the current global 2.0 target_r_multiple.
    """
    if current_global is None:
        current_global = _CURRENT_GLOBAL_SCALARS
    current_stop = current_global["stop_atr_mult"]
    current_target = current_global["target_r_multiple"]

    comparison: dict[tuple[str, str], dict[str, Any]] = {}
    for key, cell in summary.items():
        empirical_stop = cell["stop_atr_mult_percentile"]
        empirical_target = cell["target_r_multiple_percentile"]
        comparison[key] = {
            "current_stop_atr_mult": current_stop,
            "empirical_stop_atr_mult": empirical_stop,
            "stop_delta": (empirical_stop - current_stop if empirical_stop is not None else None),
            "current_target_r_multiple": current_target,
            "empirical_target_r_multiple": empirical_target,
            "target_delta": (
                empirical_target - current_target if empirical_target is not None else None
            ),
            "n_stop_qualifying": cell["n_stop_qualifying"],
            "n_target_qualifying": cell["n_target_qualifying"],
        }
    return comparison


async def _read_oos_start(conn: asyncpg.Connection) -> datetime:
    """Read alpha.validation.oos_start from config_state. Fail-loud (never a silent
    MAX(bar_ts) fallback) -- mirrors score03_gate2_execution_eval.py's _read_oos_start."""
    row = await conn.fetchrow(
        "SELECT NULLIF(config_value, '') FROM config_state "
        "WHERE config_key = 'alpha.validation.oos_start'"
    )
    if row is None or row[0] is None:
        raise RuntimeError(
            "alpha.validation.oos_start is unset -- nothing to diagnose in-sample from. "
            "Set it in config_state before running this diagnosis."
        )
    oos_start = row[0]
    if isinstance(oos_start, str):
        oos_start = datetime.fromisoformat(oos_start)
    if oos_start.tzinfo is None:
        oos_start = oos_start.replace(tzinfo=UTC)
    return oos_start


async def _load_percentile_params(conn: asyncpg.Connection) -> tuple[float, float]:
    """Read the calibration-selection percentile params seeded by migration 253. Read-only
    (SELECT only, no ConfigService.set)."""
    apr_rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])",
        [
            "alpha.ensemble_ic.stop_mae_percentile",
            "alpha.ensemble_ic.target_mfe_percentile",
        ],
    )
    apr_cfg = {row["config_key"]: row["config_value"] for row in apr_rows}
    stop_pctl = float(
        _cfg(apr_cfg, "alpha.ensemble_ic.stop_mae_percentile", _DEFAULT_STOP_MAE_PERCENTILE)
    )
    target_pctl = float(
        _cfg(apr_cfg, "alpha.ensemble_ic.target_mfe_percentile", _DEFAULT_TARGET_MFE_PERCENTILE)
    )
    return stop_pctl, target_pctl


async def _fetch_hold_max_bars_keys(conn: asyncpg.Connection) -> dict[str, str]:
    """Fetch the live alpha.frame.hold_max_bars.<regime>.<tf> keys for citation only (096
    caveat) -- this diagnosis does not recompute or re-derive hold_max_bars calibration."""
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state "
        "WHERE config_key LIKE 'alpha.frame.hold_max_bars.%' ORDER BY config_key"
    )
    return {row["config_key"]: row["config_value"] for row in rows}


def _print_report(
    comparison: dict[tuple[str, str], dict[str, Any]],
    hold_max_bars_keys: dict[str, str],
    oos_start: datetime,
    weight_epoch: str,
) -> None:
    """Aggregate-not-per-row console report (never log per-row inside a full-corpus loop)."""
    print("=" * 100)
    print("Phase 166 D-01a: Frame Calibration Diagnosis (read-only)")
    print(f"weight_epoch={weight_epoch}  in-sample cutoff (oos_start)={oos_start.isoformat()}")
    print("=" * 100)

    print(
        f"\nCitation (096, not recomputed here): hold_max_bars IS already post-096-fix "
        f"calibrated -- {len(hold_max_bars_keys)} live alpha.frame.hold_max_bars.<regime>.<tf> "
        "keys found in config_state (RESEARCH.md 'State of the Art': last calibration run "
        "2026-07-19 22:07 UTC, decay_threshold=0.05, champion weight_version aliasing "
        "confirmed byte-identical)."
    )

    print(
        "\nstop_atr_mult / target_r_multiple comparison (current global scalars: "
        f"stop_atr_mult={_CURRENT_GLOBAL_SCALARS['stop_atr_mult']}, "
        f"target_r_multiple={_CURRENT_GLOBAL_SCALARS['target_r_multiple']}):\n"
    )
    header = (
        f"{'regime':<14}{'tf':<6}{'n_stop':>8}{'n_target':>10}"
        f"{'emp_stop':>12}{'stop_Δ':>10}{'emp_target':>12}{'target_Δ':>10}"
    )
    print(header)
    print("-" * len(header))
    for regime, tf in sorted(comparison.keys()):
        cell = comparison[(regime, tf)]
        emp_stop = cell["empirical_stop_atr_mult"]
        emp_target = cell["empirical_target_r_multiple"]
        stop_delta = cell["stop_delta"]
        target_delta = cell["target_delta"]
        emp_stop_str = f"{emp_stop:.3f}" if emp_stop is not None else "n/a"
        stop_delta_str = f"{stop_delta:+.3f}" if stop_delta is not None else "n/a"
        emp_target_str = f"{emp_target:.3f}" if emp_target is not None else "n/a"
        target_delta_str = f"{target_delta:+.3f}" if target_delta is not None else "n/a"
        print(
            f"{regime:<14}{tf:<6}{cell['n_stop_qualifying']:>8}{cell['n_target_qualifying']:>10}"
            f"{emp_stop_str:>12}{stop_delta_str:>10}{emp_target_str:>12}{target_delta_str:>10}"
        )
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 166 D-01a: read-only diagnosis comparing current global "
            "stop_atr_mult/target_r_multiple scalars against empirical uncensored MAE/MFE "
            "excursion percentiles per (regime, tf). Zero writes."
        )
    )
    parser.add_argument("--weight-epoch", default=_CHAMPION_WEIGHT_EPOCH)
    args = parser.parse_args()

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            oos_start = await _read_oos_start(conn)
            stop_pctl, target_pctl = await _load_percentile_params(conn)
            rows = [
                dict(r)
                for r in await conn.fetch(_IN_SAMPLE_QUERY_SQL, args.weight_epoch, oos_start)
            ]
            hold_max_bars_keys = await _fetch_hold_max_bars_keys(conn)

        n_rows = len(rows)
        print(f"Fetched {n_rows} in-sample alpha_frames rows (aggregate count, not per-row).")

        summary = _summarize_excursions(rows, stop_pctl, target_pctl)
        comparison = _compare_to_current(summary, _CURRENT_GLOBAL_SCALARS)
        _print_report(comparison, hold_max_bars_keys, oos_start, args.weight_epoch)
    except asyncpg.PostgresError as error:
        print(f"Database error during diagnosis: {error}", file=sys.stderr)
        raise
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
