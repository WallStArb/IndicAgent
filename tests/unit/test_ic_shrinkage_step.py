"""Unit tests for scripts/ops/alpha/ops_ic_shrinkage.py (Phase 142B.1-03, E1).

Covers the pure, DB-free functions: the compute-pass update builder
(`compute_shrinkage_updates`), the out-of-fold decision helper
(`evaluate_out_of_fold_gate`), and the out-of-fold split/prior/error builder
(`build_out_of_fold_errors`). No DB, no Kafka -- follows the
`tests/unit/test_ensemble_ic_gate.py` sys.path.insert convention for importing a
`scripts/ops/alpha/` oneshot as a module.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pytest

_scripts_alpha_dir = Path(__file__).parent.parent.parent / "scripts" / "ops" / "alpha"
if str(_scripts_alpha_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_alpha_dir))

import ops_ic_shrinkage as ic_shrinkage  # noqa: E402
from ops_ic_shrinkage import (  # noqa: E402
    build_out_of_fold_errors,
    compute_shrinkage_updates,
    evaluate_out_of_fold_gate,
)

# ---------------------------------------------------------------------------
# compute_shrinkage_updates
# ---------------------------------------------------------------------------


def _row(feature_name, symbol, tf, regime, lookahead_bars, n_independent, ic_sharpe_hac):
    return {
        "feature_name": feature_name,
        "symbol": symbol,
        "tf": tf,
        "regime": regime,
        "lookahead_bars": lookahead_bars,
        "training_window_end": "2026-01-01T00:00:00Z",
        "n_independent": n_independent,
        "ic_sharpe_hac": ic_sharpe_hac,
    }


class TestComputeShrinkageUpdates:
    def test_leave_one_out_prior_excludes_self(self) -> None:
        """3-member group (momentum, high_bear, 5m) -- each row's prior excludes itself,
        matching leave_one_out_group_prior's contract exactly (D-06)."""
        ic_rows = [
            _row("feat_a", "SPY", "5m", "high_bear", 5, 1000, 0.10),
            _row("feat_b", "SPY", "5m", "high_bear", 5, 1000, 0.20),
            _row("feat_c", "SPY", "5m", "high_bear", 5, 1000, 0.30),
        ]
        feature_to_group = {"feat_a": "momentum", "feat_b": "momentum", "feat_c": "momentum"}
        updates = compute_shrinkage_updates(ic_rows, feature_to_group, k=100.0)
        assert len(updates) == 3

        by_feature = {u[2]: u for u in updates}
        # With n_eff=1000 >> k=100, w should be close to 1 (trust raw), so ic_shrunk
        # should sit close to each row's own raw ic_sharpe_hac, not the prior.
        assert by_feature["feat_a"][0] == pytest.approx(0.10, abs=0.02)
        assert by_feature["feat_b"][0] == pytest.approx(0.20, abs=0.02)
        assert by_feature["feat_c"][0] == pytest.approx(0.30, abs=0.02)

    def test_update_tuple_order_matches_pk(self) -> None:
        """(ic_shrunk, shrinkage_weight, feature_name, symbol, tf, regime,
        lookahead_bars, training_window_end) -- matches bulk_update_by_key's
        (*set_cols, *key_cols) row-ordering contract."""
        ic_rows = [
            _row("feat_a", "SPY", "5m", "high_bear", 5, 50, 0.10),
            _row("feat_a", "TLT", "5m", "high_bear", 5, 50, 0.15),
        ]
        feature_to_group = {"feat_a": "momentum"}
        updates = compute_shrinkage_updates(ic_rows, feature_to_group, k=100.0)
        assert len(updates) == 2
        for update, row in zip(updates, ic_rows):
            assert len(update) == 8
            (
                ic_shrunk,
                weight,
                feature_name,
                symbol,
                tf,
                regime,
                lookahead_bars,
                training_window_end,
            ) = update
            assert feature_name == row["feature_name"]
            assert symbol == row["symbol"]
            assert tf == row["tf"]
            assert regime == row["regime"]
            assert lookahead_bars == row["lookahead_bars"]
            assert training_window_end == row["training_window_end"]
            assert 0.0 <= weight <= 1.0
            assert np.isfinite(ic_shrunk)

    def test_row_without_group_mapping_is_skipped(self) -> None:
        """A feature absent from concept_registry.group_name cannot form a peer group
        and must be skipped, not crash or default to an empty-string group."""
        ic_rows = [
            _row("feat_unmapped", "SPY", "5m", "high_bear", 5, 100, 0.10),
            _row("feat_a", "SPY", "5m", "high_bear", 5, 100, 0.20),
        ]
        feature_to_group = {"feat_a": "momentum"}  # feat_unmapped absent
        updates = compute_shrinkage_updates(ic_rows, feature_to_group, k=100.0)
        feature_names = {u[2] for u in updates}
        assert "feat_unmapped" not in feature_names
        assert "feat_a" in feature_names

    def test_nan_ic_sharpe_hac_dropped_not_persisted(self) -> None:
        """A NaN raw input propagates through shrink_ic as a non-finite ic_shrunk --
        must be dropped, never written to the DB (Pitfall 1 defense-in-depth)."""
        ic_rows = [
            _row("feat_a", "SPY", "5m", "high_bear", 5, 100, float("nan")),
            _row("feat_b", "SPY", "5m", "high_bear", 5, 100, 0.20),
        ]
        feature_to_group = {"feat_a": "momentum", "feat_b": "momentum"}
        updates = compute_shrinkage_updates(ic_rows, feature_to_group, k=100.0)
        feature_names = {u[2] for u in updates}
        assert "feat_a" not in feature_names

    def test_n_eff_zero_falls_back_to_prior_with_zero_weight(self) -> None:
        """n_independent=0 -> shrink_ic degenerate branch: ic_shrunk == prior, weight == 0.0."""
        ic_rows = [
            _row("feat_a", "SPY", "5m", "high_bear", 5, 0, 0.90),
            _row("feat_b", "SPY", "5m", "high_bear", 5, 100, 0.10),
        ]
        feature_to_group = {"feat_a": "momentum", "feat_b": "momentum"}
        updates = compute_shrinkage_updates(ic_rows, feature_to_group, k=100.0)
        by_feature = {u[2]: u for u in updates}
        ic_shrunk_a, weight_a = by_feature["feat_a"][0], by_feature["feat_a"][1]
        # feat_a's leave-one-out prior is feat_b's raw IC (0.10) -- the only peer.
        assert ic_shrunk_a == pytest.approx(0.10)
        assert weight_a == pytest.approx(0.0)

    def test_disjoint_group_regime_tf_keys_do_not_share_a_prior(self) -> None:
        """Two rows in the same group_name but different regime (or tf) must NOT be
        pooled into one peer group -- D-06's key is (group_name, regime, tf)."""
        ic_rows = [
            _row("feat_a", "SPY", "5m", "high_bear", 5, 1000, 0.10),
            _row("feat_b", "SPY", "5m", "low_bull", 5, 1000, 0.90),
        ]
        feature_to_group = {"feat_a": "momentum", "feat_b": "momentum"}
        updates = compute_shrinkage_updates(ic_rows, feature_to_group, k=100.0)
        by_feature = {u[2]: u for u in updates}
        # Each is a singleton group (no peer sharing regime+tf) -- leave_one_out_group_prior
        # contract falls back to self, so shrink_ic shrinks toward its OWN raw value,
        # not the other row's.
        assert by_feature["feat_a"][0] == pytest.approx(0.10, abs=0.02)
        assert by_feature["feat_b"][0] == pytest.approx(0.90, abs=0.02)


