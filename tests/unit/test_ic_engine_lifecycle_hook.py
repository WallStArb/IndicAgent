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

from services.ic_engine import ICEngineConfig, _apply_feature_transitions, _run_lifecycle_hook

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

    def executemany(self, sql: str, params_list: list[tuple]) -> None:
        """Simulates psycopg2's executemany as a loop over execute() -- sufficient
        for these tests, which only assert on the accumulated per-call params
        (e.g. conn.guard_fact_inserts), not on batching/round-trip behavior."""
        for params in params_list:
            self.execute(sql, params)

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
            weight_version, training_window_end = params
            # Todo 146 (post-review): lookahead_mid is tf-specific now, but the real
            # query no longer embeds a tf/lookahead_bars filter in SQL at all --
            # _run_lifecycle_hook fetches every scale's rows for this training_window_end
            # and pins "the mid scale" in Python afterward, matching every other
            # lookahead consumer in ic_engine.py. The fake mirrors that: no
            # lookahead_bars filtering here, just training_window_end.
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
                "lookahead_bars",
                "standing_weight",
            ]
            result_rows = []
            for r in self.conn.corpus_rows:
                if r["training_window_end"] != training_window_end:
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

        if "FROM market_regimes" in sql:
            self._rows = [
                (r["regime_group"], r["regime_label"]) for r in self.conn.market_regime_rows
            ]
            self._description = [("regime_group",), ("regime_label",)]
            return

        if "metric_name = 'guard_fail_fraction'" in sql:
            subject, _limit = params
            matching = [
                r["metric_value"] for r in self.conn.guard_history_rows if r["subject"] == subject
            ]
            self._rows = [(v,) for v in matching]
            self._description = [("metric_value",)]
            return

        if "INSERT INTO integrity_monitor" in sql:
            # Both integrity_monitor call sites (decay_cells_flagged single-row via
            # emit_integrity_fact_sync, guard_fail_fraction batch via executemany)
            # now share the exact same parametrized SQL text (todo 150) -- dispatch
            # on params[2] (metric_name), the 3rd field of the shared 7-tuple
            # (monitor_type, subject, metric_name, metric_value, threshold_value,
            # passed, training_window_end), not on SQL text.
            metric_name = params[2] if len(params) > 2 else None
            if metric_name == "guard_fail_fraction":
                self.conn.guard_fact_inserts.append(params)
                self.conn.event_log.append(("guard_insert", params[1]))
            else:
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
        market_regime_rows: list[dict] | None = None,
        guard_history_rows: list[dict] | None = None,
    ):
        self.corpus_rows = corpus_rows
        self.ensemble_weight_rows = ensemble_weight_rows or []
        self.existing_integrity_rows = existing_integrity_rows or []
        self.market_regime_rows = market_regime_rows or []
        self.guard_history_rows = guard_history_rows or []
        self.integrity_inserts: list[tuple] = []
        self.guard_fact_inserts: list[tuple] = []
        self.executed_sql: list[str] = []
        self.executed_params: list[tuple] = []
        self.committed = False
        # Ordered ("commit", n) / ("guard_insert", subject) events -- lets tests
        # prove the deferred-flush ordering invariant (guard facts must not be
        # written before a registry-triggered commit already happened), not just
        # that the facts exist. See FeatureRegistryService's real `with conn:`
        # commit-on-exit semantics, mirrored below by _FakeRegistryService.
        self.event_log: list[tuple] = []
        self.commit_count = 0

    def cursor(self):
        return _FakeLifecycleCursor(self)

    def commit(self):
        self.committed = True
        self.commit_count += 1
        self.event_log.append(("commit", self.commit_count))


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
        # Real FeatureRegistryService.record_transition_sync wraps its SQL in
        # `with conn:`, which commits on clean exit -- mirrored here so tests can
        # verify _run_lifecycle_hook's deferred guard-fact writes actually survive
        # this commit rather than assuming it (todo 144 /simplify pass).
        conn.commit()
        return self.transition_return_value

    def advance_shadow_counters_sync(self, conn, feature_name, passed, new_observations):
        self.advance_calls.append((feature_name, passed, new_observations))
        conn.commit()

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
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 5, "15m": 5, "1h": 5, "1d": 5},
        lookahead_slow={"5m": 20, "15m": 20, "1h": 20, "1d": 20},
        lookahead_extended={"5m": 60, "15m": 60, "1h": 60, "1d": 60},
        equity_model_enabled=True,
        min_obs_daily=1000,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
        decay_materiality_threshold=0.005,
        guard_fail_rate_max=0.995,
        guard_fail_rate_min=0.85,
        guard_band_z=3.0,
        guard_min_cells=100,
        guard_min_history=8,
        guard_history_window=20,
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
    config = _make_config(meta_fdr_min_fraction=0.50)
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
    config = _make_config(meta_fdr_min_fraction=0.50)
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
    config = _make_config(meta_fdr_min_fraction=0.50)
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
    config = _make_config(meta_fdr_min_fraction=0.50)
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
# Regime-shift guard (todo 144: stratified, self-calibrating, two-sided)
# ---------------------------------------------------------------------------


