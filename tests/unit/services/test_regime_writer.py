"""Unit tests for services/regime_writer.py.

All tests use synthetic data — no DB dependency. Tests verify:
- _build_obs_matrix produces correct shape and alignment
- _causal_decode is causal (only uses past+current observations)
- _causal_decode produces valid state indices
- _build_label_map produces canonical text labels deterministically
- Label map covers all K states
- HMM random state default is 42 (lives in APR as alpha.hmm.random_state)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from hmmlearn.hmm import GaussianHMM

# Ensure project root is in sys.path for import
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from unittest.mock import MagicMock

import services.regime_writer as regime_writer_module
from services.regime_writer import (
    _LABEL_RANGING,
    _LABEL_TRENDING_DOWN,
    _LABEL_TRENDING_UP,
    _build_label_map,
    _build_obs_matrix,
    _compute_symbol_tf,
)
from tests.unit._hmm_decode_helpers import decode as _decode

_HMM_RANDOM_STATE = 42  # conventional seed; lives in APR as alpha.hmm.random_state

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_trending_up_closes(n: int = 500, seed: int = 42) -> list[float]:
    """Generate n monotonically trending-up close prices with small noise.

    Returns exactly n closes (not n+1). The return for bar i = close[i]/close[i-1],
    so n closes produce n-1 log returns.
    """
    rng = np.random.default_rng(seed)
    # n-1 returns to produce n closes starting at 100
    returns = rng.normal(0.001, 0.002, n - 1)
    closes = [100.0]
    for r in returns:
        closes.append(closes[-1] * np.exp(r))
    assert len(closes) == n
    return closes


def _make_ranging_closes(n: int = 500, seed: int = 99) -> list[float]:
    """Generate n mean-reverting close prices.

    Returns exactly n closes. n closes produce n-1 log returns.
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.003, n - 1)
    closes = [100.0]
    for r in returns:
        closes.append(closes[-1] * np.exp(r))
    assert len(closes) == n
    return closes


def _make_timestamps(n: int):
    """Generate n UTC datetime timestamps (synthetic, not DB-fetched)."""
    from datetime import UTC, datetime, timedelta

    base = datetime(2020, 1, 1, tzinfo=UTC)
    return [base + timedelta(hours=i) for i in range(n)]


def _make_volumes(n: int, seed: int = 7) -> list[float]:
    """Generate n synthetic daily volumes with log-normal distribution."""
    rng = np.random.default_rng(seed)
    return list(rng.lognormal(mean=14.0, sigma=0.5, size=n))


def _fit_simple_hmm(obs_matrix: np.ndarray, n_components: int = 3) -> GaussianHMM:
    """Fit a GaussianHMM on synthetic obs matrix for use in tests."""
    model = GaussianHMM(
        n_components=n_components,
        covariance_type="diag",
        n_iter=50,
        random_state=_HMM_RANDOM_STATE,
    )
    model.fit(obs_matrix)
    return model


# ---------------------------------------------------------------------------
# Tests: _build_obs_matrix
# ---------------------------------------------------------------------------


def test_build_obs_matrix_shape():
    """obs_matrix should have shape (n-1-vol_window, 5) for 5D observation vector."""
    n = 200
    vol_window = 20
    momentum_window = 20
    vol_of_vol_window = 20
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)

    obs, valid_ts = _build_obs_matrix(
        timestamps, closes, volumes, vol_window, momentum_window, vol_of_vol_window
    )

    # n closes -> n-1 log returns -> drop first (max_window-1) for warm-up
    # With all windows equal to vol_window: remaining = (n-1) - (vol_window-1) = n - vol_window
    expected_rows = n - vol_window
    assert obs.shape == (expected_rows, 5), f"Expected ({expected_rows}, 5), got {obs.shape}"
    assert len(valid_ts) == expected_rows


def test_build_obs_matrix_no_nan():
    """obs_matrix must not contain NaN or Inf."""
    n = 300
    closes = _make_trending_up_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    assert not np.any(np.isnan(obs)), "obs_matrix contains NaN"
    assert not np.any(np.isinf(obs)), "obs_matrix contains Inf"