# ---------------------------------------------------------------------------
# evaluate_out_of_fold_gate
# ---------------------------------------------------------------------------


class TestEvaluateOutOfFoldGate:
    def test_pass_when_shrunk_error_smaller(self) -> None:
        passed, mean_shrunk, mean_raw = evaluate_out_of_fold_gate(
            shrunk_errors=[0.01, 0.02, 0.03], raw_errors=[0.05, 0.06, 0.07]
        )
        assert passed is True
        assert mean_shrunk < mean_raw

    def test_fail_when_raw_error_smaller(self) -> None:
        passed, mean_shrunk, mean_raw = evaluate_out_of_fold_gate(
            shrunk_errors=[0.10, 0.10], raw_errors=[0.01, 0.01]
        )
        assert passed is False
        assert mean_shrunk > mean_raw

    def test_fail_on_tie_strict_inequality(self) -> None:
        """D-05: strictly less, not <=. An exact tie must FAIL, not PASS."""
        passed, mean_shrunk, mean_raw = evaluate_out_of_fold_gate(
            shrunk_errors=[0.05, 0.05], raw_errors=[0.05, 0.05]
        )
        assert passed is False
        assert mean_shrunk == mean_raw

    def test_empty_input_fails_without_crashing(self) -> None:
        passed, mean_shrunk, mean_raw = evaluate_out_of_fold_gate(shrunk_errors=[], raw_errors=[])
        assert passed is False
        assert np.isnan(mean_shrunk)
        assert np.isnan(mean_raw)