def _stratum_cells(feature_name: str, tf: str, group_regimes: list[str], n_fail: int) -> list[dict]:
    """n_fail failing + (len(group_regimes) - n_fail) passing cells, one per
    regime label in group_regimes, all at the given tf, all feature_name."""
    cells = []
    for i, regime in enumerate(group_regimes):
        failing = i < n_fail
        cells.append(
            _cell(
                feature_name,
                tf,
                regime,
                ic_ci_lower=-0.02 if failing else 0.03,
                passes_fdr=not failing,
                n_independent=1000,
                status="active",
            )
        )
    return cells


def test_regime_shift_cold_start_within_seeded_rails_does_not_hold(tmp_path):
    """Regression for the exact live incident (fraction=0.9618): 100 active cells
    in one (tf, regime_group) stratum, 96 failing, NO history yet. 0.9618 sits
    inside the seeded rails [0.85, 0.995] -- must NOT hold. This is the case the
    old flat 0.60 threshold got wrong."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=96)
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, market_regime_rows=market_regimes)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(
        conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path)
    )

    # Did not hold: Step 4 ran, so featA's material-fail fraction (96/100=96% >=
    # 50% floor) demoted it -- proving the run proceeded past the guard, unlike
    # the old code which would have held here.
    assert len(registry.transition_calls) == 1
    assert registry.transition_calls[0][:4] == ("featA", "active", "shadow_only", "ic_demotion")
    # One guard fact was still written for calibration history.
    assert len(conn.guard_fact_inserts) == 1
    # 7-tuple: (monitor_type, subject, metric_name, metric_value, threshold_value,
    # passed, training_window_end) -- todo 150 shared-helper shape.
    _, subject, _, fraction, threshold, passed, window = conn.guard_fact_inserts[0]
    assert subject == "tf=5m|group=equity"
    assert fraction == 0.96
    assert passed is True


def test_regime_shift_cold_start_above_rail_holds(tmp_path):
    """100 active cells, all 100 failing (fraction=1.0, above the 0.995 rail) ->
    hold_high -> zero transitions, Step 4/5 skipped."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=100)
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, market_regime_rows=market_regimes)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(
        conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path)
    )

    assert registry.transition_calls == []
    assert len(conn.guard_fact_inserts) == 1
    _, _, _, fraction, _, passed, _ = conn.guard_fact_inserts[0]
    assert fraction == 1.0
    assert passed is False


def test_regime_shift_small_stratum_never_hold_authoritative(tmp_path):
    """10 active cells (below guard_min_cells=100), all failing -- must NOT hold
    (insufficient_cells is never authoritative), even though the fraction (1.0)
    would trip the rail if it were evaluated. Demotion still proceeds normally."""
    regimes = [f"r{i}" for i in range(10)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=10)
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, market_regime_rows=market_regimes)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(
        conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path)
    )

    assert len(registry.transition_calls) == 1  # demotion proceeded, guard didn't block it
    assert len(conn.guard_fact_inserts) == 1
    _, _, _, _, _, passed, _ = conn.guard_fact_inserts[0]
    assert passed is True  # insufficient_cells is not a violation


