"""The production feature path against real-data golden digests (R2 item 1).

The corpus rerun computes `feature_vectors` through `_series_kernel_inputs` and
`_compute_series_columns` (one `compute_kernels` call from the series start, declared-warmup and
none masks, float32 clamp). The older golden (`real_golden.json`) is computed by the legacy
`FeatureFactory.compute_batch`, a path the rerun never runs. `production_golden.json` pins the
rerun's own path over the same stored real cases; regenerate it with
`features_capture_kernel_parity_golden --production --reason ...` in a commit of its own.

The second test ties the two together while the legacy path still exists: after each column's
declared warmup the production values equal the legacy reference bit for bit in float32. The
differences are the rows the production path masks by declared memory (the legacy path wrote a
value or 0.0 there) and the three regime-model columns, which the legacy path read from a cache
that the production path replaces with the walk-forward HMM. Delete that test with
`compute_batch` (R2 item 2); `production_golden.json` then carries the pin alone.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from tests.unit.intelligence import kernel_parity_reference as ref

MANIFEST = ref.load_manifest()
GOLDEN = json.loads((ref.FIXTURE_DIR / "production_golden.json").read_text())["cases"]
REAL_CASES = [c for c in MANIFEST["sample"]["cases"] if c["kind"] == "real"]
# Columns whose value comes from the regime model: not comparable across the two paths.
REGIME_MODEL_COLUMNS = frozenset({"hmm_regime_prob", "hmm_entropy", "hmm_duration"})


@pytest.mark.parametrize("case", REAL_CASES, ids=ref.case_id)
def test_production_path_matches_its_golden_digests(case):
    cid = ref.case_id(case)
    digest = ref.digest_output(ref.compute_production(case))
    golden = GOLDEN[cid]
    assert digest["rows"] == golden["rows"], f"{cid}: row count"
    assert digest["bar_ts_sha256"] == golden["bar_ts_sha256"], f"{cid}: bar_ts digest"
    assert sorted(digest["columns"]) == sorted(golden["columns"]), f"{cid}: column set"
    changed = [c for c, d in digest["columns"].items() if d != golden["columns"][c]]
    assert not changed, f"{cid}: {len(changed)} column digest(s) moved, first {changed[:5]}"


@pytest.mark.parametrize("case", REAL_CASES, ids=ref.case_id)
def test_production_path_equals_the_legacy_reference_after_declared_warmup(case):
    from services.backfill_feature_factory import column_warmup_bars
    from src.core.market_calendar import get_market_calendar
    from src.intelligence.features.contract.registry import default_registry
    from src.intelligence.features.feature_vector_persistence import feature_vectors_numeric_columns
    from src.intelligence.features.kernels._hmm import HmmConfig
    from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR

    real = ref._real_case_inputs(case, MANIFEST, ref.FIXTURE_DIR)
    config = dataclasses.replace(real.config, hmm=HmmConfig.from_values(SMALL_HMM_APR.get))
    warmups = column_warmup_bars(default_registry(), feature_vectors_numeric_columns(), config)
    calendar = get_market_calendar()
    rows = np.array(
        [
            i
            for i, bar in enumerate(real.bars)
            if i >= MANIFEST["warm_up_bars"]
            and calendar.is_trading_bar("NYSE", bar["ts"], case["tf"])
        ]
    )
    legacy, production = ref.compute_reference(case), ref.compute_production(case)
    assert np.array_equal(legacy.bar_ts, production.bar_ts)
    for name, produced in production.columns.items():
        if name in REGIME_MODEL_COLUMNS:
            continue
        expected = legacy.columns[name]
        equal = (expected == produced) | (np.isnan(expected) & np.isnan(produced))
        masked_by_memory = np.isnan(produced) & (rows < warmups.get(name, 0))
        bad = ~(equal | masked_by_memory)
        assert not bad.any(), (
            f"{ref.case_id(case)} {name}: {int(bad.sum())} row(s) differ outside the declared "
            f"warmup, first at row {int(rows[np.argmax(bad)])}"
        )
