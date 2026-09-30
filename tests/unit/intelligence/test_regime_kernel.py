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
from src.intelligence.features.contract.causality_probe import causality_probe
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
    make_collapsing_segment_bars,
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


# ---------------------------------------------------------------------------
# Lookahead in the segment gate and the length gates (186-13 task 2, todo 451)
# ---------------------------------------------------------------------------


def _kernel_and_inputs(name: str, bars: dict, tf: str = "1d"):
    kernel = default_registry().by_name(name)
    n = len(bars["close"])
    inputs = {
        "ts": bars["ts"],
        "close": bars["close"],
        "volume": bars["volume"],
        "tf": np.array([tf] * n, dtype=object),
    }
    return kernel, inputs


def test_segment_gate_verdict_does_not_depend_on_bars_after_t():
    """RED against the whole-segment gate: on the full 920 bars the first segment (bars 620..919)
    decodes into one state for its last rows, so the gate rejects it and bar 640 is unlabeled;
    cut at bar 649 the same rows are labeled. The verdict has to come from data before the
    refit boundary, so the two runs must agree."""
    bars = make_collapsing_segment_bars()
    kernel, inputs = _kernel_and_inputs("hmm_trend_walk_forward", bars)
    cut = 649
    full = kernel.compute(inputs, _config())
    truncated = kernel.compute({k: v[:cut] for k, v in inputs.items()}, _config())
    rows = slice(620, cut)
    assert np.array_equal(
        full["_hmm_trend_segment_status"][rows],
        truncated["_hmm_trend_segment_status"][rows],
    ), "the segment gate read bars after the cut"
    causality_probe(kernel, inputs, _config(), np.array([cut - 1]))


def test_first_boundary_does_not_depend_on_total_series_length():
    """RED against the whole-series length gate: at 602 observations (bars 0..621) the old
    gate refused every row, yet the full series labels bars 620 and 621. A row's label must not
    depend on how many rows come later."""
    bars = make_synthetic_regime_bars(700, 7)
    kernel, inputs = _kernel_and_inputs("hmm_trend_walk_forward", bars)
    full = kernel.compute(inputs, _config())
    assert not np.isnan(full["_hmm_trend_code"][620])  # the full series does label bar 620
    truncated = kernel.compute({k: v[:622] for k, v in inputs.items()}, _config())
    assert np.array_equal(
        full["_hmm_trend_code"][:622], truncated["_hmm_trend_code"], equal_nan=True
    )


# (kernel, tf, bar count, probed rows): rows just after a refit boundary (obs boundary + 20
# warmup bars + a few), mid-segment and the last row. SMALL_HMM_APR schedules: 1d refit 300 /
# warmup 600; 1h refit 450 / warmup 900.
_PROBE_CASES = [
    (name, tf, n, rows)
    for name in ("hmm_trend_walk_forward", "hmm_volatility_walk_forward")
    for tf, n, rows in (
        ("1d", 1250, (625, 760, 925, 1249)),
        ("1h", 1700, (925, 1100, 1375, 1699)),
    )
]


@pytest.mark.parametrize("name,tf,n,rows", _PROBE_CASES)
def test_causality_probe_passes_the_walk_forward_kernels(name, tf, n, rows):
    """ulp 0 on every output, truncating at rows just after a refit boundary, mid-segment and at
    the last row (todo 451: this fails before the training-slice gate)."""
    bars = make_synthetic_regime_bars(n, 42)
    kernel, inputs = _kernel_and_inputs(name, bars, tf)
    causality_probe(kernel, inputs, _config(), np.array(rows), ulp=0)


def test_every_regime_origin_kernel_is_covered_by_a_probe_or_label_test():
    """`non_regime_kernels` exempts the whole `regime` origin from the generic probe runs, so a
    kernel added to that origin would inherit the exemption unnoticed. Each one has to be a
    heavy kernel in `_PROBE_CASES` or a label kernel `test_label_kernels_are_row_local` runs."""
    regime_kernels = {k.name for k in default_registry().kernels if k.origin == "regime"}
    probed = {name for name, *_ in _PROBE_CASES}
    label_tested = {f"hmm_{family}_label" for family in FAMILIES}
    assert regime_kernels == probed | label_tested


