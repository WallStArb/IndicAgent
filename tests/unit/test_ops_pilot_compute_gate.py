import numpy as np

import scripts.ops.ops_pilot_compute_gate as gate
from scripts.ops.ops_pilot_compute_gate import probe_rows, series_digest


def _series(labels=("ranging", None)):
    from services.backfill_feature_factory import SeriesColumns

    numeric = np.array([[1.0, np.nan], [2.0, 0.5]], dtype=np.float32)
    regime = np.array(labels, dtype=object)
    return SeriesColumns(numeric=numeric, regime=regime, regime_volatility=regime.copy())


def test_probe_rows_are_the_quarters_inside_the_series():
    assert probe_rows(400) == [100, 200, 300]
    assert probe_rows(8) == [2, 4, 6]
    assert probe_rows(1) == [0]  # the quarters collide and dedupe
    assert probe_rows(2) == [0, 1]


def test_series_digest_equal_outputs_match_and_any_difference_moves_it():
    assert series_digest(_series()) == series_digest(_series())
    changed = _series()
    changed.numeric[1, 1] = np.nextafter(np.float32(0.5), np.float32(1))
    assert series_digest(changed) != series_digest(_series())
    relabeled = _series(labels=("trending_up", None))
    assert series_digest(relabeled) != series_digest(_series())
    none_moved = _series(labels=(None, "ranging"))
    assert series_digest(none_moved) != series_digest(_series())


def test_unit_registry_plans_the_compute_and_adds_only_readable_controls(monkeypatch):
    from src.intelligence.features.contract.registry import (
        Alignment,
        ExternalInput,
        Kernel,
        KernelRegistry,
    )

    def kernel(name, outputs, inputs, acausal=False):
        return Kernel(
            name=name,
            outputs=outputs,
            inputs=inputs,
            memory=lambda config: 0,
            compute=lambda x, config: {out: x[inputs[0]] for out in outputs},
            acausal_control=acausal,
        )

    registry = KernelRegistry.from_kernels(
        [
            kernel("series_feature", ("fv_col",), ("close",)),
            kernel("canary", ("canary_col",), ("close",), acausal=True),
            kernel("daily_grid_feature", ("ext_xa",), ("ref_spy_close",)),
        ],
        [ExternalInput("ref_spy_close", np.dtype(np.float64), Alignment.DAILY_REFERENCE_GRID)],
    )
    monkeypatch.setattr(gate, "feature_vectors_v2_output_columns", lambda: ("fv_col",))
    inputs = {"close": np.arange(4, dtype=np.float64)}
    scoped = gate.unit_registry(registry, inputs)
    assert [k.name for k in scoped.kernels] == ["series_feature", "canary"]  # daily-grid excluded