def test_regime_shift_suspiciously_low_fail_rate_alerts_not_holds(tmp_path):
    """100 active cells, only 10 failing (fraction=0.10, below the 0.85 rail) ->
    alert_low -> a fact is written with passed=False, but transitions still
    proceed normally (no hold on the low tail, per design)."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featB", "15m", regimes, n_fail=10)
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(cells, market_regime_rows=market_regimes)
    registry = _FakeRegistryService({"featB": {"status": "active"}})

    _run_lifecycle_hook(
        conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path)
    )

    assert len(conn.guard_fact_inserts) == 1
    _, _, _, fraction, _, passed, _ = conn.guard_fact_inserts[0]
    assert fraction == 0.10
    assert passed is False
    # Did not hold: Step 4 ran (90/100 = 90% pass, well below the 50% demote floor
    # applied to the 10% material-fail fraction -- no demotion, but that's Step 4
    # logic proceeding normally, not the guard blocking it).
    assert registry.transition_calls == []


def test_regime_shift_unmapped_regime_label_buckets_to_unmapped_stratum(tmp_path):
    """A cell whose regime label isn't found in the market_regimes lookup (e.g.
    market_regime_rows is empty, or genuinely missing that label) must bucket into
    a ('<tf>', '_unmapped') stratum -- and that stratum must still be evaluated
    (not silently dropped), just under the '_unmapped' group key. This is a real
    code path (services/ic_engine.py's `.get(cell["regime"], "_unmapped")`
    fallback) that every OTHER test in this file exercises incidentally (they all
    pass empty or non-matching market_regime_rows unless testing the mapping
    itself), so it needs its own explicit assertion rather than staying
    accidentally-covered."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=100)
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    # No market_regime_rows at all -- every regime label fails the lookup.
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, market_regime_rows=[])
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(
        conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path)
    )

    assert len(conn.guard_fact_inserts) == 1
    subject = conn.guard_fact_inserts[0][1]
    assert subject == "tf=5m|group=_unmapped"
    # Still evaluated (100 cells >= min_cells=100, 100% fail >= 0.995 rail) -> held.
    assert registry.transition_calls == []


def test_regime_shift_two_independent_strata_only_failing_one_holds(tmp_path):
    """(5m, equity) at 100% fail holds; (1h, equity) at 90% fail (within rails)
    does not -- but ANY hold-authoritative stratum holding holds the ENTIRE run
    (all transitions), proving strata are evaluated independently but the hold
    decision is global."""
    regimes = [f"r{i}" for i in range(100)]
    hot_cells = _stratum_cells("featA", "5m", regimes, n_fail=100)
    cold_cells = _stratum_cells("featB", "1h", regimes, n_fail=90)
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(
        hot_cells + cold_cells,
        ensemble_weight_rows=[
            {
                "tf": "5m",
                "regime": r,
                "feature_name": "featA",
                "weight_version": "v1",
                "weight": 0.5,
            }
            for r in regimes
        ],
        market_regime_rows=market_regimes,
    )
    registry = _FakeRegistryService({"featA": {"status": "active"}, "featB": {"status": "active"}})

    _run_lifecycle_hook(
        conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path)
    )

    assert registry.transition_calls == []  # global hold, even though only one stratum tripped
    assert len(conn.guard_fact_inserts) == 2  # both strata still wrote calibration facts


def test_guard_facts_deferred_past_registry_triggered_commit(tmp_path):
    """Regression for the atomicity bug found in todo 144's final review:
    FeatureRegistryService.record_transition_sync/advance_shadow_counters_sync
    each wrap their own SQL in `with conn:` on the SAME write_conn, which commits
    immediately on exit -- eagerly writing guard facts inside Step 3's loop (the
    original, buggy shape) would let the FIRST such registry call silently
    commit or roll back those facts before the hook's own intended single commit
    point. The fix defers the guard-fact writes past Step 4/5 entirely.

    This test's stratum (10 cells, below guard_min_cells=100) is never
    hold-authoritative, so Step 4 runs and a genuine demotion fires
    record_transition_sync -- triggering a REAL commit() call via the fake
    registry's with-conn simulation (see _FakeRegistryService above) mid-run.
    Asserts the ordering directly: the registry-triggered commit must appear in
    the event log BEFORE the guard-fact INSERT, proving the write was deferred
    past it rather than landing eagerly beforehand. A regression back to eager
    per-stratum writes (todo 144's original defect) would reverse this order
    and fail this assertion, even though every other test in this file (whose
    fakes only check final state, not commit ordering) would still pass."""
    regimes = [f"regime_{i}" for i in range(10)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=6)  # 60% >= 50% demote floor
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, market_regime_rows=market_regimes)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(
        conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path)
    )

    # Demotion actually happened -- proves record_transition_sync ran and
    # triggered its own commit() via the fake's with-conn simulation.
    assert len(registry.transition_calls) == 1
    assert registry.transition_calls[0][:4] == ("featA", "active", "shadow_only", "ic_demotion")

    guard_insert_positions = [
        i for i, event in enumerate(conn.event_log) if event[0] == "guard_insert"
    ]
    registry_commit_positions = [
        i
        for i, event in enumerate(conn.event_log)
        if event[0] == "commit" and event[1] < conn.commit_count
    ]
    assert guard_insert_positions, "guard fact was never written"
    assert registry_commit_positions, "registry-triggered commit never fired -- test setup invalid"
    assert max(registry_commit_positions) < min(guard_insert_positions), (
        "guard fact written before (or interleaved eagerly with) a registry-triggered "
        "commit -- this is the exact atomicity defect todo 144's final review found"
    )