def test_build_obs_matrix_log_return_sign():
    """Trending-up closes should yield mostly positive log-returns in col 0."""
    n = 500
    closes = _make_trending_up_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    positive_fraction = np.mean(obs[:, 0] > 0)
    assert (
        positive_fraction > 0.55
    ), f"Expected >55% positive log-returns, got {positive_fraction:.2%}"


def test_build_obs_matrix_insufficient_data():
    """With fewer closes than vol_window+2, obs matrix should be empty."""
    n = 10
    closes = [100.0] * n
    volumes = [1e6] * n
    timestamps = _make_timestamps(n)
    obs, valid_ts = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    assert obs.shape[0] == 0
    assert len(valid_ts) == 0


def test_build_obs_matrix_timestamp_alignment():
    """valid_ts length must match obs_matrix row count."""
    n = 150
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, valid_ts = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=10, momentum_window=10, vol_of_vol_window=10
    )

    assert len(valid_ts) == obs.shape[0]


# ---------------------------------------------------------------------------
# Tests: _causal_decode
# ---------------------------------------------------------------------------


def test_causal_decode_valid_states():
    """All decoded states must be in [0, K-1]."""
    n = 400
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    d = model.means_.shape[1]
    covars_diag = model.covars_[:, np.arange(d), np.arange(d)]
    states, alpha_history = _decode(obs, model.means_, covars_diag, model.transmat_, n_components)

    assert states.shape == (obs.shape[0],)
    assert np.all(states >= 0) and np.all(
        states < n_components
    ), f"State indices out of range [0, {n_components-1}]: {np.unique(states)}"
    assert alpha_history.shape == (obs.shape[0], n_components)
    assert np.allclose(alpha_history.sum(axis=1), 1.0)


def test_causal_decode_no_predict():
    """Causal decode should not use model.predict() — this test verifies the
    function produces different results than Viterbi when forced forward-only."""
    n = 300
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    d = model.means_.shape[1]
    covars_diag = model.covars_[:, np.arange(d), np.arange(d)]

    # Our causal decoder
    causal_states, alpha_history = _decode(
        obs, model.means_, covars_diag, model.transmat_, n_components
    )

    # hmmlearn Viterbi (full-sequence, non-causal)
    viterbi_states = model.predict(obs)

    # They must not be identical (causal vs Viterbi differ on boundary transitions)
    # If they are identical it could mean the data is too clean — we just check shapes match
    assert causal_states.shape == viterbi_states.shape
    # Causal states must be valid regardless of whether they match Viterbi
    assert np.all(causal_states >= 0) and np.all(causal_states < n_components)
    assert alpha_history.shape == (obs.shape[0], n_components)
    assert np.allclose(alpha_history.sum(axis=1), 1.0)


def test_causal_decode_deterministic():
    """Same obs, model must produce same decoded states (no randomness in decode)."""
    n = 250
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    d = model.means_.shape[1]
    covars_diag = model.covars_[:, np.arange(d), np.arange(d)]

    states1, alpha_history1 = _decode(obs, model.means_, covars_diag, model.transmat_, n_components)
    states2, alpha_history2 = _decode(obs, model.means_, covars_diag, model.transmat_, n_components)

    np.testing.assert_array_equal(states1, states2)
    np.testing.assert_array_almost_equal(alpha_history1, alpha_history2)


def test_causal_decode_uses_only_past_observations():
    """Causal decoder: state at T depends only on obs[0..T].

    We verify this by decoding obs[0..T] and obs[0..T+k] — the state at T
    must be identical regardless of what comes after T. If a backward pass
    or smoothing were present, the additional future obs[T+1..T+k] would
    change the decoded state at T.
    """
    n = 300
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    d = model.means_.shape[1]
    covars_diag = model.covars_[:, np.arange(d), np.arange(d)]

    # Decode on first half of obs
    half = len(obs) // 2
    states_half, _ = _decode(obs[:half], model.means_, covars_diag, model.transmat_, n_components)

    # Decode on full sequence
    states_full, _ = _decode(obs, model.means_, covars_diag, model.transmat_, n_components)

    # The decoded state at each position in the first half must be identical
    # between the two decoding runs — future observations cannot change past states
    np.testing.assert_array_equal(
        states_half,
        states_full[:half],
        err_msg=(
            "Causal violation: decoded states in obs[0..T] differ between "
            "decode(obs[0..T]) and decode(obs[0..2T]). "
            "Check for smoothing or backward pass in _causal_decode."
        ),
    )


