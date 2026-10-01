"""Walk-forward HMM regime kernels (186-13, D-29, R-10).

Golden parity: both families reproduce the golden captured from the unchanged regime_writer
(`tests/fixtures/regime_kernel/`): label index equal, float32 columns bitwise equal, on the
synthetic case and on every 1d real case (SPY, TLT, LQD; LQD exercises the degenerate skip path).
The SPY 1h case is checked by `features_capture_regime_kernel_golden.py --verify`, not here,
because it takes about a minute per family. The kernel pins its own BLAS to one thread, so these
tests run under whatever thread count the process has (more threads would change the low bits and
are not run to run reproducible).

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
from src.intelligence.features.kernels._hmm import FAMILY_SPECS
from src.intelligence.features.kernels.regime import compute_regime_columns
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


@pytest.mark.parametrize("threads", [8, 24])
def test_kernel_output_does_not_depend_on_the_callers_blas_threads(threads):
    """Determinism is the kernel's own property: a caller running many BLAS threads gets the
    single-thread golden. On this box the trend synthetic case differs at 8 and 24 threads
    without the kernel's own pin."""
    stored = np.load(FIXTURE_DIR / "synthetic_golden.npz")
    bars = load_synthetic(FIXTURE_DIR)
    with threadpool_limits(threads):
        labels, columns = run_kernel_case(SMALL_HMM_APR, bars, "trend", "1d")
    assert np.array_equal(labels, stored["trend/labels"])
    for c in range(len(columns)):
        assert np.array_equal(_bits(columns[c]), _bits(stored["trend/columns"][c])), c


def test_two_threads_running_the_kernel_concurrently_both_match_the_golden():
    """`threadpool_limits` is process-global and not reentrant: two threads each pinning and
    restoring it can leave one of them running (or restoring) the wrong thread count. The heavy
    kernel serializes its pinned section behind a lock, so concurrent callers, each inside
    their own `threadpool_limits(8)`, both get the single-thread golden."""
    import threading

    stored = np.load(FIXTURE_DIR / "synthetic_golden.npz")
    bars = load_synthetic(FIXTURE_DIR)
    results: dict[int, tuple] = {}
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def work(i: int) -> None:
        try:
            with threadpool_limits(8):
                barrier.wait()
                results[i] = run_kernel_case(SMALL_HMM_APR, bars, "trend", "1d")
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for i in range(2):
        labels, columns = results[i]
        assert np.array_equal(labels, stored["trend/labels"]), i
        for c in range(len(columns)):
            assert np.array_equal(_bits(columns[c]), _bits(stored["trend/columns"][c])), (i, c)


def test_the_pin_is_reentrant_within_one_thread():
    """A kernel call nested inside a pinned section of the same thread must not deadlock."""
    with _hmm.pinned_blas_threads(), _hmm.pinned_blas_threads():
        pass


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
        assert FAMILY_SPECS[family].labels == FAMILY_LABELS[family]


def test_registry_owns_the_sixteen_regime_columns():
    registry = default_registry()
    outputs = {o for k in registry.kernels if k.origin == "regime" for o in k.outputs}
    columns = set(registry.feature_columns()) & set(ALL_COLUMNS)
    assert columns == set(ALL_COLUMNS) and len(ALL_COLUMNS) == 16
    assert FAMILY_SPECS["trend"].numeric_outputs == REGIME_WRITER_OWNED_COLUMN_NAMES[1:]
    assert (
        FAMILY_SPECS["volatility"].numeric_outputs
        == REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES[1:]
    )
    assert FAMILY_SPECS["trend"].regime_column == REGIME_WRITER_OWNED_COLUMN_NAMES[0]
    assert (
        FAMILY_SPECS["volatility"].regime_column == REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES[0]
    )
    assert set(ALL_COLUMNS) <= outputs
    # the intermediates are not feature columns
    assert not [o for o in registry.feature_columns() if o.startswith("_hmm")]


def _config(apr: dict | None = None):
    """The registry config the kernels read: `hmm` loaded from `apr` (SMALL_HMM_APR by default)."""
    values = SMALL_HMM_APR if apr is None else apr
    return SimpleNamespace(hmm=_hmm.HmmConfig.from_values(values.get))


@pytest.mark.parametrize("column", ALL_COLUMNS)
def test_feature_memory_bars_raises_for_every_regime_column(column):
    with pytest.raises(KernelRegistryError, match="path dependent"):
        feature_memory_bars(column, SimpleNamespace(hmm=None))