@pytest.mark.parametrize("family", FAMILIES)
def test_label_kernels_are_row_local(family):
    spec = FAMILY_KERNELS[family]
    label_kernel = default_registry().by_name(f"hmm_{family}_label")
    code = _run(_bars(), family)[spec.code_output]
    full = label_kernel.compute({spec.code_output: code}, _config())[spec.label_output]
    for t in (10, 1900, 2999):
        cut = label_kernel.compute({spec.code_output: code[: t + 1]}, _config())[spec.label_output]
        assert list(cut) == list(full[: t + 1])


def test_segment_gate_is_taken_on_the_training_slice():
    """Each segment's gate diagnostics name their basis, and the collapsing segment (whose
    decode occupies one state for its last rows) is written, because its model's training slice
    passes the gate."""
    bars = make_collapsing_segment_bars()
    config = _config()
    obs, _ = _hmm._build_obs_matrix(
        list(range(len(bars["close"]))),
        bars["close"],
        bars["volume"],
        vol_window=config.hmm_vol_window,
        momentum_window=config.hmm_momentum_window,
        vol_of_vol_window=config.hmm_vol_of_vol_window,
    )
    segments = _hmm._walk_forward_hmm_full(
        obs,
        config.hmm_n_components,
        config.hmm_covariance_type,
        config.hmm_n_iter,
        config.hmm_random_state,
        config.hmm_refit_every_bars_1d,
        config.hmm_initial_warmup_bars_1d,
        config.hmm_min_hold_bars,
        config.hmm_full_cov_min_obs,
        config.hmm_min_state_occupation,
        min_obs_factor=config.hmm_min_obs_factor,
    )
    assert len(segments) == 1
    assert segments[0]["gate_info"]["gate_basis"] == "training_slice"
    assert not segments[0]["is_degenerate"]


# ---------------------------------------------------------------------------
# Bounded rolling-window memory in the obs builders (todo 290 item 1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("window", [20, 60, 250])
@pytest.mark.parametrize("block_rows", [1, 7, 4096, 5000])
@pytest.mark.parametrize("fn", [np.std, np.sum, np.mean], ids=lambda f: f.__name__)
def test_blocked_rolling_is_bitwise_equal_to_unblocked(window, block_rows, fn):
    rng = np.random.default_rng(window * 31 + block_rows)
    series = rng.normal(0.0, 0.01, 5000)
    want = _hmm._rolling(series, window, fn)
    got = _hmm._rolling(series, window, fn, block_rows=block_rows)
    assert got.dtype == want.dtype and got.shape == want.shape
    assert np.array_equal(got.view(np.uint64), want.view(np.uint64))


def test_blocked_rolling_short_series_and_no_block_are_unchanged():
    series = np.arange(30, dtype=float)
    assert np.array_equal(
        _hmm._rolling(series, 20, np.std, block_rows=3), _hmm._rolling(series, 20, np.std)
    )
    # the series is exactly one window long: one real value, window - 1 zeros
    assert _hmm._rolling(series[:20], 20, np.sum, block_rows=4)[-1] == series[:20].sum()


@pytest.mark.parametrize("family", FAMILIES)
def test_obs_builders_are_bitwise_equal_when_blocked(family):
    bars = _bars()
    rows = list(range(len(bars["close"])))
    if family == "trend":
        args = (rows, bars["close"], bars["volume"])
        kwargs = dict(vol_window=20, momentum_window=20, vol_of_vol_window=20)
        build = _hmm._build_obs_matrix
    else:
        args = (rows, bars["close"])
        kwargs = dict(vol_window=20, vol_of_vol_window=60)
        build = _hmm._build_obs_matrix_volatility
    want, want_rows = build(*args, **kwargs)
    got, got_rows = build(*args, **kwargs, block_rows=257)
    assert want_rows == got_rows
    assert np.array_equal(got.view(np.uint64), want.view(np.uint64))


def test_block_rows_config_default_and_reaches_the_kernels():
    fields = _hmm.hmm_config_fields_from_values(lambda key, default: default)
    assert fields["hmm_rolling_block_rows"] == 16384
    fields = _hmm.hmm_config_fields_from_values({"infra.hmm.rolling_block_rows": 64}.get)
    assert fields["hmm_rolling_block_rows"] == 64
