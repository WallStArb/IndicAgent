"""Exact-equality tests for the vectorized regime kernel internals (186-13 review, D7).

Each optimized function is compared with the loop it replaced, kept here as the slow reference.
Equality is exact (bits for floats), never approximate: the regime golden is bit-identical and
these pin the pieces it runs through, on inputs the golden does not reach (single-state runs,
min_hold beyond the series, windows longer than the series).
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.features.kernels import _hmm


def _reference_smooth_states(raw_states: np.ndarray, min_hold: int) -> np.ndarray:
    """The per-row loop `_smooth_states` used before it was vectorized."""
    if min_hold <= 1:
        return raw_states.copy()
    n = len(raw_states)
    smoothed = raw_states.copy()
    current = int(raw_states[0])
    for t in range(1, n):
        if t < min_hold:
            smoothed[t] = current
            continue
        window = raw_states[t - min_hold + 1 : t + 1]
        if np.all(window == raw_states[t]):
            current = int(raw_states[t])
        smoothed[t] = current
    return smoothed


def _reference_churn(labels, churn_window: int) -> np.ndarray:
    """The per-row np.mean loop `_compute_hmm_churn` used before it used cumulative sums."""
    n = len(labels)
    if n == 0:
        return np.zeros(0, dtype=float)
    labels_arr = np.asarray(labels, dtype=object)
    changes = np.zeros(n, dtype=float)
    if n > 1:
        changes[1:] = (labels_arr[1:] != labels_arr[:-1]).astype(float)
    churn = np.zeros(n, dtype=float)
    for i in range(n):
        window_start = max(0, i - churn_window + 1)
        churn[i] = float(np.mean(changes[window_start : i + 1]))
    return churn


def _state_sequences():
    """Random walks with runs of every length: sticky, flappy, one-state and two-state."""
    rng = np.random.default_rng(20260930)
    cases = [np.zeros(50, dtype=np.int64), np.array([2], dtype=np.int64)]
    for n in (2, 3, 4, 7, 40, 400, 5000):
        for stay in (0.2, 0.7, 0.95, 0.995):
            for k in (2, 3, 5):
                states = np.empty(n, dtype=np.int64)
                states[0] = rng.integers(0, k)
                for t in range(1, n):
                    states[t] = states[t - 1] if rng.random() < stay else rng.integers(0, k)
                cases.append(states)
    return cases


@pytest.mark.parametrize("min_hold", [0, 1, 2, 3, 5, 10, 100])
def test_smooth_states_equals_the_loop(min_hold):
    for raw in _state_sequences():
        want = _reference_smooth_states(raw, min_hold)
        got = _hmm._smooth_states(raw, min_hold)
        assert got.dtype == want.dtype
        assert np.array_equal(got, want), (min_hold, raw[:20])
        assert got is not raw


def test_smooth_states_does_not_alias_its_input():
    raw = np.array([0, 1, 1, 1, 0, 0, 0], dtype=np.int64)
    before = raw.copy()
    _hmm._smooth_states(raw, 3)
    assert np.array_equal(raw, before)


@pytest.mark.parametrize("window", [1, 2, 3, 10, 60, 10_000])
def test_churn_equals_the_loop_bit_for_bit(window):
    rng = np.random.default_rng(window)
    for n in (0, 1, 2, 5, 61, 700, 3000):
        for stay in (0.3, 0.9, 0.99):
            labels = [0]
            for _ in range(n - 1):
                labels.append(labels[-1] if rng.random() < stay else int(rng.integers(0, 5)))
            labels = labels[:n]
            for shape in (labels, np.array(labels, dtype=np.int64), [f"s{x}" for x in labels]):
                want = _reference_churn(shape, window)
                got = _hmm._compute_hmm_churn(shape, window)
                assert got.dtype == want.dtype and got.shape == want.shape
                assert np.array_equal(got.view(np.uint64), want.view(np.uint64)), (n, window)


def test_non_converged_segment_skips_the_training_slice_decode_and_keeps_its_verdict(monkeypatch):
    """n_iter=1 never converges (the retry at 2 does not either). The gate refuses such a fit
    from the slice length alone, so the training-slice decode is not run; the verdict is the
    one the decode would have produced."""
    from tests.unit.intelligence.regime_kernel_fixtures import make_synthetic_regime_bars

    bars = make_synthetic_regime_bars(1400, 42)
    obs, _ = _hmm._build_obs_matrix(
        list(range(1400)), bars["close"], bars["volume"], vol_window=20, momentum_window=20,
        vol_of_vol_window=20,
    )  # fmt: skip
    calls = []
    real = _hmm._alpha_pass_jit

    def counting(log_emit, log_a, pi0):
        calls.append(len(log_emit))
        return real(log_emit, log_a, pi0)

    monkeypatch.setattr(_hmm, "_alpha_pass_jit", counting)
    segments = _hmm._walk_forward_hmm_full(
        obs, 3, "full", 1, 42, 300, 600, 3, 500, 0.05, min_obs_factor=50
    )
    assert len(segments) >= 2
    for seg in segments:
        assert seg["converged"] is False and seg["is_degenerate"] is True
        assert seg["gate_info"] == {
            "reason": "not_converged",
            "n_obs": seg["seg_start"],
            "gate_basis": "training_slice",
        }
    assert calls == [seg["seg_end"] - seg["seg_start"] for seg in segments]