def _run(bars: dict, family: str, tf: str = "1d", *, tf_values=None, outputs=None):
    spec = FAMILY_SPECS[family]
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
        outputs=outputs or [spec.code_output, spec.status_output, spec.regime_column],
    )


@lru_cache(maxsize=1)
def _bars():
    return make_synthetic_regime_bars(3000, 42)


@pytest.mark.parametrize("family", FAMILIES)
def test_label_kernel_maps_the_code_and_leaves_none_where_unlabeled(family):
    out = _run(_bars(), family)
    spec = FAMILY_SPECS[family]
    code = out[spec.code_output]
    label = out[spec.regime_column]
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
    spec = FAMILY_SPECS[family]
    tail = _run(bars, family)
    head = _run({k: v[:cut] for k, v in bars.items()}, family)
    assert np.isnan(tail[spec.code_output][cut:]).all()
    assert (tail[spec.status_output][cut:] == _hmm.STATUS_NO_MODEL).all()
    assert (tail[spec.regime_column][cut:] == None).all()  # noqa: E711
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
        spec = FAMILY_SPECS[family]
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
    """RED against the whole-segment gate: on the full 939 bars the first segment (bars 639..938)
    decodes into one state for its last rows, so the gate rejects it and bar 660 is unlabeled;
    cut at bar 668 the same rows are labeled. The verdict has to come from data before the
    refit boundary, so the two runs must agree."""
    bars = make_collapsing_segment_bars()
    kernel, inputs = _kernel_and_inputs("hmm_trend_walk_forward", bars)
    cut = 668
    full = kernel.compute(inputs, _config())
    truncated = kernel.compute({k: v[:cut] for k, v in inputs.items()}, _config())
    rows = slice(639, cut)
    assert np.array_equal(
        full["_hmm_trend_segment_status"][rows],
        truncated["_hmm_trend_segment_status"][rows],
    ), "the segment gate read bars after the cut"
    causality_probe(kernel, inputs, _config(), np.array([cut - 1]))


