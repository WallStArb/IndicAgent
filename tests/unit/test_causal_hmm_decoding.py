"""Unit test: the causal HMM forward filter is causal.

GaussianHMM.predict() is full-sequence Viterbi and uses future observations. _decode() is
the causal forward filter (alpha pass only): at timestep t it uses ONLY obs[0..t]. The
gating property is prefix invariance: decoding obs[0..T] and obs[0..N] gives the same states
and the same filtered probabilities at every t <= T.

An earlier test asserted that causal and Viterbi labels differ; on cleanly separated regimes
they rightly agree, so that test only passed when the fit degenerated and skipped (todo 677).
It is removed; prefix invariance of the probabilities is the stricter check.

No DB, no Kafka. Pure numpy + hmmlearn.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from hmmlearn.hmm import GaussianHMM

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.features.kernels._hmm import _log_emit_diag, _stationary_distribution
from src.intelligence.hmm_jit import alpha_pass_jit
from tests.unit._hmm_decode_helpers import decode as _decode

_SEED = 42


def _make_regime_switch_obs(n_bars: int = 30, switch_at: int = 20, seed: int = _SEED) -> np.ndarray:
    """Build a deterministic observation sequence with a sharp regime switch.

    First switch_at bars: strongly positive log-returns (trending-up regime).
    Remaining bars: strongly negative log-returns (trending-down regime).

    Two-dimensional: [log_return, realized_vol], in percent. In raw units the per-regime
    variances (about 1e-6) sit far below hmmlearn's min_covar floor (1e-3), the two states
    cannot separate and the 2-state fit degenerates to one (todo 677); in percent they do.
    """
    rng = np.random.default_rng(seed)
    obs = np.zeros((n_bars, 2))
    # First segment: positive returns, low vol
    obs[:switch_at, 0] = rng.normal(0.005, 0.001, switch_at)
    obs[:switch_at, 1] = rng.uniform(0.001, 0.003, switch_at)
    # Second segment: negative returns, higher vol
    obs[switch_at:, 0] = rng.normal(-0.008, 0.001, n_bars - switch_at)
    obs[switch_at:, 1] = rng.uniform(0.004, 0.008, n_bars - switch_at)
    return obs * 100.0


class TestCausalVsViterbi:
    """The causal forward filter is prefix-invariant on regime-switch data."""

    def setup_method(self):
        """Fit a 2-component HMM on a three-segment sequence (150 up, 50 down, 60 up)."""
        # up, down, then up again: with one switch the fitted chain is absorbing, its stationary
        # prior puts no mass on the first regime and bar 0 decodes to the wrong state
        self.obs = np.vstack(
            [
                _make_regime_switch_obs(n_bars=200, switch_at=150),
                _make_regime_switch_obs(60, 60, seed=_SEED + 1),
            ]
        )
        self.n_components = 2
        model = GaussianHMM(
            n_components=self.n_components,
            covariance_type="diag",
            n_iter=100,
            random_state=_SEED,
        )
        model.fit(self.obs)
        self.model = model
        # a degenerate or muddled fit would make every check below trivial (todo 677): Viterbi
        # must recover the three known segments, up to the label permutation
        truth = np.r_[np.zeros(150), np.ones(50), np.zeros(60)].astype(int)
        viterbi = model.predict(self.obs)
        agreement = max((viterbi == truth).mean(), (viterbi == 1 - truth).mean())
        assert agreement >= 0.95, f"the fit does not recover the regimes ({agreement:.2f})"
        share = np.bincount(viterbi, minlength=self.n_components) / len(viterbi)
        assert share.min() >= 0.10, f"a regime holds under 10 percent of bars ({share})"

    def _covars_diag(self) -> np.ndarray:
        """Extract diagonal variances (K, d) from model.covars_ (K, d, d)."""
        d = self.model.means_.shape[1]
        return self.model.covars_[:, np.arange(d), np.arange(d)]

    def test_causal_states_dtype_and_range(self):
        """Causal decoded states must be integer type, all values in {0, 1}."""
        causal_states, _ = _decode(
            self.obs,
            self.model.means_,
            self._covars_diag(),
            self.model.transmat_,
            self.n_components,
        )

        assert np.issubdtype(
            causal_states.dtype, np.integer
        ), f"causal_states dtype should be integer, got {causal_states.dtype}"
        assert set(np.unique(causal_states)).issubset(
            {0, 1}
        ), f"causal_states values must be in {{0, 1}}, got {np.unique(causal_states)}"

    def test_causal_pre_switch_bars_consistent(self):
        """Pre-switch bars 0-9 must all be assigned the same causal regime.

        Since the first 10 bars are strongly positive returns with very low variance,
        the causal filter should consistently assign them to the same state.
        Viterbi may assign a different state (due to backward smoothing) but the
        causal decoder must be internally consistent on the clear pre-switch region.
        """
        causal_states, _ = _decode(
            self.obs,
            self.model.means_,
            self._covars_diag(),
            self.model.transmat_,
            self.n_components,
        )

        pre_switch_states = causal_states[:10]
        n_unique_pre = len(np.unique(pre_switch_states))
        assert n_unique_pre == 1, (
            f"Pre-switch bars 0-9 should all share the same causal regime label, "
            f"got {n_unique_pre} distinct labels: {np.unique(pre_switch_states)}"
        )

    def _ambiguous_tail(self, n: int = 12) -> np.ndarray:
        """The regime-switch sequence plus n bars between the two fitted means, where the filter
        is not saturated, so a leak of future information moves a probability materially."""
        mid = self.model.means_.mean(axis=0)
        rng = np.random.default_rng(_SEED + 2)
        spread = np.sqrt(self._covars_diag().mean(axis=0))
        return np.vstack([self.obs, mid + rng.normal(0.0, 0.3, (n, 2)) * spread])

    def _prefix_check(self, decoder, obs: np.ndarray, cuts) -> None:
        full_states, full_alpha = decoder(obs)
        for cut in cuts:
            states, alpha = decoder(obs[:cut])
            np.testing.assert_array_equal(states, full_states[:cut], err_msg=f"states, cut {cut}")
            np.testing.assert_array_equal(alpha, full_alpha[:cut], err_msg=f"alpha, cut {cut}")

    def _decoders(self):
        means, covars, transmat = self.model.means_, self._covars_diag(), self.model.transmat_
        log_a = np.log(np.maximum(transmat, 1e-300))
        pi0 = _stationary_distribution(transmat)

        def production(obs):
            return alpha_pass_jit(_log_emit_diag(obs, means, covars), log_a, pi0)

        def reference(obs):
            return _decode(obs, means, covars, transmat, self.n_components)

        return production, reference

    def test_causal_is_truly_causal(self):
        """Prefix invariance: decoding obs[0..T] and obs[0..N] gives the same states and the same
        filtered probabilities at every t <= T, for the production filter (alpha_pass_jit) and the
        reference one, with cuts inside a run of ambiguous bars where the filter is not
        saturated, and after each regime switch."""
        obs = self._ambiguous_tail()
        n = len(self.obs)
        cuts = (151, 201, n + 3, n + 6, n + 9)
        _states, alpha = self._decoders()[0](obs)
        assert (
            alpha[n + 3 : n + 9].min() > 1e-9
        ), "the ambiguous bars must not be saturated (1e-36 after a switch)"
        for decoder in self._decoders():
            self._prefix_check(decoder, obs, cuts)

    def test_the_prefix_check_catches_a_smoother(self):
        """The same check on hmmlearn's forward-backward posteriors (a non-causal decoder) fails."""

        def smoother(obs):
            posteriors = self.model.predict_proba(obs)
            return posteriors.argmax(axis=1), posteriors

        obs = self._ambiguous_tail()
        n = len(self.obs)
        with pytest.raises(AssertionError, match="alpha"):
            self._prefix_check(smoother, obs, (n + 3, n + 6, n + 9))

    def test_causal_decode_output_shape(self):
        """Output state array must have length == n_bars."""
        causal_states, alpha_hist = _decode(
            self.obs,
            self.model.means_,
            self._covars_diag(),
            self.model.transmat_,
            self.n_components,
        )
        n = len(self.obs)
        assert causal_states.shape == (n,), f"Expected ({n},), got {causal_states.shape}"
        assert alpha_hist.shape == (
            n,
            self.n_components,
        ), f"Expected ({n}, {self.n_components}), got {alpha_hist.shape}"