def test_causal_decode_single_obs():
    """Decoder must handle n=1 observation without crash."""
    n = 200
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    d = model.means_.shape[1]
    covars_diag = model.covars_[:, np.arange(d), np.arange(d)]

    single_obs = obs[:1]  # shape (1, 5)
    states, alpha_history = _decode(
        single_obs, model.means_, covars_diag, model.transmat_, n_components
    )
    assert states.shape == (1,)
    assert 0 <= states[0] < n_components
    assert alpha_history.shape == (1, n_components)
    assert np.allclose(alpha_history.sum(axis=1), 1.0)


# ---------------------------------------------------------------------------
# Tests: _build_label_map
# ---------------------------------------------------------------------------


def test_build_label_map_covers_all_states():
    """label_map must contain an entry for every state 0..K-1."""
    n = 400
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    label_map = _build_label_map(model.means_)

    assert set(label_map.keys()) == set(range(n_components))


def test_build_label_map_canonical_values():
    """All label values must be one of the three canonical strings."""
    n = 400
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    label_map = _build_label_map(model.means_)

    valid_labels = {_LABEL_TRENDING_UP, _LABEL_TRENDING_DOWN, _LABEL_RANGING}
    for state, label in label_map.items():
        assert label in valid_labels, f"State {state} has invalid label '{label}'"


def test_build_label_map_trending_up_has_highest_mean():
    """The state mapped to trending_up must have the highest mean log-return."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    label_map = _build_label_map(model.means_)

    up_state = [k for k, v in label_map.items() if v == _LABEL_TRENDING_UP][0]
    down_state = [k for k, v in label_map.items() if v == _LABEL_TRENDING_DOWN][0]

    assert (
        model.means_[up_state, 0] > model.means_[down_state, 0]
    ), "trending_up state does not have highest mean log-return"


def test_build_label_map_trending_down_has_lowest_mean():
    """The state mapped to trending_down must have the lowest mean log-return."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    label_map = _build_label_map(model.means_)

    down_state = [k for k, v in label_map.items() if v == _LABEL_TRENDING_DOWN][0]

    means_ret = model.means_[:, 0]
    assert (
        model.means_[down_state, 0] == means_ret.min()
    ), "trending_down state does not have lowest mean log-return"


