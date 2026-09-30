"""Walk-forward HMM regime kernels (186-13, D-29, R-10).

Golden parity: both families reproduce the golden captured from the unchanged regime_writer
(`tests/fixtures/regime_kernel/`): label index equal, float32 columns bitwise equal, on the
synthetic case and on every 1d real case (SPY, TLT, LQD; LQD exercises the degenerate skip path).
The SPY 1h case is checked by `features_capture_regime_kernel_golden.py --verify`, not here,
because it takes about a minute per family. The fit runs with one BLAS thread, as production's
worker pool does; more threads change the low bits and are not run to run reproducible.

Measured (BLAS threads 1): the synthetic case about 1 s per family, the three 1d real cases
together about 16 s, so all of them run here; SPY 1h is left to --verify (about 40 s).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from threadpoolctl import threadpool_limits

from scripts.infrastructure.features_capture_regime_kernel_golden import (
    load_real_inputs,
    load_synthetic,
    run_kernel_case,
)
from src.intelligence.features.contract.registry import (
    KernelRegistryError,
    compute_kernels,
    default_registry,
    feature_memory_bars,
)
from src.intelligence.features.feature_vector_persistence import (
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
from src.intelligence.features.kernels import _hmm
from src.intelligence.features.kernels.regime import FAMILY_KERNELS
from tests.unit.intelligence.regime_kernel_fixtures import (
    FAMILY_LABELS,
    SMALL_HMM_APR,
    digest_case,
    make_synthetic_regime_bars,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "regime_kernel"
FAMILIES = ("trend", "volatility")
ALL_COLUMNS = (*REGIME_WRITER_OWNED_COLUMN_NAMES, *REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)


@pytest.fixture(autouse=True)
def _one_blas_thread():
    with threadpool_limits(1):
        yield


@lru_cache(maxsize=1)
def _manifest() -> dict:
    return json.loads((FIXTURE_DIR / "manifest.json").read_text())


def _bits(values: np.ndarray) -> np.ndarray:
    """float32 bit patterns with one NaN pattern and no negative zero."""
    arr = np.asarray(values, dtype=np.float32)
    arr = np.where(np.isnan(arr), np.float32("nan"), arr) + np.float32(0.0)
    return arr.view(np.uint32)


@pytest.mark.parametrize("family", FAMILIES)
def test_synthetic_case_reproduces_the_writer_golden(family):
    stored = np.load(FIXTURE_DIR / "synthetic_golden.npz")
    bars = load_synthetic(FIXTURE_DIR)
    labels, columns = run_kernel_case(SMALL_HMM_APR, bars, family, "1d")
    assert np.array_equal(labels, stored[f"{family}/labels"])
    for c in range(len(columns)):
        assert np.array_equal(_bits(columns[c]), _bits(stored[f"{family}/columns"][c])), c


@pytest.mark.parametrize("case", ["SPY/1d", "TLT/1d", "LQD/1d"])
def test_real_daily_cases_reproduce_the_writer_golden(case):
    stored = json.loads((FIXTURE_DIR / "real_golden.json").read_text())
    bars = load_real_inputs(FIXTURE_DIR)[case]
    tf = case.split("/")[1]
    for family in FAMILIES:
        got = digest_case(*run_kernel_case(_manifest()["apr_snapshot"], bars, family, tf))
        assert got == stored[f"{case}/{family}"], f"{case}/{family}"


def test_label_tuples_equal_the_golden_label_order():
    assert _hmm.TREND_LABELS == FAMILY_LABELS["trend"]
    assert _hmm.VOLATILITY_LABELS == FAMILY_LABELS["volatility"]
    for family in FAMILIES:
        assert FAMILY_KERNELS[family].labels == FAMILY_LABELS[family]


def test_registry_owns_the_sixteen_regime_columns():
    registry = default_registry()
    outputs = {o for k in registry.kernels if k.origin == "regime" for o in k.outputs}
    columns = set(registry.feature_columns()) & set(ALL_COLUMNS)
    assert columns == set(ALL_COLUMNS) and len(ALL_COLUMNS) == 16
    assert FAMILY_KERNELS["trend"].numeric_outputs == REGIME_WRITER_OWNED_COLUMN_NAMES[1:]
    assert (
        FAMILY_KERNELS["volatility"].numeric_outputs
        == REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES[1:]
    )
    assert FAMILY_KERNELS["trend"].label_output == REGIME_WRITER_OWNED_COLUMN_NAMES[0]
    assert (
        FAMILY_KERNELS["volatility"].label_output == REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES[0]
    )
    assert set(ALL_COLUMNS) <= outputs
    # the intermediates are not feature columns
    assert not [o for o in registry.feature_columns() if o.startswith("_hmm")]


def _config(apr: dict | None = None):
    """The hmm_* config attributes over `apr` (SMALL_HMM_APR by default)."""
    values = SMALL_HMM_APR if apr is None else apr
    return SimpleNamespace(**_hmm.hmm_config_fields_from_values(values.get))


@pytest.mark.parametrize("column", ALL_COLUMNS)
def test_feature_memory_bars_raises_for_every_regime_column(column):
    with pytest.raises(KernelRegistryError, match="path dependent"):
        feature_memory_bars(column, _config({}))


def _run(bars: dict, family: str, tf: str = "1d", *, tf_values=None, outputs=None):
    spec = FAMILY_KERNELS[family]
    n = len(bars["close"])
    inputs = {
        "ts": bars["ts"],
        "close": bars["close"],
        "volume": bars["volume"],
        "tf": np.array(tf_values if tf_values is not None else [tf] * n, dtype=object),
    }
    return compute_kernels(
        default_registry(),
        inputs,
        _config(),
        outputs=outputs or [spec.code_output, spec.status_output, spec.label_output],
    )


@lru_cache(maxsize=1)
def _bars():
    return make_synthetic_regime_bars(3000, 42)


@pytest.mark.parametrize("family", FAMILIES)
def test_label_kernel_maps_the_code_and_leaves_none_where_unlabeled(family):
    out = _run(_bars(), family)
    spec = FAMILY_KERNELS[family]
    code = out[spec.code_output]
    label = out[spec.label_output]
    assert label.dtype == object
    assert (label == None).sum() == np.isnan(code).sum()  # noqa: E711
    written = ~np.isnan(code)
    assert written.any()
    assert list(label[written][:5]) == [spec.labels[int(c)] for c in code[written][:5]]


@pytest.mark.parametrize("family", FAMILIES)
def test_non_finite_tail_is_unlabeled_from_its_first_row(family):
    bars = {k: v.copy() for k, v in _bars().items()}
    cut = 2400
    bars["close"][cut:] = np.nan
    bars["volume"][cut:] = np.nan
    spec = FAMILY_KERNELS[family]
    tail = _run(bars, family)
    head = _run({k: v[:cut] for k, v in bars.items()}, family)
    assert np.isnan(tail[spec.code_output][cut:]).all()
    assert (tail[spec.status_output][cut:] == _hmm.STATUS_NO_MODEL).all()
    assert (tail[spec.label_output][cut:] == None).all()  # noqa: E711
    # the finite prefix is exactly what the same rows give on their own
    assert np.array_equal(tail[spec.code_output][:cut], head[spec.code_output], equal_nan=True)


@pytest.mark.parametrize("family", FAMILIES)
def test_non_finite_value_followed_by_finite_rows_raises(family):
    bars = {k: v.copy() for k, v in _bars().items()}
    bars["close"][900] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        _run(bars, family)


@pytest.mark.parametrize("family", FAMILIES)
def test_unknown_or_changing_tf_raises(family):
    with pytest.raises(ValueError, match="timeframes"):
        _run(_bars(), family, tf="7m")
    n = len(_bars()["close"])
    mixed = ["1d"] * (n - 1) + ["1h"]
    with pytest.raises(ValueError, match="one tf per series"):
        _run(_bars(), family, tf_values=mixed)


def test_series_too_short_for_a_model_is_all_unlabeled():
    short = {k: v[:300] for k, v in _bars().items()}
    for family in FAMILIES:
        out = _run(short, family)
        spec = FAMILY_KERNELS[family]
        assert np.isnan(out[spec.code_output]).all()
        assert (out[spec.status_output] == _hmm.STATUS_NO_MODEL).all()
