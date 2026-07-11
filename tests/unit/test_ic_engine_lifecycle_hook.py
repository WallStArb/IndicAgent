"""Unit tests: ic_engine post-run lifecycle hook (Phase 143 Plan 03, LIFECYCLE-03/04).

Pure Python -- no real DB, no Kafka. A hand-rolled fake psycopg2 connection/cursor
pair simulates enough of feature_ic_scores JOIN ensemble_weights + integrity_monitor
to exercise the hook's actual SQL parameter binding (lookahead_bars, weight_version),
not just the Python-side aggregation. Mirrors the fake-connection pattern used by
tests/unit/intelligence/test_feature_registry_service.py (Plan 02).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from datetime import UTC, datetime

from services.ic_engine import ICEngineConfig, _run_lifecycle_hook

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeManifest:
    """Minimal stand-in exposing only the attributes _get_prior_ic_engine_completion
    reads (manifest_dir, step_name). Points at a directory with no manifest file --
    CorpusManifest.read() raises FileNotFoundError, exercising the first-run fallback."""

    def __init__(self, manifest_dir: Path):
        self.manifest_dir = manifest_dir
        self.step_name = "ic_engine"


class _FakeLifecycleCursor:
    def __init__(self, conn: _FakeLifecycleConn):
        self.conn = conn
        self._rows: list[tuple] = []
        self._description: list[tuple] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        params = params or ()
        self.conn.executed_sql.append(sql)
        self.conn.executed_params.append(params)

        if "SELECT 1 FROM integrity_monitor" in sql:
            training_window_end = params[0]
            hit = any(
                r["training_window_end"] == training_window_end
                for r in self.conn.existing_integrity_rows
            )
            self._rows = [(1,)] if hit else []
            self._description = [("exists",)]
            return

        if "FROM feature_ic_scores fis" in sql:
            weight_version, training_window_end, lookahead_bars = params
            weight_lookup = {
                (r["tf"], r["regime"], r["feature_name"]): r["weight"]
                for r in self.conn.ensemble_weight_rows
                if r["weight_version"] == weight_version
            }
            cols = [
                "feature_name",
                "tf",
                "regime",
                "ic_ci_lower",
                "ic_ci_upper",
                "ic_sign",
                "passes_fdr",
                "reliable",
                "n_independent",
                "feature_status_at_eval",
                "ic_sharpe_hac",
                "standing_weight",
            ]
            result_rows = []
            for r in self.conn.corpus_rows:
                if r["training_window_end"] != training_window_end:
                    continue
                if r["lookahead_bars"] != lookahead_bars:
                    continue
                standing_weight = weight_lookup.get((r["tf"], r["regime"], r["feature_name"]), 0.0)
                result_rows.append(
                    tuple(
                        standing_weight if col == "standing_weight" else r.get(col) for col in cols
                    )
                )
            self._rows = result_rows
            self._description = [(c,) for c in cols]
            return

        if "INSERT INTO integrity_monitor" in sql:
            self.conn.integrity_inserts.append(params)
            self._rows = []
            self._description = None
            return

        if "max(training_window_end)" in sql:
            training_window_end = params[0]
            candidates = [
                r["training_window_end"]
                for r in self.conn.corpus_rows
                if r["training_window_end"] < training_window_end
            ]
            self._rows = [(max(candidates) if candidates else None,)]
            self._description = [("max",)]
            return

        self._rows = []
        self._description = None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    @property
    def description(self):
        return self._description


class _FakeLifecycleConn:
    """Simulates enough of a psycopg2 connection for _run_lifecycle_hook."""

    def __init__(
        self,
        corpus_rows: list[dict],
        ensemble_weight_rows: list[dict] | None = None,
        existing_integrity_rows: list[dict] | None = None,
    ):
        self.corpus_rows = corpus_rows
        self.ensemble_weight_rows = ensemble_weight_rows or []
        self.existing_integrity_rows = existing_integrity_rows or []
        self.integrity_inserts: list[tuple] = []
        self.executed_sql: list[str] = []
        self.executed_params: list[tuple] = []
        self.committed = False

    def cursor(self):
        return _FakeLifecycleCursor(self)

    def commit(self):
        self.committed = True


class _FakeRegistryService:
    """Fake FeatureRegistryService exposing only the methods the hook calls."""

    def __init__(self, features: dict[str, dict]):
        # features: feature_name -> {"status": str, "eligible": bool}
        self._features = features
        self.transition_calls: list[tuple] = []
        self.advance_calls: list[tuple] = []
        self.transition_return_value = True

    def get_all_features(self):
        return [{"feature_name": k, "status": v["status"]} for k, v in self._features.items()]

    def record_transition_sync(
        self,
        conn,
        feature_name,
        from_status,
        to_status,
        reason,
        ic_value=None,
        ic_sharpe=None,
        ic_n=None,
    ):
        self.transition_calls.append(
            (feature_name, from_status, to_status, reason, ic_value, ic_sharpe, ic_n)
        )
        if self.transition_return_value:
            self._features[feature_name]["status"] = to_status
        return self.transition_return_value

    def advance_shadow_counters_sync(self, conn, feature_name, passed, new_observations):
        self.advance_calls.append((feature_name, passed, new_observations))

    def is_promotion_eligible(self, feature_name, recovery_min_observations, recovery_min_passes):
        return self._features.get(feature_name, {}).get("eligible", False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T1 = datetime(2026, 7, 10, 5, 15, tzinfo=UTC)


def _cell(
    feature_name: str,
    tf: str,
    regime: str,
    ic_ci_lower: float | None,
    passes_fdr: bool,
    n_independent: int,
    status: str,
    ic_sharpe_hac: float | None = 0.1,
    training_window_end=_T1,
    lookahead_bars: int = 5,
    reliable: bool = True,
    ic_ci_upper: float | None = None,
    ic_sign: int = 1,
) -> dict:
    return {
        "feature_name": feature_name,
        "tf": tf,
        "regime": regime,
        "ic_ci_lower": ic_ci_lower,
        "ic_ci_upper": ic_ci_upper,
        "ic_sign": ic_sign,
        "passes_fdr": passes_fdr,
        "reliable": reliable,
        "n_independent": n_independent,
        "feature_status_at_eval": status,
        "ic_sharpe_hac": ic_sharpe_hac,
        "training_window_end": training_window_end,
        "lookahead_bars": lookahead_bars,
    }


def _make_config(**overrides) -> ICEngineConfig:
    defaults = dict(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=2000,
        sharpe_min_windows=10,
        subsample_min_stride=5,
        min_reliable_n=100,
        cluster_max_corr=0.70,
        lookahead_fast=1,
        lookahead_mid=5,
        lookahead_slow=20,
        lookahead_extended=60,
        equity_model_enabled=True,
        min_obs_daily=1000,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
        decay_materiality_threshold=0.005,
        decay_regime_shift_fraction=0.60,
        decay_recovery_min_observations=2000,
        decay_recovery_min_passes=2,
        meta_fdr_min_fraction=0.50,
        ic_staleness_alert_days=5,
        ensemble_weight_version="v1",
        sign_symmetric=False,
    )
    defaults.update(overrides)
    return ICEngineConfig(**defaults)


def _make_manifest(tmp_path: Path) -> _FakeManifest:
    return _FakeManifest(tmp_path)


# ---------------------------------------------------------------------------
# Demotion
# ---------------------------------------------------------------------------


def test_demotion_triggers_on_materially_failing_active_feature(tmp_path):
    """6/10 material-fail cells (60% >= 50% floor) demotes; never 'deprecated'."""
    config = _make_config(meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99)
    cells = []
    for i in range(10):
        failing = i < 6
        cells.append(
            _cell(
                "featA",
                "5m",
                f"regime_{i}",
                ic_ci_lower=-0.02 if failing else 0.03,
                passes_fdr=not failing,
                n_independent=1000,
                status="active",
            )
        )
    ew = [
        {
            "tf": "5m",
            "regime": f"regime_{i}",
            "feature_name": "featA",
            "weight_version": "v1",
            "weight": 0.5,
        }
        for i in range(10)
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert len(registry.transition_calls) == 1
    call = registry.transition_calls[0]
    assert call[0] == "featA"
    assert call[1] == "active"
    assert call[2] == "shadow_only"
    assert call[3] == "ic_demotion"
    assert all(c[2] != "deprecated" for c in registry.transition_calls)


def test_demotion_boundary_below_threshold_not_demoted(tmp_path):
    """4/10 material-fail cells (40% < 50% floor) does NOT demote."""
    config = _make_config(meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99)
    cells = []
    for i in range(10):
        failing = i < 4
        cells.append(
            _cell(
                "featA",
                "5m",
                f"regime_{i}",
                ic_ci_lower=-0.02 if failing else 0.03,
                passes_fdr=not failing,
                n_independent=1000,
                status="active",
            )
        )
    ew = [
        {
            "tf": "5m",
            "regime": f"regime_{i}",
            "feature_name": "featA",
            "weight_version": "v1",
            "weight": 0.5,
        }
        for i in range(10)
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.transition_calls == []


def test_demotion_boundary_at_threshold_demoted(tmp_path):
    """5/10 material-fail cells (50% == 50% floor) DOES demote (>= is inclusive)."""
    config = _make_config(meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99)
    cells = []
    for i in range(10):
        failing = i < 5
        cells.append(
            _cell(
                "featA",
                "5m",
                f"regime_{i}",
                ic_ci_lower=-0.02 if failing else 0.03,
                passes_fdr=not failing,
                n_independent=1000,
                status="active",
            )
        )
    ew = [
        {
            "tf": "5m",
            "regime": f"regime_{i}",
            "feature_name": "featA",
            "weight_version": "v1",
            "weight": 0.5,
        }
        for i in range(10)
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert len(registry.transition_calls) == 1
    assert registry.transition_calls[0][2] == "shadow_only"


def test_zero_standing_weight_not_demoted(tmp_path):
    """8/10 cells fail, but standing_weight=0 for all -- zero material-fail cells, no demotion."""
    config = _make_config(meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99)
    cells = []
    for i in range(10):
        failing = i < 8
        cells.append(
            _cell(
                "featA",
                "5m",
                f"regime_{i}",
                ic_ci_lower=-0.02 if failing else 0.03,
                passes_fdr=not failing,
                n_independent=1000,
                status="active",
            )
        )
    # No ensemble_weight_rows at all -> standing_weight COALESCEs to 0.0 for every cell.
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=[])
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.transition_calls == []


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------


def test_promotion_when_eligible_zero_ensemble_weights_writes(tmp_path):
    config = _make_config(meta_fdr_min_fraction=0.50)
    cells = [
        _cell(
            "featB",
            "5m",
            f"regime_{i}",
            ic_ci_lower=0.03,
            passes_fdr=True,
            n_independent=1000,
            status="shadow_only",
        )
        for i in range(4)
    ]
    conn = _FakeLifecycleConn(cells)
    registry = _FakeRegistryService({"featB": {"status": "shadow_only", "eligible": True}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert len(registry.transition_calls) == 1
    call = registry.transition_calls[0]
    assert call[:4] == ("featB", "shadow_only", "active", "ic_promotion")
    # advance_shadow_counters_sync: passed = FDR-pass fraction test; new_observations = sum n_independent
    assert registry.advance_calls == [("featB", True, 4000)]
    assert not any(
        "INSERT INTO ensemble_weights" in sql or "UPDATE ensemble_weights" in sql
        for sql in conn.executed_sql
    )


def test_no_promotion_when_ineligible(tmp_path):
    config = _make_config(meta_fdr_min_fraction=0.50)
    cells = [
        _cell(
            "featB",
            "5m",
            f"regime_{i}",
            ic_ci_lower=0.03,
            passes_fdr=True,
            n_independent=1000,
            status="shadow_only",
        )
        for i in range(4)
    ]
    conn = _FakeLifecycleConn(cells)
    registry = _FakeRegistryService({"featB": {"status": "shadow_only", "eligible": False}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.transition_calls == []
    # Counters still advanced even when not (yet) eligible.
    assert registry.advance_calls == [("featB", True, 4000)]


# ---------------------------------------------------------------------------
# Regime-shift guard
# ---------------------------------------------------------------------------


def test_regime_shift_guard_holds_all_weights(tmp_path):
    """>=60% of active cells fail simultaneously -> hold: zero transitions, one hold fact."""
    config = _make_config(decay_regime_shift_fraction=0.60)
    cells = []
    for i in range(10):
        failing = i < 7  # 70% >= 60% threshold
        cells.append(
            _cell(
                "featA",
                "5m",
                f"regime_{i}",
                ic_ci_lower=-0.02 if failing else 0.03,
                passes_fdr=not failing,
                n_independent=1000,
                status="active",
            )
        )
    ew = [
        {
            "tf": "5m",
            "regime": f"regime_{i}",
            "feature_name": "featA",
            "weight_version": "v1",
            "weight": 0.5,
        }
        for i in range(10)
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.transition_calls == []
    assert len(conn.integrity_inserts) == 1
    inserted_params = conn.integrity_inserts[0]
    # (fraction, threshold, training_window_end)
    assert inserted_params[1] == config.decay_regime_shift_fraction
    assert inserted_params[2] == _T1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotency_short_circuit_on_existing_fact(tmp_path):
    config = _make_config()
    cells = [
        _cell(
            "featA",
            "5m",
            "regime_0",
            ic_ci_lower=-0.02,
            passes_fdr=False,
            n_independent=1000,
            status="active",
        )
    ]
    conn = _FakeLifecycleConn(cells, existing_integrity_rows=[{"training_window_end": _T1}])
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.transition_calls == []
    assert not any("FROM feature_ic_scores fis" in sql for sql in conn.executed_sql)


# ---------------------------------------------------------------------------
# Fable N3: lookahead pinning (no ~4x overcounting)
# ---------------------------------------------------------------------------


def test_lookahead_pinning_uses_only_mid_lookahead_rows(tmp_path):
    """4 rows per (feature, tf, regime) at lookahead_bars in {1,5,20,60}; hook must use
    ONLY the mid (5) row per cell -- new_observations must equal the sum over mid-only
    rows, not all 4 lookaheads (a naive sum-all implementation would overcount ~4x)."""
    config = _make_config(lookahead_mid=5, meta_fdr_min_fraction=0.50)
    cells = []
    for tf, regime in [("5m", "r0"), ("5m", "r1"), ("5m", "r2"), ("5m", "r3")]:
        for lookahead in (1, 5, 20, 60):
            cells.append(
                _cell(
                    "featB",
                    tf,
                    regime,
                    ic_ci_lower=0.03,
                    passes_fdr=True,
                    n_independent=1000,
                    status="shadow_only",
                    lookahead_bars=lookahead,
                )
            )
    conn = _FakeLifecycleConn(cells)
    registry = _FakeRegistryService({"featB": {"status": "shadow_only", "eligible": False}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.advance_calls == [
        ("featB", True, 4000)
    ]  # 4 mid-lookahead cells * 1000, not 16*1000


# ---------------------------------------------------------------------------
# Fable N4: weight_version pinning to the APR champion
# ---------------------------------------------------------------------------


def test_weight_version_pinning_to_champion(tmp_path):
    """Standing-weight lookup must resolve config.ensemble_weight_version ('v1'), not
    the most-recent-by-computed_at row (a newer 'v2_challenger' weight_version)."""
    config = _make_config(ensemble_weight_version="v1", decay_regime_shift_fraction=0.99)
    cells = [
        _cell(
            "featA",
            "5m",
            "r0",
            ic_ci_lower=-0.02,
            passes_fdr=False,
            n_independent=1000,
            status="active",
        ),
    ]
    ew = [
        {
            "tf": "5m",
            "regime": "r0",
            "feature_name": "featA",
            "weight_version": "v1",
            "weight": 0.1,
        },
        # A newer, larger weight under a challenger epoch -- must NOT be picked up.
        {
            "tf": "5m",
            "regime": "r0",
            "feature_name": "featA",
            "weight_version": "v2_challenger",
            "weight": 100.0,
        },
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    # v1 weight (0.1) * |ic_ci_lower| (0.02) = 0.002, BELOW materiality_threshold (0.005) -> not material.
    # If v2_challenger's weight (100.0) had been used instead: 100*0.02=2.0, hugely material.
    assert registry.transition_calls == []
    assert "ORDER BY computed_at DESC LIMIT 1" not in "\n".join(conn.executed_sql)


# ---------------------------------------------------------------------------
# Fable N5: zero-cell guard
# ---------------------------------------------------------------------------


def test_zero_cell_guard_writes_no_fact(tmp_path):
    config = _make_config()
    conn = _FakeLifecycleConn(corpus_rows=[])  # zero POOLED rows for this window
    registry = _FakeRegistryService({})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.transition_calls == []
    assert conn.integrity_inserts == []


def test_zero_cell_run_does_not_short_circuit_a_later_run_with_cells(tmp_path):
    """A zero-cell run must NOT poison the idempotency key -- a later invocation for the
    SAME training_window_end that DOES have cells must still run to completion."""
    config = _make_config(meta_fdr_min_fraction=0.50)
    empty_conn = _FakeLifecycleConn(corpus_rows=[])
    registry = _FakeRegistryService({"featA": {"status": "active"}})
    _run_lifecycle_hook(empty_conn, registry, config, _T1, _make_manifest(tmp_path))
    assert empty_conn.integrity_inserts == []

    # Second invocation, same training_window_end, now WITH cells, using the SAME
    # existing_integrity_rows state (empty, since the zero-cell run wrote nothing).
    cells = [
        _cell(
            "featA",
            "5m",
            "r0",
            ic_ci_lower=0.03,
            passes_fdr=True,
            n_independent=1000,
            status="active",
        )
    ]
    ew = [
        {"tf": "5m", "regime": "r0", "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
    ]
    conn2 = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, existing_integrity_rows=[])
    _run_lifecycle_hook(conn2, registry, config, _T1, _make_manifest(tmp_path))
    assert len(conn2.integrity_inserts) == 1


# ---------------------------------------------------------------------------
# One integrity_monitor fact per normal run
# ---------------------------------------------------------------------------


def test_one_integrity_monitor_fact_per_normal_run(tmp_path):
    config = _make_config()
    cells = [
        _cell(
            "featA",
            "5m",
            "r0",
            ic_ci_lower=0.03,
            passes_fdr=True,
            n_independent=1000,
            status="active",
        )
    ]
    ew = [
        {"tf": "5m", "regime": "r0", "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert len(conn.integrity_inserts) == 1
    assert conn.committed is True


# ---------------------------------------------------------------------------
# Sign-aware demote predicate (Component E, todo 094, BLOCKER 1): closes the
# third sign-asymmetric gate. Contrarians (ic_sign=-1) must not be auto-demoted
# just because their persistently-negative ic_ci_lower sits below zero -- that
# is expected and correct for a real contrarian signal, not a failure.
# ---------------------------------------------------------------------------


def test_sign_symmetric_significant_contrarian_not_demoted(tmp_path):
    """sign_symmetric=True: a significant contrarian (ic_sign=-1, ic_ci_upper<0,
    passes_fdr=true) with non-zero standing_weight must NOT be flagged failed/material
    -- this is the exact self-reverting failure mode BLOCKER 1 identified (every
    contrarian would otherwise be re-demoted one cycle after Component E lands)."""
    config = _make_config(
        meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99, sign_symmetric=True
    )
    cells = [
        _cell(
            "featC",
            "5m",
            f"regime_{i}",
            ic_ci_lower=-0.30,  # persistently negative -- would fail the OLD unconditional gate
            ic_ci_upper=-0.05,  # significant CI entirely below zero on its own side
            ic_sign=-1,
            passes_fdr=True,
            n_independent=1000,
            status="active",
        )
        for i in range(10)
    ]
    ew = [
        {
            "tf": "5m",
            "regime": f"regime_{i}",
            "feature_name": "featC",
            "weight_version": "v1",
            "weight": 0.5,
        }
        for i in range(10)
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featC": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert (
        registry.transition_calls == []
    ), "A significant contrarian must not be demoted under sign_symmetric=True"


def test_sign_symmetric_ci_straddling_contrarian_is_demoted(tmp_path):
    """sign_symmetric=True: a contrarian whose CI straddles zero (ic_ci_upper >= 0,
    i.e. NOT significant on its own side) IS flagged failed/material and demoted --
    the sign-aware gate still catches genuinely non-significant contrarians."""
    config = _make_config(
        meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99, sign_symmetric=True
    )
    # 6/10 straddling (failed) + 4/10 significant (not failed) -- 60% material-fail
    # meets the 50% demote floor without tripping the 99% regime-shift guard.
    cells = []
    for i in range(10):
        straddling = i < 6
        cells.append(
            _cell(
                "featC",
                "5m",
                f"regime_{i}",
                ic_ci_lower=-0.10,
                ic_ci_upper=0.02 if straddling else -0.05,  # straddles zero vs. significant
                ic_sign=-1,
                passes_fdr=not straddling,
                n_independent=1000,
                status="active",
            )
        )
    ew = [
        {
            "tf": "5m",
            "regime": f"regime_{i}",
            "feature_name": "featC",
            "weight_version": "v1",
            "weight": 0.5,
        }
        for i in range(10)
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featC": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert len(registry.transition_calls) == 1
    assert registry.transition_calls[0][:4] == ("featC", "active", "shadow_only", "ic_demotion")


def test_sign_symmetric_positive_cell_still_demoted(tmp_path):
    """sign_symmetric=True: a positive cell (ic_sign=1, ic_ci_lower<=0) is still
    flagged failed/material -- the positive side of the predicate is unchanged by
    the flag, only the contrarian branch is new."""
    config = _make_config(
        meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99, sign_symmetric=True
    )
    # 6/10 failing + 4/10 passing -- 60% material-fail meets the 50% demote floor
    # without tripping the 99% regime-shift guard.
    cells = []
    for i in range(10):
        failing = i < 6
        cells.append(
            _cell(
                "featA",
                "5m",
                f"regime_{i}",
                ic_ci_lower=-0.02 if failing else 0.03,
                ic_ci_upper=0.10 if failing else 0.15,
                ic_sign=1,
                passes_fdr=not failing,
                n_independent=1000,
                status="active",
            )
        )
    ew = [
        {
            "tf": "5m",
            "regime": f"regime_{i}",
            "feature_name": "featA",
            "weight_version": "v1",
            "weight": 0.5,
        }
        for i in range(10)
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert len(registry.transition_calls) == 1
    assert registry.transition_calls[0][:4] == ("featA", "active", "shadow_only", "ic_demotion")


def test_sign_symmetric_off_positive_cell_decision_is_byte_identical(tmp_path):
    """Equivalence property: with sign_symmetric=False (the default), the
    failed/material decision for a positive cell is byte-identical to
    test_demotion_triggers_on_materially_failing_active_feature's outcome above --
    same cell shape, same result, flag OFF reproduces the pre-Component-E hook."""
    config = _make_config(
        meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99, sign_symmetric=False
    )
    cells = []
    for i in range(10):
        failing = i < 6
        cells.append(
            _cell(
                "featA",
                "5m",
                f"regime_{i}",
                ic_ci_lower=-0.02 if failing else 0.03,
                passes_fdr=not failing,
                n_independent=1000,
                status="active",
            )
        )
    ew = [
        {
            "tf": "5m",
            "regime": f"regime_{i}",
            "feature_name": "featA",
            "weight_version": "v1",
            "weight": 0.5,
        }
        for i in range(10)
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert len(registry.transition_calls) == 1
    call = registry.transition_calls[0]
    assert call[:4] == ("featA", "active", "shadow_only", "ic_demotion")


# ---------------------------------------------------------------------------
# Structural / static assertions
# ---------------------------------------------------------------------------


def test_hook_has_no_async_or_await():
    source = inspect.getsource(_run_lifecycle_hook)
    assert "await" not in source
    assert "async def" not in source


def test_hook_never_writes_ensemble_weights_source():
    source = inspect.getsource(_run_lifecycle_hook)
    assert "INSERT INTO ensemble_weights" not in source
    assert "UPDATE ensemble_weights" not in source


def test_hook_uses_meta_fdr_min_fraction_from_config():
    source = inspect.getsource(_run_lifecycle_hook)
    assert "meta_fdr_min_fraction" in source


def test_hook_filters_lookahead_bars_and_never_orders_by_computed_at():
    source = inspect.getsource(_run_lifecycle_hook)
    assert "lookahead_bars" in source
    assert "ORDER BY computed_at DESC LIMIT 1" not in source
