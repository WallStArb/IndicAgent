"""Pilot compute gates G4 and G5 on real bars (todo 584 design D3; sibling of
ops_feature_column_screen.py, which gates the STORED columns as G1-G3).

- G4 causality: the existing `probe_registry` (contract/causality_probe.py, the same
  truncation probe the research S3 guard adopts) over real bars at three truncation points
  (rows n//4, n//2, 3n//4): every kernel in topological order, path-dependent kernels
  included (causality only), the acausal control must fail, and a memory violation is a
  failure, not a skip.
- G5 determinism: each unit computed twice through the rebuild's own path
  (`_series_kernel_inputs` + `_compute_series_columns`, the exact composition of
  `_rebuild_worker`) and the two outputs hashed bit-level; the report stores the digests, so
  running the script twice and comparing reports is the cross-process check.

One unit is one (symbol, tf). Compute cost is the rebuild's: G4 at 5m recomputes the HMM
walk-forward four times per family (full + three truncations), tens of minutes per unit; a
pilot gate run picks its units accordingly (1d units cost seconds). Nothing is written to the
database; bars are read through the tradeable view like the rebuild.

Run: .venv/bin/python scripts/ops/ops_pilot_compute_gate.py --units SPY:1d AAPL:5m
Output: a JSON report under logs/ and the gate results on stdout. Exit 0 when both gates pass
on every unit, 1 when any gate fails, 2 when a unit could not be screened at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import (  # noqa: E402
    _NO_FLOOR,
    _build_feature_factory_config,
    _compute_series_columns,
    _fetch_bar_arrays,
    _fetch_bars_from_db,
    _series_kernel_inputs,
    build_daily_records,
    default_data_horizon,
    feature_vectors_v2_output_columns,
)
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.features.contract.causality_probe import (  # noqa: E402
    CausalityViolation,
    MemoryViolation,
    probe_registry,
    with_derived_inputs,
)
from src.intelligence.features.contract.registry import (  # noqa: E402
    KernelRegistry,
    default_registry,
)
from src.intelligence.features.kernels._hmm import load_rolling_block_rows  # noqa: E402
from src.intelligence.features.kernels.macro import (  # noqa: E402
    HYG,
    LQD,
    SHY,
    SPY,
    TIP,
    TLT,
    build_cross_asset_series,
    build_symbol_beta_series,
)

REPORT_DIR = project_root / "logs"


def unit_registry(registry: KernelRegistry, inputs: dict) -> KernelRegistry:
    """The kernels one pilot unit's compute runs: the registry's own plan for the table's output
    columns, plus the acausal controls that read this bundle (they must fail the probe). The
    daily-grid kernels (`cross_asset_daily`, `factor_beta_daily`) are excluded because the unit
    compute never runs them: their outputs arrive as the `ext_*` externals `_series_kernel_inputs`
    aligns onto the rows, so their inputs (`ref_spy_close`, ...) are not in the bundle."""
    kernels = list(registry.topological_order(list(feature_vectors_v2_output_columns())))
    planned = {kernel.name for kernel in kernels}
    closable = with_derived_inputs(inputs)
    kernels += [
        k
        for k in registry.kernels
        if k.acausal_control and k.name not in planned and set(k.inputs) <= set(closable)
    ]
    return KernelRegistry.from_kernels(kernels, registry.external_inputs)


def probe_rows(n: int) -> list[int]:
    """The three truncation rows of a series of n bars: the quarters, deduplicated and
    ordered (a short series can collide) and kept inside the series."""
    return sorted({min(n * q // 4, n - 1) for q in (1, 2, 3)})


def series_digest(series) -> str:
    """One hash over everything a unit's compute produces: the float32 numeric matrix in
    its column order and the two label columns (None kept distinct from any label)."""
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(series.numeric).tobytes())
    for column in (series.regime, series.regime_volatility):
        h.update("\x00".join("" if v is None else str(v) for v in column).encode())
    return h.hexdigest()


def _unit_inputs(
    conn,
    symbol: str,
    tf: str,
    config,
    cross_asset_by_date: dict,
    reference: dict,
    horizon,
    block_rows,
):
    """Bars and every external input of one unit, built exactly as `_rebuild_worker` builds
    them (the same helpers, one definition of each alignment)."""
    bars, _ = _fetch_bar_arrays(conn, symbol, tf, horizon, block_rows, _NO_FLOOR)
    symbol_1d = _fetch_bars_from_db(conn, symbol, "1d", until=horizon, floor=_NO_FLOOR)
    beta_by_date = build_symbol_beta_series(
        symbol_1d, reference[SPY], reference[TLT], symbol, config
    )
    htf_tf = config.ctf_higher_tf_map[tf]
    htf_bars = (
        symbol_1d if htf_tf == "1d" else _fetch_bars_from_db(conn, symbol, htf_tf, until=horizon)
    )
    return bars, _series_kernel_inputs(
        symbol,
        tf,
        bars,
        config,
        cross_asset_by_date,
        beta_by_date,
        htf_bars,
        build_daily_records(conn, symbol, symbol_1d, reference[SPY], config),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--units", nargs="+", required=True, help="SYMBOL:TF pairs to gate")
    args = parser.parse_args(argv)
    units = []
    for unit in args.units:
        symbol, _, tf = unit.rpartition(":")
        if not symbol or not tf:
            parser.error(f"--units needs SYMBOL:TF pairs, got {unit!r}")
        units.append((symbol, tf))

    registry = default_registry()
    report: dict = {"generated": datetime.now(UTC).isoformat(), "units": {}}
    failures = errors = 0
    with psycopg.connect(get_settings().database_url) as conn:
        cfg = load_config_service_sync(conn)
        config = _build_feature_factory_config(cfg)
        block_rows = load_rolling_block_rows(cfg.get_sync)
        horizon = default_data_horizon()
        reference = {
            name: _fetch_bars_from_db(conn, name, "1d", until=horizon)
            for name in (SPY, TLT, SHY, TIP, HYG, LQD)
        }
        cross_asset_by_date = build_cross_asset_series(
            reference[SPY],
            reference[TLT],
            reference[SHY],
            reference[TIP],
            reference[HYG],
            reference[LQD],
            config,
        )
        for symbol, tf in units:
            entry: dict = {}
            report["units"][f"{symbol}:{tf}"] = entry
            try:
                _, inputs = _unit_inputs(
                    conn, symbol, tf, config, cross_asset_by_date, reference, horizon, block_rows
                )
                n = len(inputs["close"])
                entry["rows"] = n
                # G4: truncation causality over every kernel; a violation names the kernel.
                entry["probe_rows"] = probe_rows(n)
                try:
                    unit = unit_registry(registry, inputs)
                    entry["g4_kernels"] = len(unit.kernels)
                    entry["g4"] = probe_registry(unit, inputs, config, entry["probe_rows"])
                except (CausalityViolation, MemoryViolation) as error:
                    entry["g4"] = f"FAIL {type(error).__name__}: {error}"
                    failures += 1
                # G5: the same unit computed twice, bit-identical.
                first = _compute_series_columns(inputs, config)
                second = _compute_series_columns(inputs, config)
                entry["digest_first"] = series_digest(first)
                entry["digest_second"] = series_digest(second)
                if entry["digest_first"] != entry["digest_second"]:
                    entry["g5"] = "FAIL digests differ"
                    failures += 1
                else:
                    entry["g5"] = "ok"
                g4 = entry["g4"] if isinstance(entry["g4"], str) else "ok"
                print(f"{symbol}:{tf}: rows {n}, g4 {g4}, g5 {entry['g5']}", flush=True)
            except Exception as error:  # a unit that cannot be screened is exit 2, not a gate fail
                entry["error"] = f"{type(error).__name__}: {error}"
                errors += 1
                print(f"{symbol}:{tf}: ERROR {entry['error']}", file=sys.stderr, flush=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"pilot_compute_gate_{stamp}.json"
    path.write_text(json.dumps(report, indent=1, sort_keys=True, default=str))
    print(f"g4/g5 failures {failures}, errors {errors}; report: {path}")
    if errors:
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