# ---------------------------------------------------------------------------
# build_out_of_fold_errors (split + fresh window-T prior + error construction)
# ---------------------------------------------------------------------------


def _make_pooled_series(n: int, feature_values: dict[str, list[float]], returns: list[float]):
    """Build a synthetic pooled cross-sectional series: n rows, each with the given
    feature columns and a 'return_fast' column (only scale exercised by these tests)."""
    rows = []
    for i in range(n):
        row = {"bar_ts": i, "return_fast": returns[i]}
        for fname, values in feature_values.items():
            row[fname] = values[i]
        rows.append(row)
    return rows


class TestBuildOutOfFoldErrors:
    def test_produces_one_error_pair_per_qualifying_cell(self) -> None:
        n = 40
        rng = np.random.default_rng(42)
        returns = rng.normal(size=n).tolist()
        feat_a = (np.array(returns) + rng.normal(scale=0.1, size=n)).tolist()
        pooled = _make_pooled_series(n, {"feat_a": feat_a}, returns)

        cells_by_stratum = {
            ("5m", "high_bear"): [
                {"feature_name": "feat_a", "tf": "5m", "regime": "high_bear", "lookahead_bars": 1}
            ]
        }
        pooled_by_stratum = {("5m", "high_bear"): pooled}
        feature_to_group = {"feat_a": "momentum"}
        bars_to_scale_by_tf = {"5m": {1: "fast"}}

        shrunk_errors, raw_errors, n_evaluated = build_out_of_fold_errors(
            pooled_by_stratum, cells_by_stratum, feature_to_group, bars_to_scale_by_tf, k=10.0
        )
        assert n_evaluated == 1
        assert len(shrunk_errors) == 1
        assert len(raw_errors) == 1
        assert shrunk_errors[0] >= 0.0
        assert raw_errors[0] >= 0.0

    def test_too_few_bars_in_stratum_skipped(self) -> None:
        """n < 4 in the pooled series -- stratum contributes zero cells (cannot split)."""
        pooled = _make_pooled_series(2, {"feat_a": [0.1, 0.2]}, [0.1, 0.2])
        cells_by_stratum = {
            ("5m", "high_bear"): [
                {"feature_name": "feat_a", "tf": "5m", "regime": "high_bear", "lookahead_bars": 1}
            ]
        }
        pooled_by_stratum = {("5m", "high_bear"): pooled}
        shrunk_errors, raw_errors, n_evaluated = build_out_of_fold_errors(
            pooled_by_stratum,
            cells_by_stratum,
            {"feat_a": "momentum"},
            {"5m": {1: "fast"}},
            k=10.0,
        )
        assert n_evaluated == 0
        assert shrunk_errors == []
        assert raw_errors == []

    def test_unknown_lookahead_bars_skipped(self) -> None:
        """A cell whose lookahead_bars has no scale mapping is skipped, not crashed on."""
        n = 20
        rng = np.random.default_rng(1)
        returns = rng.normal(size=n).tolist()
        feat_a = rng.normal(size=n).tolist()
        pooled = _make_pooled_series(n, {"feat_a": feat_a}, returns)
        cells_by_stratum = {
            ("5m", "high_bear"): [
                {
                    "feature_name": "feat_a",
                    "tf": "5m",
                    "regime": "high_bear",
                    "lookahead_bars": 999,  # not in bars_to_scale
                }
            ]
        }
        shrunk_errors, raw_errors, n_evaluated = build_out_of_fold_errors(
            {("5m", "high_bear"): pooled},
            cells_by_stratum,
            {"feat_a": "momentum"},
            {"5m": {1: "fast"}},
            k=10.0,
        )
        assert n_evaluated == 0

    def test_cross_tf_bars_do_not_leak(self) -> None:
        """Todo 146/202 adversarial case: a stratum's tf is 15m, but bars_to_scale_by_tf
        only has an entry for 5m at this cell's lookahead_bars. Must be skipped, not
        matched against another tf's map -- proves no cross-tf leakage, same defect
        class as ic_engine.py's lifecycle-hook gate query fixed under todo 146 itself."""
        n = 20
        rng = np.random.default_rng(2)
        returns = rng.normal(size=n).tolist()
        feat_a = rng.normal(size=n).tolist()
        pooled = _make_pooled_series(n, {"feat_a": feat_a}, returns)
        cells_by_stratum = {
            ("15m", "high_bear"): [
                {
                    "feature_name": "feat_a",
                    "tf": "15m",
                    "regime": "high_bear",
                    "lookahead_bars": 1,  # valid for 5m's map below, not for 15m's (absent)
                }
            ]
        }
        shrunk_errors, raw_errors, n_evaluated = build_out_of_fold_errors(
            {("15m", "high_bear"): pooled},
            cells_by_stratum,
            {"feat_a": "momentum"},
            {"5m": {1: "fast"}},  # no "15m" key at all
            k=10.0,
        )
        assert n_evaluated == 0
        assert shrunk_errors == []
        assert raw_errors == []

    def test_embargo_exceeding_series_length_skips_cell(self) -> None:
        """A large embargo (lookahead_bars) relative to series length pushes
        test_start >= n -- the cell is skipped, not crashed on with a negative slice."""
        n = 10
        returns = [0.1] * n
        feat_a = [0.1] * n
        pooled = _make_pooled_series(n, {"feat_a": feat_a}, returns)
        cells_by_stratum = {
            ("5m", "high_bear"): [
                {
                    "feature_name": "feat_a",
                    "tf": "5m",
                    "regime": "high_bear",
                    "lookahead_bars": 100,  # embargo >> n
                }
            ]
        }
        shrunk_errors, raw_errors, n_evaluated = build_out_of_fold_errors(
            {("5m", "high_bear"): pooled},
            cells_by_stratum,
            {"feat_a": "momentum"},
            {"5m": {100: "fast"}},
            k=10.0,
        )
        assert n_evaluated == 0