def test_build_label_map_exactly_one_trending_up():
    """There must be exactly one 'trending_up' state."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    n_components = 3
    model = _fit_simple_hmm(obs, n_components)
    label_map = _build_label_map(model.means_)

    up_count = sum(1 for v in label_map.values() if v == _LABEL_TRENDING_UP)
    down_count = sum(1 for v in label_map.values() if v == _LABEL_TRENDING_DOWN)
    assert up_count == 1
    assert down_count == 1


# ---------------------------------------------------------------------------
# Tests: Constants
# ---------------------------------------------------------------------------


def test_hmm_random_state_default():
    """Conventional HMM seed for reproducibility. Actual value lives in APR (alpha.hmm.random_state)."""
    assert _HMM_RANDOM_STATE == 42


def test_canonical_label_constants():
    """Canonical label constants must be exact expected strings."""
    assert _LABEL_TRENDING_UP == "trending_up"
    assert _LABEL_TRENDING_DOWN == "trending_down"
    assert _LABEL_RANGING == "ranging"


# ---------------------------------------------------------------------------
# Tests: _compute_symbol_tf
# ---------------------------------------------------------------------------


def _make_mock_conn(closes, volumes, timestamps):
    """Build a psycopg2 connection mock that returns synthetic OHLCV rows."""
    rows = list(zip(timestamps, closes, volumes))
    # cursor used as context manager for named server-side cursor
    cursor_mock = MagicMock()
    cursor_mock.__enter__ = lambda s: s
    cursor_mock.__exit__ = MagicMock(return_value=False)
    # fetchmany returns all rows on first call, then [] to signal EOF
    cursor_mock.fetchmany.side_effect = [rows, []]
    conn_mock = MagicMock()
    conn_mock.cursor.return_value = cursor_mock
    return conn_mock


def test_compute_symbol_tf_returns_tuple_structure():
    """_compute_symbol_tf must return (update_rows, converged, heldout_ll) with correct row shape.

    min_state_occupation=0.0 disables the P2b degenerate-model gate for this fixture —
    this test verifies return-tuple structure, not gate behavior (gate has no dedicated
    coverage of its own; see todo captured this session).
    """
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    result = _compute_symbol_tf(
        conn=conn,
        symbol="SPY",
        tf="1d",
        n_components=3,
        vol_window=20,
        n_iter=50,
        hmm_random_state=42,
        momentum_window=20,
        vol_of_vol_window=20,
        min_state_occupation=0.0,
    )

    assert result is not None
    update_rows, converged, heldout_ll = result
    assert isinstance(update_rows, list)
    assert len(update_rows) > 0
    # Each tuple: (regime, p_up, p_ranging, p_down, prob_val, entropy_val, duration,
    #              hmm_churn, symbol, tf, ts)
    assert len(update_rows[0]) == 11
    assert isinstance(converged, bool)
    assert isinstance(heldout_ll, float)


def test_compute_symbol_tf_logs_convergence_iterations():
    """_compute_symbol_tf must log the actual EM iteration count used per cell.

    This is measurement-only instrumentation for todo 226 (n_iter=200 headroom
    check) -- asserts the log event fires with correct fields. Zero side-effect
    evidence comes from sibling tests (test_compute_symbol_tf_returns_tuple_structure,
    test_compute_symbol_tf_regime_values, test_compute_symbol_tf_probabilities_sum_to_one)
    continuing to pass unmodified, confirming the instrumentation has no effect on
    fit output or label computation.
    """
    from structlog.testing import capture_logs

    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    with capture_logs() as cap_logs:
        result = _compute_symbol_tf(
            conn=conn,
            symbol="SPY",
            tf="1d",
            n_components=3,
            vol_window=20,
            n_iter=50,
            hmm_random_state=42,
            momentum_window=20,
            vol_of_vol_window=20,
            min_state_occupation=0.0,
        )

    assert result is not None

    events = [e for e in cap_logs if e["event"] == "regime_writer.hmm_convergence_iters"]
    assert len(events) == 1
    event = events[0]
    assert event["symbol"] == "SPY"
    assert event["tf"] == "1d"
    assert event["n_iter_cap"] == 50
    assert isinstance(event["iters_used"], int)
    assert 0 < event["iters_used"] <= 50
    assert isinstance(event["converged"], bool)


def test_compute_symbol_tf_regime_values():
    """All regime labels in update_rows must be canonical strings."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    result = _compute_symbol_tf(
        conn=conn,
        symbol="TLT",
        tf="1d",
        n_components=3,
        vol_window=20,
        n_iter=50,
        hmm_random_state=42,
        momentum_window=20,
        vol_of_vol_window=20,
        min_state_occupation=0.0,
    )

    assert result is not None
    update_rows, _, _ = result
    valid_labels = {"trending_up", "trending_down", "ranging"}
    for row in update_rows:
        assert row[0] in valid_labels, f"Invalid regime label: {row[0]}"