def test_first_boundary_does_not_depend_on_total_series_length():
    """RED against the whole-series length gate: at 602 observations (bars 0..640) the old
    gate refused every row, yet the full series labels bars 639 and 640. A row's label must not
    depend on how many rows come later."""
    bars = make_synthetic_regime_bars(720, 7)
    kernel, inputs = _kernel_and_inputs("hmm_trend_walk_forward", bars)
    full = kernel.compute(inputs, _config())
    assert not np.isnan(full["_hmm_trend_code"][639])  # the full series does label bar 639
    truncated = kernel.compute({k: v[:641] for k, v in inputs.items()}, _config())
    assert np.array_equal(
        full["_hmm_trend_code"][:641], truncated["_hmm_trend_code"], equal_nan=True
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
    """The registry-wide probe tests run every regime kernel on the short series under the small
    HMM configuration; this file adds the per-tf and boundary-row probes for the heavy kernels.
    A kernel added to the origin has to be a heavy kernel in `_PROBE_CASES` or a label kernel
    `test_label_kernels_are_row_local` runs."""
    regime_kernels = {k.name for k in default_registry().kernels if k.origin == "regime"}
    probed = {name for name, *_ in _PROBE_CASES}
    label_tested = {f"hmm_{family}_label" for family in FAMILIES}
    assert regime_kernels == probed | label_tested


@pytest.mark.parametrize("family", FAMILIES)
def test_label_kernels_are_row_local(family):
    spec = FAMILY_SPECS[family]
    label_kernel = default_registry().by_name(f"hmm_{family}_label")
    code = _run(_bars(), family)[spec.code_output]
    full = label_kernel.compute({spec.code_output: code}, _config())[spec.regime_column]
    for t in (10, 1900, 2999):
        cut = label_kernel.compute({spec.code_output: code[: t + 1]}, _config())[spec.regime_column]
        assert list(cut) == list(full[: t + 1])


def test_segment_gate_is_taken_on_the_training_slice():
    """Each segment's gate diagnostics name their basis, and the collapsing segment (whose
    decode occupies one state for its last rows) is written, because its model's training slice
    passes the gate."""
    bars = make_collapsing_segment_bars()
    config = _config().hmm
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
        covariance_ridge=config.hmm_covariance_ridge,
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


def _same_column(a: np.ndarray, b: np.ndarray) -> bool:
    """Exact equality, NaN equal to NaN, object columns (labels, None) compared as lists."""
    if a.dtype == object or b.dtype == object:
        return list(a) == list(b)
    return np.array_equal(a, b, equal_nan=True)


@pytest.mark.parametrize("family", FAMILIES)
def test_block_rows_argument_changes_no_output(family):
    """`block_rows` is the caller's memory bound (`infra.hmm.rolling_block_rows`): the shared
    entry point returns the same columns at any block size, and with none."""
    bars = _bars()
    params = _hmm.HmmConfig.from_values(SMALL_HMM_APR.get)
    spec = FAMILY_SPECS[family]
    want = compute_regime_columns(bars["close"], bars["volume"], params, "1d", spec, None).columns
    for block_rows in (1, 257, 16384):
        got = compute_regime_columns(
            bars["close"], bars["volume"], params, "1d", spec, block_rows
        ).columns
        assert list(got) == list(want)
        assert all(_same_column(got[name], want[name]) for name in want), block_rows


@pytest.mark.parametrize("family", FAMILIES)
def test_the_shared_entry_point_equals_the_registry_kernels(family):
    """The writer and the rebuild both call `compute_regime_columns`; the registry kernels are
    what the kernel-parity machinery runs. They must return the same columns, label included."""
    spec = FAMILY_SPECS[family]
    bars = _bars()
    params = _hmm.HmmConfig.from_values(SMALL_HMM_APR.get)
    shared = compute_regime_columns(bars["close"], bars["volume"], params, "1d", spec).columns
    outputs = [spec.code_output, spec.status_output, *spec.numeric_outputs, spec.regime_column]
    registry = _run(bars, family, outputs=outputs)
    assert set(shared) == set(outputs)
    assert all(_same_column(shared[name], registry[name]) for name in outputs)


def test_the_shared_entry_point_rejects_an_unknown_tf_and_a_volatility_run_needs_no_volume():
    params = _hmm.HmmConfig.from_values(SMALL_HMM_APR.get)
    bars = _bars()
    with pytest.raises(ValueError, match="timeframes"):
        compute_regime_columns(bars["close"], bars["volume"], params, "7m", FAMILY_SPECS["trend"])
    volatility = FAMILY_SPECS["volatility"]
    with_volume = compute_regime_columns(
        bars["close"], bars["volume"], params, "1d", volatility
    ).columns
    without = compute_regime_columns(bars["close"], None, params, "1d", volatility).columns
    assert all(_same_column(with_volume[name], without[name]) for name in with_volume)


# ---------------------------------------------------------------------------
# Todo 286: trend obs rows start after the nested vol_of_vol warmup
# ---------------------------------------------------------------------------


def test_trend_vol_of_vol_never_reaches_the_zero_padded_realized_vol_warmup():
    """Todo 286. vol_of_vol is a rolling std of realized_vol, whose first `vol_window - 1` rows
    are zero padding from `_rolling`. The first emitted trend obs row must therefore have a
    vol_of_vol over a window made entirely of full-window realized_vol values, equal to the
    population std computed here independently from the log returns."""
    vol_window = momentum_window = vol_of_vol_window = 20
    rng = np.random.default_rng(286)
    n = 400
    # large returns for the first 60 steps, small after: the padding zeros are far from the data
    returns = np.concatenate([rng.normal(0, 0.05, 60), rng.normal(0, 0.002, n - 60)])
    closes = 100.0 * np.exp(np.cumsum(returns))
    volumes = np.full(n, 1e6)
    ts = list(range(n))

    obs, valid_ts = _hmm._build_obs_matrix(
        ts,
        closes,
        volumes,
        vol_window=vol_window,
        momentum_window=momentum_window,
        vol_of_vol_window=vol_of_vol_window,
    )

    log_returns = np.log(closes[1:] / closes[:-1])
    start = valid_ts[0] - 1  # log-return index of the first emitted obs row
    first_clean = vol_window + vol_of_vol_window - 2
    assert start >= first_clean, (
        f"first obs row is log-return row {start}, but its vol_of_vol window reaches realized_vol "
        f"warmup padding until row {first_clean}"
    )
    realized = {
        i: float(np.std(log_returns[i - vol_window + 1 : i + 1]))
        for i in range(vol_window - 1, len(log_returns))
    }
    window_vols = [realized[i] for i in range(start - vol_of_vol_window + 1, start + 1)]
    assert obs[0, 3] == pytest.approx(float(np.std(window_vols)), rel=1e-12)