def test_regime_shift_empirical_band_takes_over_after_min_history(tmp_path):
    """A stratum with 8 prior evaluations all near 0.96 develops a tight empirical
    band; a new fraction of 0.994 (inside the seeded rail 0.995, but outside the
    tightened empirical band) now holds -- proving the empirical layer, not just
    the rails, is live."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=99)  # 0.99 fraction this run
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    history_rows = [
        {"subject": "tf=5m|group=equity", "metric_value": v}
        for v in [0.960, 0.961, 0.960, 0.962, 0.959, 0.961, 0.960, 0.961]
    ]
    conn = _FakeLifecycleConn(
        cells,
        ensemble_weight_rows=ew,
        market_regime_rows=market_regimes,
        guard_history_rows=history_rows,
    )
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(
        conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path)
    )

    assert registry.transition_calls == []  # held: 0.99 is far outside the tight empirical band


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
    config = _make_config(
        lookahead_mid={"5m": 5, "15m": 2, "1h": 2, "1d": 2},
        meta_fdr_min_fraction=0.50,
    )
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
    # A 15m row at lookahead_bars=5 -- same bar count as 5m's mid, but 15m's real mid
    # is 2. This row must NOT be picked up by the gate query; if it were, it would
    # prove the filter is still matching on lookahead_bars alone, ignoring tf.
    cells.append(
        _cell(
            "featB",
            "15m",
            "r0",
            ic_ci_lower=0.03,
            passes_fdr=True,
            n_independent=9999,
            status="shadow_only",
            lookahead_bars=5,
        )
    )
    conn = _FakeLifecycleConn(cells)
    registry = _FakeRegistryService({"featB": {"status": "shadow_only", "eligible": False}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.advance_calls == [
        ("featB", True, 4000)
    ]  # 4 real 5m-mid cells * 1000; the mis-tf'd 15m/lookahead=5 row (n=9999) must be excluded


# ---------------------------------------------------------------------------
# Fable N4: weight_version pinning to the APR champion
# ---------------------------------------------------------------------------


def test_weight_version_pinning_to_champion(tmp_path):
    """Standing-weight lookup must resolve config.ensemble_weight_version ('v1'), not
    the most-recent-by-computed_at row (a newer 'v2_challenger' weight_version)."""
    config = _make_config(ensemble_weight_version="v1")
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
    config = _make_config(meta_fdr_min_fraction=0.50, sign_symmetric=True)
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
    config = _make_config(meta_fdr_min_fraction=0.50, sign_symmetric=True)
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
    config = _make_config(meta_fdr_min_fraction=0.50, sign_symmetric=True)
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
    config = _make_config(meta_fdr_min_fraction=0.50, sign_symmetric=False)
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
    # Covers both _run_lifecycle_hook and _apply_feature_transitions (Step 4/5,
    # extracted out of the hook by the todo 144 /simplify pass) -- the sync
    # invariant applies to the whole call chain, not just the outer function.
    for fn in (_run_lifecycle_hook, _apply_feature_transitions):
        source = inspect.getsource(fn)
        assert "await" not in source
        assert "async def" not in source


def test_hook_never_writes_ensemble_weights_source():
    for fn in (_run_lifecycle_hook, _apply_feature_transitions):
        source = inspect.getsource(fn)
        assert "INSERT INTO ensemble_weights" not in source
        assert "UPDATE ensemble_weights" not in source


def test_hook_uses_meta_fdr_min_fraction_from_config():
    # meta_fdr_min_fraction lives in _apply_feature_transitions (Step 4/5),
    # extracted out of _run_lifecycle_hook by the todo 144 /simplify pass.
    source = inspect.getsource(_apply_feature_transitions)
    assert "meta_fdr_min_fraction" in source


def test_hook_filters_lookahead_bars_and_never_orders_by_computed_at():
    source = inspect.getsource(_run_lifecycle_hook)
    assert "lookahead_bars" in source
    assert "ORDER BY computed_at DESC LIMIT 1" not in source