# ---------------------------------------------------------------------------
# Structural / source assertions (T-142B1-03-02: hard-gate source guarantee)
# ---------------------------------------------------------------------------


class TestHardGateSourceStructure:
    def test_ic_input_flip_lives_only_inside_pass_branch(self) -> None:
        """The alpha.ensemble.ic_input ConfigService.set(...) call must appear strictly
        after `if passed:` and before the matching `else:` in main() -- on FAIL, no
        config_state UPDATE flipping ic_input may execute (T-142B1-03-02)."""
        source = Path(ic_shrinkage.__file__).read_text()
        if_passed_idx = source.index("if passed:")
        else_idx = source.index("else:", if_passed_idx)
        pass_branch = source[if_passed_idx:else_idx]
        assert "alpha.ensemble.ic_input" in pass_branch
        assert "config_service.set(" in pass_branch
        else_branch = source[else_idx:]
        # The else branch (FAIL path) must not also flip ic_input.
        fail_branch_end = (
            else_branch.index("\n\n", 0) if "\n\n" in else_branch else len(else_branch)
        )
        assert "config_service.set(" not in else_branch[:fail_branch_end]

    def test_bulk_update_by_key_uses_correct_key_and_set_cols(self) -> None:
        """bulk_update_by_key must be called with the 6-column PK as key_cols and
        ic_shrunk/shrinkage_weight as set_cols (acceptance criterion)."""
        assert ic_shrinkage._PK_COLS == (
            "feature_name",
            "symbol",
            "tf",
            "regime",
            "lookahead_bars",
            "training_window_end",
        )
        assert ic_shrinkage._SET_COLS == ("ic_shrunk", "shrinkage_weight")
        source = Path(ic_shrinkage.__file__).read_text()
        assert "key_cols=list(_PK_COLS)" in source
        assert "set_cols=list(_SET_COLS)" in source

    def test_no_naive_group_average_or_explicit_matrix_inverse(self) -> None:
        """Acceptance criterion: no naive self-inclusive group AVG, no np.linalg.inv."""
        source = Path(ic_shrinkage.__file__).read_text()
        assert not re.search(r"np\.linalg\.inv|SELECT AVG.*group_name|AVG\(ic", source)

    def test_imports_shrink_ic_and_leave_one_out_group_prior(self) -> None:
        assert callable(ic_shrinkage.shrink_ic)
        assert callable(ic_shrinkage.leave_one_out_group_prior)

    def test_imports_bulk_update_by_key_and_load_apr_dict_async(self) -> None:
        assert callable(ic_shrinkage.bulk_update_by_key)
        assert callable(ic_shrinkage._load_apr_dict)
