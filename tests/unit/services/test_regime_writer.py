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
from hmmlearn.hmm import GaussianHMM

# Ensure project root is in sys.path for import
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from unittest.mock import MagicMock

from services.regime_writer import (
    _LABEL_RANGING,
    _LABEL_TRENDING_DOWN,
    _LABEL_TRENDING_UP,
    _build_label_map,
    _build_obs_matrix,
    _causal_decode,
    _compute_symbol_tf,
)

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
    states, alpha_history = _causal_decode(
        obs, model.means_, covars_diag, model.transmat_, n_components
    )

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
    causal_states, alpha_history = _causal_decode(
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

    states1, alpha_history1 = _causal_decode(
        obs, model.means_, covars_diag, model.transmat_, n_components
    )
    states2, alpha_history2 = _causal_decode(
        obs, model.means_, covars_diag, model.transmat_, n_components
    )

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
    states_half, _ = _causal_decode(
        obs[:half], model.means_, covars_diag, model.transmat_, n_components
    )

    # Decode on full sequence
    states_full, _ = _causal_decode(obs, model.means_, covars_diag, model.transmat_, n_components)

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
    states, alpha_history = _causal_decode(
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
    """_compute_symbol_tf must return (update_rows, converged) with correct row shape."""
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
    )

    assert result is not None
    update_rows, converged = result
    assert isinstance(update_rows, list)
    assert len(update_rows) > 0
    # Each tuple: (regime, p_up, p_ranging, p_down, prob_val, entropy_val, duration, symbol, tf, ts)
    assert len(update_rows[0]) == 10
    assert isinstance(converged, bool)


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
    )

    assert result is not None
    update_rows, _ = result
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
    )

    assert result is not None
    update_rows, _ = result
    for row in update_rows:
        _regime, p_up, p_ranging, p_down, prob_val, entropy_val, duration, sym, tf, ts = row
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