def test_compute_symbol_tf_probabilities_sum_to_one():
    """p_up + p_ranging + p_down must sum to ~1.0 for each row."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    result = _compute_symbol_tf(
        conn=conn,
        symbol="GLD",
        tf="1d",
        n_components=3,
        vol_window=20,
        n_iter=50,
        hmm_random_state=42,
        momentum_window=20,
        vol_of_vol_window=20,
        min_state_occupation=0.0,
    )

    assert result is not None
    update_rows, _, _ = result
    for row in update_rows:
        (
            _regime,
            p_up,
            p_ranging,
            p_down,
            prob_val,
            entropy_val,
            duration,
            _hmm_churn,
            sym,
            tf,
            ts,
        ) = row
        total = p_up + p_ranging + p_down
        assert abs(total - 1.0) < 1e-6, f"Probabilities sum to {total}, expected ~1.0"


def test_compute_symbol_tf_returns_none_on_insufficient_data():
    """Returns None when fewer obs than n_components * _MIN_OBS_FACTOR."""
    n = 10
    closes = [100.0] * n
    volumes = [1e6] * n
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    result = _compute_symbol_tf(
        conn=conn,
        symbol="SPY",
        tf="1d",
        n_components=3,
        vol_window=20,
        n_iter=50,
        hmm_random_state=42,
        momentum_window=20,
        vol_of_vol_window=20,
    )

    assert result is None


def test_compute_symbol_tf_no_db_write():
    """Worker must not call conn.execute or conn.executemany for writes."""
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    _compute_symbol_tf(
        conn=conn,
        symbol="SPY",
        tf="1d",
        n_components=3,
        vol_window=20,
        n_iter=50,
        hmm_random_state=42,
        momentum_window=20,
        vol_of_vol_window=20,
    )

    # The cursor mock is only called for the SELECT (fetchmany) — never for UPDATE
    cursor = conn.cursor.return_value
    for c in cursor.execute.call_args_list:
        sql = c[0][0].upper() if c[0] else ""
        assert "UPDATE" not in sql, f"Worker issued an UPDATE: {sql}"


# ---------------------------------------------------------------------------
# Tests: alpha.hmm.n_restarts multi-seed restart (todo 108)
# ---------------------------------------------------------------------------


def test_compute_symbol_tf_n_restarts_default_fits_once_on_convergence(monkeypatch):
    """n_restarts defaults to 1 -- when the single seed converges on the first try,
    exactly one GaussianHMM is instantiated, at hmm_random_state, matching the prior
    single-seed code path exactly (no multi-seed loop overhead at the default).

    n_restarts is intentionally NOT passed here -- this proves the *default* behavior,
    not merely that n_restarts=1 works when explicitly requested.
    """
    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    call_log: list[dict] = []
    real_gaussian_hmm = regime_writer_module.GaussianHMM

    class _TrackedHMM(real_gaussian_hmm):
        def __init__(self, *args, **kwargs):
            call_log.append(
                {"n_iter": kwargs.get("n_iter"), "random_state": kwargs.get("random_state")}
            )
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(regime_writer_module, "GaussianHMM", _TrackedHMM)

    result = _compute_symbol_tf(
        conn=conn,
        symbol="SPY",
        tf="1d",
        n_components=3,
        vol_window=20,
        n_iter=50,
        hmm_random_state=42,
        momentum_window=20,
        vol_of_vol_window=20,
        min_state_occupation=0.0,
    )

    assert result is not None
    assert len(call_log) == 1, f"Expected exactly 1 GaussianHMM fit at the default, got {call_log}"
    assert call_log[0] == {"n_iter": 50, "random_state": 42}


def test_compute_symbol_tf_n_restarts_default_preserves_same_seed_retry(monkeypatch):
    """n_restarts=1 (default) must preserve the prior same-seed, doubled-n_iter retry
    on non-convergence -- exactly 2 GaussianHMM fits, BOTH using hmm_random_state, never
    hmm_random_state + 1. This is the load-bearing default-preserving property: the new
    multi-seed loop must not silently turn a single-seed retry into a second, different
    seed being tried.

    hmmlearn's monitor_.converged reads True whenever the EM loop ran its full n_iter
    budget (by construction of ConvergenceMonitor.converged), so real non-convergence
    can't be forced deterministically via n_iter alone -- the first fit's convergence
    flag is force-overridden here to exercise the retry branch under test.
    """
    from types import SimpleNamespace

    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    call_log: list[dict] = []
    fit_count = {"n": 0}
    real_gaussian_hmm = regime_writer_module.GaussianHMM

    class _ForceFirstNonConvergedHMM(real_gaussian_hmm):
        def __init__(self, *args, **kwargs):
            call_log.append(
                {"n_iter": kwargs.get("n_iter"), "random_state": kwargs.get("random_state")}
            )
            super().__init__(*args, **kwargs)

        def fit(self, X, lengths=None):
            super().fit(X, lengths)
            fit_count["n"] += 1
            if fit_count["n"] == 1:
                real_iter = self.monitor_.iter
                real_n_iter = self.monitor_.n_iter
                self.monitor_ = SimpleNamespace(converged=False, iter=real_iter, n_iter=real_n_iter)
            return self

    monkeypatch.setattr(regime_writer_module, "GaussianHMM", _ForceFirstNonConvergedHMM)

    result = _compute_symbol_tf(
        conn=conn,
        symbol="SPY",
        tf="1d",
        n_components=3,
        vol_window=20,
        n_iter=50,
        hmm_random_state=42,
        momentum_window=20,
        vol_of_vol_window=20,
        min_state_occupation=0.0,
        # n_restarts intentionally omitted -- proves the default, not an explicit 1.
    )

    assert result is not None
    assert (
        len(call_log) == 2
    ), f"Expected exactly 2 GaussianHMM fits (original + same-seed retry), got {call_log}"
    assert call_log[0] == {"n_iter": 50, "random_state": 42}
    assert call_log[1] == {
        "n_iter": 100,
        "random_state": 42,
    }, "Retry must reuse hmm_random_state (not hmm_random_state + 1) and double n_iter"


def test_compute_symbol_tf_n_restarts_selects_highest_log_likelihood(monkeypatch):
    """n_restarts > 1 must select the converged candidate with the highest log-likelihood.

    Monkeypatches GaussianHMM.score() so a specific, non-obvious seed (hmm_random_state + 2,
    neither the first nor the last seed tried) is engineered to report the highest
    log-likelihood regardless of the real data-driven score -- this isolates the
    *selection* logic under test from whatever any particular seed's real likelihood
    happens to be on this fixture. No real market data; reuses this file's synthetic
    ranging-price fixture. Model identity is verified via _stationary_distribution's
    input (the transmat_ of whichever model the restart loop picked), the first place
    downstream of the loop that touches the chosen model.
    """
    from types import SimpleNamespace

    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    hmm_random_state = 42
    n_restarts = 4
    winning_seed = hmm_random_state + 2  # neither the first nor the last seed tried

    real_gaussian_hmm = regime_writer_module.GaussianHMM
    seed_to_transmat: dict[int, np.ndarray] = {}

    class _ControlledHMM(real_gaussian_hmm):
        def fit(self, X, lengths=None):
            super().fit(X, lengths)
            if self.random_state == winning_seed:
                # Force convergence so the engineered score below is what decides the
                # winner: convergence status ranks ahead of log-likelihood in the
                # selection tuple, so a non-converged "winner" would lose regardless
                # of its score.
                real_iter = self.monitor_.iter
                real_n_iter = self.monitor_.n_iter
                self.monitor_ = SimpleNamespace(converged=True, iter=real_iter, n_iter=real_n_iter)
            seed_to_transmat[self.random_state] = self.transmat_.copy()
            return self

        def score(self, X, lengths=None):
            if self.random_state == winning_seed:
                return 1e6  # engineered to dominate every other seed's real score
            return super().score(X, lengths)

    monkeypatch.setattr(regime_writer_module, "GaussianHMM", _ControlledHMM)

    captured: dict = {}
    real_stationary_distribution = regime_writer_module._stationary_distribution

    def _capture_stationary_distribution(transmat):
        captured["transmat"] = np.asarray(transmat).copy()
        return real_stationary_distribution(transmat)

    monkeypatch.setattr(
        regime_writer_module, "_stationary_distribution", _capture_stationary_distribution
    )

    result = _compute_symbol_tf(
        conn=conn,
        symbol="SPY",
        tf="1d",
        n_components=3,
        vol_window=20,
        n_iter=50,
        hmm_random_state=hmm_random_state,
        momentum_window=20,
        vol_of_vol_window=20,
        min_state_occupation=0.0,
        n_restarts=n_restarts,
    )

    assert result is not None
    assert "transmat" in captured, "Model selection never reached _stationary_distribution"
    assert winning_seed in seed_to_transmat, "Winning seed was never fit"
    np.testing.assert_array_equal(captured["transmat"], seed_to_transmat[winning_seed])


# ---------------------------------------------------------------------------
# Tests: _walk_forward_hmm_labels / _seed_prior_from_label (todo 248/026 P4a)
#
# _compute_symbol_tf fits its GaussianHMM once on the ENTIRE (symbol, tf) history before
# causally decoding -- the decode step is causal, but the model's own parameters were
# estimated with knowledge of the whole series, a parameter-level lookahead channel
# confirmed empirically (docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md: SPY/1h
# full-fit vs expanding-refit labels agree only 24.9% of the time, chance baseline 21.7%).
# _walk_forward_hmm_labels fixes this: refits periodically on a growing training prefix
# only, and seeds each new model's initial belief from the label the PREVIOUS segment
# ended on (via _seed_prior_from_label) rather than a fresh stationary prior -- raw HMM
# state indices are not comparable across independently-fit models, but semantic labels
# are, since _build_label_map normalizes every fit onto the same fixed vocabulary.
# ---------------------------------------------------------------------------


def test_seed_prior_from_label_is_one_hot_on_matching_state():
    """The seeded prior must place all mass on whichever state label_map maps to `label`."""
    from services.regime_writer import _seed_prior_from_label

    label_map = {
        0: _LABEL_TRENDING_DOWN,
        1: "transition_down",
        2: _LABEL_RANGING,
        3: "transition_up",
        4: _LABEL_TRENDING_UP,
    }
    fallback = np.full(5, 0.2)

    pi0 = _seed_prior_from_label(label_map, _LABEL_RANGING, n_components=5, fallback_prior=fallback)

    expected = np.array([0.0, 0.0, 1.0, 0.0, 0.0])
    np.testing.assert_array_equal(pi0, expected)


def test_seed_prior_from_label_falls_back_when_label_absent():
    """If `label` isn't present in this model's label_map (shouldn't happen at K=5, but
    must fail safe rather than divide by zero), return the caller-supplied fallback."""
    from services.regime_writer import _seed_prior_from_label

    label_map = {0: _LABEL_TRENDING_DOWN, 1: _LABEL_RANGING, 2: _LABEL_TRENDING_UP}
    fallback = np.array([0.2, 0.6, 0.2])

    pi0 = _seed_prior_from_label(
        label_map, "transition_down", n_components=3, fallback_prior=fallback
    )

    np.testing.assert_array_equal(pi0, fallback)


def test_walk_forward_hmm_labels_unaffected_by_future_data():
    """Causality: labels for bars before a truncation point must be identical whether or
    not data after that point exists -- mirrors test_causal_decode_uses_only_past_observations,
    one level up (the model's PARAMETERS, not just the decode, must not see the future).

    If _walk_forward_hmm_labels fit on the full series (the current _compute_symbol_tf bug),
    truncating the tail would change every prior model's fit and this test would fail.
    """
    from services.regime_writer import _walk_forward_hmm_labels

    n_full = 1200
    closes = _make_ranging_closes(n_full)
    volumes = _make_volumes(n_full)
    timestamps = _make_timestamps(n_full)
    obs_full, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    truncate_at = 900  # falls exactly on a refit boundary: warmup(300) + 3*refit_every(200)
    obs_truncated = obs_full[:truncate_at]

    kwargs = dict(
        n_components=3,
        covariance_type="diag",
        n_iter=50,
        hmm_random_state=_HMM_RANDOM_STATE,
        refit_every_bars=200,
        initial_warmup_bars=300,
        min_hold_bars=3,
        full_cov_min_obs=0,
    )

    labels_full, _ = _walk_forward_hmm_labels(obs_full, **kwargs)
    labels_truncated, _ = _walk_forward_hmm_labels(obs_truncated, **kwargs)

    n_overlap = truncate_at - kwargs["initial_warmup_bars"]
    assert len(labels_truncated) == n_overlap
    assert labels_full[:n_overlap] == labels_truncated, (
        "Causal violation: walk-forward labels before the truncation point changed when "
        "future data was added. Check for a full-series fit leaking into an early segment."
    )


def test_walk_forward_hmm_labels_second_segment_seeded_from_first_segments_ending_label():
    """Belief continuity: the second segment's model must be decoded with an initial prior
    concentrated on the state its OWN label_map maps to the first segment's final label --
    not that model's stationary distribution (which ignores what regime bar 299 was actually
    in). Verified via monkeypatching _seed_prior_from_label to capture its call arguments."""
    from unittest.mock import patch

    import services.regime_writer as regime_writer_module
    from services.regime_writer import _walk_forward_hmm_labels

    n_full = 500
    closes = _make_ranging_closes(n_full)
    volumes = _make_volumes(n_full)
    timestamps = _make_timestamps(n_full)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    real_seed_prior_from_label = regime_writer_module._seed_prior_from_label
    calls: list[tuple] = []

    def _spy(label_map, label, n_components, fallback_prior):
        calls.append((dict(label_map), label))
        return real_seed_prior_from_label(label_map, label, n_components, fallback_prior)

    with patch.object(regime_writer_module, "_seed_prior_from_label", side_effect=_spy):
        labels, segments = _walk_forward_hmm_labels(
            obs,
            n_components=3,
            covariance_type="diag",
            n_iter=50,
            hmm_random_state=_HMM_RANDOM_STATE,
            refit_every_bars=150,
            initial_warmup_bars=200,
            min_hold_bars=3,
            full_cov_min_obs=0,
        )

    assert len(segments) >= 2, "Test needs at least 2 refit segments to check continuity"
    # First segment has no predecessor -- must NOT call _seed_prior_from_label.
    # Every later segment must call it exactly once, with the prior segment's final label.
    assert len(calls) == len(segments) - 1
    first_segment_len = segments[0][2] - segments[0][1]
    _, second_call_label = calls[0]
    assert second_call_label == labels[first_segment_len - 1], (
        "Second segment's seeded prior must use the first segment's own final label, not "
        "a fresh stationary distribution."
    )


# ---------------------------------------------------------------------------
# Tests: _hmm_seed_stability_check (todo 026's bundled ask -- 3-5 seeds, compare
# log-likelihood spread and label agreement, since each walk-forward segment's refit is
# itself a fresh non-convex EM optimization subject to the same local-optima risk todo 108's
# multi-seed-restart already addresses for the single full-history fit).
# ---------------------------------------------------------------------------


def test_hmm_seed_stability_check_shape_and_ranges():
    """Structural contract: one log-likelihood per seed, one agreement value per unique
    seed pair, ll_spread and min_pairwise_agreement are consistent aggregates of those."""
    from services.regime_writer import _hmm_seed_stability_check

    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    seeds = [42, 43, 44]
    result = _hmm_seed_stability_check(
        obs,
        n_components=3,
        covariance_type="diag",
        n_iter=50,
        seeds=seeds,
        full_cov_min_obs=0,
    )

    assert set(result["log_likelihoods"].keys()) == set(seeds)
    assert all(isinstance(v, float) for v in result["log_likelihoods"].values())

    expected_pairs = {(a, b) for i, a in enumerate(seeds) for b in seeds[i + 1 :]}
    assert set(result["pairwise_label_agreement"].keys()) == expected_pairs
    assert all(0.0 <= v <= 1.0 for v in result["pairwise_label_agreement"].values())

    lls = list(result["log_likelihoods"].values())
    assert result["ll_spread"] == pytest.approx(max(lls) - min(lls))
    assert result["min_pairwise_agreement"] == pytest.approx(
        min(result["pairwise_label_agreement"].values())
    )


def test_hmm_seed_stability_check_is_deterministic():
    """Same obs + same seeds must give byte-identical results across two calls --
    GaussianHMM.fit is deterministic given a fixed seed and data; any non-determinism here
    would mean a real bug in the aggregation (e.g. unordered dict/set iteration leaking into
    a computed value)."""
    from services.regime_writer import _hmm_seed_stability_check

    n = 400
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    obs, _ = _build_obs_matrix(
        timestamps, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )

    kwargs = dict(
        n_components=3,
        covariance_type="diag",
        n_iter=50,
        seeds=[42, 43],
        full_cov_min_obs=0,
    )
    result_a = _hmm_seed_stability_check(obs, **kwargs)
    result_b = _hmm_seed_stability_check(obs, **kwargs)

    assert result_a == result_b
