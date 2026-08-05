"""Unit tests for FeatureRegistryService.

Tests cover:
- get_active_features() returns all non-deprecated features
- get_all_features() returns ALL features including deprecated ones
- get_ic_sharpe_gate() returns per-feature override if set, else global default
- load() raises RuntimeError when row count != 61
"""

from __future__ import annotations

import pytest

from src.intelligence.feature_registry_service import FeatureRegistryService

_REGISTRY_ROW_COUNT = 61


def _make_rows(n: int, *, with_deprecated: bool = False) -> list[dict]:
    """Build n synthetic feature registry rows for testing."""
    rows = []
    for i in range(n):
        status = "deprecated" if (with_deprecated and i == 0) else "active"
        rows.append(
            {
                "feature_name": f"feature_{i:03d}",
                "group_name": "momentum",
                "tier": "0_atomic",
                "status": status,
                "min_ic_sharpe": None,
                "min_ic_n": 100,
                "fdr_required": True,
                "fdr_alpha": 0.05,
            }
        )
    return rows


def _load_service_from_rows(
    rows: list[dict], sharpe_default: float = 0.5
) -> FeatureRegistryService:
    """Manually populate a FeatureRegistryService without DB calls."""
    svc = FeatureRegistryService()
    svc._features = {r["feature_name"]: r for r in rows}
    svc._min_ic_sharpe_default = sharpe_default
    svc._loaded = True
    return svc


class TestGetActiveFeatures:
    def test_returns_all_non_deprecated(self):
        rows = _make_rows(_REGISTRY_ROW_COUNT, with_deprecated=True)
        svc = _load_service_from_rows(rows)
        active = svc.get_active_features()
        assert len(active) == _REGISTRY_ROW_COUNT - 1
        assert all(f["status"] != "deprecated" for f in active)

    def test_deprecated_excluded(self):
        rows = _make_rows(5, with_deprecated=True)
        svc = _load_service_from_rows(rows)
        # Manually set correct count to avoid load gate; patch _loaded
        svc._features = {r["feature_name"]: r for r in rows}
        svc._loaded = True
        active = svc.get_active_features()
        assert "feature_000" not in {f["feature_name"] for f in active}

    def test_tier_filter_applied(self):
        rows = _make_rows(_REGISTRY_ROW_COUNT)
        rows[0]["tier"] = "2_theory"
        svc = _load_service_from_rows(rows)
        theory = svc.get_active_features(tier="2_theory")
        assert len(theory) == 1
        assert theory[0]["feature_name"] == "feature_000"

    def test_raises_if_not_loaded(self):
        svc = FeatureRegistryService()
        with pytest.raises(RuntimeError, match="not loaded"):
            svc.get_active_features()


class TestGetAllFeatures:
    def test_returns_all_including_deprecated(self):
        rows = _make_rows(_REGISTRY_ROW_COUNT, with_deprecated=True)
        svc = _load_service_from_rows(rows)
        all_feats = svc.get_all_features()
        assert len(all_feats) == _REGISTRY_ROW_COUNT
        names = {f["feature_name"] for f in all_feats}
        assert "feature_000" in names  # the deprecated one

    def test_deprecated_included_in_all_features(self):
        rows = _make_rows(5, with_deprecated=True)
        svc = _load_service_from_rows(rows)
        all_feats = svc.get_all_features()
        deprecated = [f for f in all_feats if f["status"] == "deprecated"]
        assert len(deprecated) == 1

    def test_tier_filter_on_all_features(self):
        rows = _make_rows(_REGISTRY_ROW_COUNT, with_deprecated=True)
        rows[0]["tier"] = "2_theory"  # the deprecated row
        svc = _load_service_from_rows(rows)
        theory = svc.get_all_features(tier="2_theory")
        assert len(theory) == 1
        assert theory[0]["status"] == "deprecated"  # still included

    def test_raises_if_not_loaded(self):
        svc = FeatureRegistryService()
        with pytest.raises(RuntimeError, match="not loaded"):
            svc.get_all_features()


class TestGetIcSharpeGate:
    def test_returns_per_feature_override_when_set(self):
        rows = _make_rows(_REGISTRY_ROW_COUNT)
        rows[0]["min_ic_sharpe"] = 0.8
        svc = _load_service_from_rows(rows, sharpe_default=0.5)
        assert svc.get_ic_sharpe_gate("feature_000") == pytest.approx(0.8)

    def test_returns_global_default_when_per_feature_is_none(self):
        rows = _make_rows(_REGISTRY_ROW_COUNT)
        svc = _load_service_from_rows(rows, sharpe_default=0.5)
        assert svc.get_ic_sharpe_gate("feature_001") == pytest.approx(0.5)

    def test_returns_global_default_for_unknown_feature(self):
        rows = _make_rows(_REGISTRY_ROW_COUNT)
        svc = _load_service_from_rows(rows, sharpe_default=0.5)
        assert svc.get_ic_sharpe_gate("nonexistent_feature") == pytest.approx(0.5)


class TestLoadRowCountGate:
    def test_load_sync_raises_on_wrong_row_count(self):
        """load_sync() must raise RuntimeError if DB returns != 61 rows."""
        svc = FeatureRegistryService()

        class _FakeCursor:
            def __init__(self, rows):
                self._rows = rows
                self.description = [
                    type("Col", (), {"__getitem__": lambda s, i: "feature_name"})()
                    for _ in range(8)
                ]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def execute(self, *a, **kw):
                pass

            def fetchall(self):
                return self._rows

            def fetchone(self):
                return ("0.5",)

        class _FakeConn:
            def __init__(self, n_rows):
                self._n_rows = n_rows
                self._call_count = 0

            def cursor(self):
                self._call_count += 1
                if self._call_count == 1:
                    # First call: main registry query — return wrong count
                    rows = [(f"feature_{i}",) + ("x",) * 7 for i in range(self._n_rows)]
                    cur = _FakeCursor(rows)
                    # Patch description to have correct column names
                    cur.description = [
                        type(
                            "D",
                            (),
                            {
                                "__getitem__": lambda self, i: [
                                    "feature_name",
                                    "group_name",
                                    "tier",
                                    "status",
                                    "min_ic_sharpe",
                                    "min_ic_n",
                                    "fdr_required",
                                    "fdr_alpha",
                                ][i]
                            },
                        )()
                        for _ in range(8)
                    ]
                    return cur
                else:
                    # Second call: APR key lookup
                    class _AprCursor:
                        def __enter__(self):
                            return self

                        def __exit__(self, *a):
                            pass

                        def execute(self, *a, **kw):
                            pass

                        def fetchone(self):
                            return ("0.5",)

                    return _AprCursor()

        wrong_count_conn = _FakeConn(n_rows=5)
        with pytest.raises(RuntimeError, match="row count mismatch"):
            svc.load_sync(wrong_count_conn)


class TestGetStatus:
    def test_returns_status_for_known_feature(self):
        rows = _make_rows(_REGISTRY_ROW_COUNT)
        rows[2]["status"] = "shadow_only"
        svc = _load_service_from_rows(rows)
        assert svc.get_status("feature_002") == "shadow_only"

    def test_returns_none_for_unknown_feature(self):
        rows = _make_rows(_REGISTRY_ROW_COUNT)
        svc = _load_service_from_rows(rows)
        assert svc.get_status("ghost_feature") is None


class TestRecordTransitionIsSync:
    def test_record_transition_is_not_async(self):
        """Verify record_transition() is a synchronous method."""
        import inspect

        from src.intelligence.feature_registry_service import FeatureRegistryService

        assert not inspect.iscoroutinefunction(FeatureRegistryService.record_transition)

    def test_write_transition_record_is_async(self):
        """Verify _write_transition_record() is async."""
        import inspect

        from src.intelligence.feature_registry_service import FeatureRegistryService

        assert inspect.iscoroutinefunction(FeatureRegistryService._write_transition_record)


# ---------------------------------------------------------------------------
# Fake psycopg-style connection/cursor for record_transition_sync tests
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Records executed statements; rowcount is scripted per-connection."""

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn
        self.rowcount: int | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        stmt_index = len(self._conn.executed)
        self._conn.executed.append((" ".join(sql.split()), params))
        if sql.strip().upper().startswith("UPDATE"):
            self.rowcount = self._conn.update_rowcount
        else:
            self.rowcount = 1
        if self._conn.raise_on_statement_index == stmt_index:
            raise RuntimeError("simulated mid-transaction failure")


class _FakeTransaction:
    """Mirrors psycopg's conn.transaction() semantics: commits on clean exit,
    rolls back and re-raises on exception. Deliberately NOT the connection's own
    __enter__/__exit__ (bare `with conn:`) -- psycopg (unlike psycopg2) closes
    the connection on that exit, which would break record_transition_sync's real
    caller (ic_engine reuses the same connection across many features per run)."""

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def __enter__(self) -> _FakeTransaction:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> bool:
        if exc_type is None:
            self._conn.committed = True
        else:
            self._conn.rolled_back = True
        return False  # never swallow — mirrors psycopg propagation


class _FakeConn:
    """No real DB touched. See _FakeTransaction for commit/rollback semantics."""

    def __init__(
        self,
        update_rowcount: int = 1,
        raise_on_statement_index: int | None = None,
    ) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self.update_rowcount = update_rowcount
        self.raise_on_statement_index = raise_on_statement_index
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction(self)


def _feature_row(
    feature_name: str = "momentum_z_fast",
    status: str = "active",
    consecutive_shadow_passes: int = 0,
    observations_since_demotion: int = 0,
) -> dict:
    return {
        "feature_name": feature_name,
        "group_name": "momentum",
        "tier": "0_atomic",
        "status": status,
        "min_ic_sharpe": None,
        "min_ic_n": 100,
        "fdr_required": True,
        "fdr_alpha": 0.05,
        "consecutive_shadow_passes": consecutive_shadow_passes,
        "observations_since_demotion": observations_since_demotion,
    }


class TestRecordTransitionSync:
    def test_transactional_insert_and_update_commit(self):
        row = _feature_row(status="active")
        svc = _load_service_from_rows([row])
        conn = _FakeConn(update_rowcount=1)

        result = svc.record_transition_sync(
            conn,
            "momentum_z_fast",
            from_status="active",
            to_status="shadow_only",
            reason="ic_demotion",
        )

        assert result is True
        assert conn.committed is True
        assert conn.rolled_back is False
        # UPDATE then INSERT, in that order, in ONE transaction.
        assert len(conn.executed) == 2
        assert conn.executed[0][0].upper().startswith("UPDATE FEATURE_REGISTRY")
        assert conn.executed[1][0].upper().startswith("INSERT INTO FEATURE_TRANSITION_LOG")

    def test_rollback_on_mid_transaction_error(self):
        row = _feature_row(status="active")
        svc = _load_service_from_rows([row])
        # Raise on the second execute() call (index 1, the INSERT).
        conn = _FakeConn(update_rowcount=1, raise_on_statement_index=1)

        with pytest.raises(RuntimeError, match="simulated mid-transaction failure"):
            svc.record_transition_sync(
                conn,
                "momentum_z_fast",
                from_status="active",
                to_status="shadow_only",
                reason="ic_demotion",
            )

        assert conn.rolled_back is True
        assert conn.committed is False
        # Cache must NOT reflect the failed transition.
        assert svc.get_status("momentum_z_fast") == "active"

    def test_optimistic_lock_noop_on_rowcount_zero(self):
        row = _feature_row(status="active")
        svc = _load_service_from_rows([row])
        # Simulate feature already transitioned by a concurrent/prior write:
        # the UPDATE's WHERE status = from_status matches zero rows.
        conn = _FakeConn(update_rowcount=0)

        result = svc.record_transition_sync(
            conn,
            "momentum_z_fast",
            from_status="active",
            to_status="shadow_only",
            reason="ic_demotion",
        )

        assert result is False
        # No orphan transition-log row: only the UPDATE executed, not the INSERT.
        assert len(conn.executed) == 1
        assert conn.rolled_back is True
        assert conn.committed is False
        # DB (cache) left untouched.
        assert svc.get_status("momentum_z_fast") == "active"

    def test_rejects_automated_transition_to_deprecated(self):
        row = _feature_row(status="shadow_only")
        svc = _load_service_from_rows([row])
        conn = _FakeConn()

        with pytest.raises(ValueError, match="operator-only"):
            svc.record_transition_sync(
                conn,
                "momentum_z_fast",
                from_status="shadow_only",
                to_status="deprecated",
                reason="ic_demotion",
            )

        # Zero writes attempted before the guard raises.
        assert conn.executed == []

    def test_operator_override_to_deprecated_is_allowed(self):
        row = _feature_row(status="shadow_only")
        svc = _load_service_from_rows([row])
        conn = _FakeConn(update_rowcount=1)

        result = svc.record_transition_sync(
            conn,
            "momentum_z_fast",
            from_status="shadow_only",
            to_status="deprecated",
            reason="operator_override",
        )

        assert result is True
        assert svc.get_status("momentum_z_fast") == "deprecated"

    def test_cache_coherency_after_commit(self):
        row = _feature_row(status="shadow_only")
        svc = _load_service_from_rows([row])
        conn = _FakeConn(update_rowcount=1)

        svc.record_transition_sync(
            conn,
            "momentum_z_fast",
            from_status="shadow_only",
            to_status="active",
            reason="ic_promotion",
        )

        # Same-invocation read sees fresh state immediately, not stale.
        assert svc._features["momentum_z_fast"]["status"] == "active"
        assert svc.get_status("momentum_z_fast") == "active"

    def test_counter_reset_on_second_demotion(self):
        # Feature already satisfied the recovery floors from a PRIOR shadow
        # period (consecutive_shadow_passes=2, observations_since_demotion=5000)
        # and was promoted back to active. It now decays a second time.
        row = _feature_row(
            status="active",
            consecutive_shadow_passes=2,
            observations_since_demotion=5000,
        )
        svc = _load_service_from_rows([row])
        conn = _FakeConn(update_rowcount=1)

        result = svc.record_transition_sync(
            conn,
            "momentum_z_fast",
            from_status="active",
            to_status="shadow_only",
            reason="ic_demotion",
        )

        assert result is True
        # Reset happened in the DB write (the UPDATE statement itself).
        update_sql = conn.executed[0][0]
        assert "consecutive_shadow_passes = 0" in update_sql
        assert "observations_since_demotion = 0" in update_sql
        # Reset happened in the cache too.
        feature = svc._features["momentum_z_fast"]
        assert feature["consecutive_shadow_passes"] == 0
        assert feature["observations_since_demotion"] == 0

    def test_counter_reset_rolled_back_with_rest_of_transaction(self):
        row = _feature_row(
            status="active",
            consecutive_shadow_passes=2,
            observations_since_demotion=5000,
        )
        svc = _load_service_from_rows([row])
        # Fail on the INSERT (index 1) — the whole transaction, including the
        # counter reset issued in the UPDATE, must roll back together.
        conn = _FakeConn(update_rowcount=1, raise_on_statement_index=1)

        with pytest.raises(RuntimeError):
            svc.record_transition_sync(
                conn,
                "momentum_z_fast",
                from_status="active",
                to_status="shadow_only",
                reason="ic_demotion",
            )

        assert conn.rolled_back is True
        feature = svc._features["momentum_z_fast"]
        assert feature["status"] == "active"
        # Cache retains pre-transition counters since nothing committed.
        assert feature["consecutive_shadow_passes"] == 2
        assert feature["observations_since_demotion"] == 5000

    def test_active_to_active_style_update_does_not_touch_counters(self):
        # Promotion (shadow_only -> active) must NOT reset/touch the counters —
        # only demotion into shadow_only does.
        row = _feature_row(
            status="shadow_only",
            consecutive_shadow_passes=2,
            observations_since_demotion=2000,
        )
        svc = _load_service_from_rows([row])
        conn = _FakeConn(update_rowcount=1)

        svc.record_transition_sync(
            conn,
            "momentum_z_fast",
            from_status="shadow_only",
            to_status="active",
            reason="ic_promotion",
        )

        update_sql = conn.executed[0][0]
        assert "consecutive_shadow_passes" not in update_sql
        assert "observations_since_demotion" not in update_sql
        feature = svc._features["momentum_z_fast"]
        assert feature["consecutive_shadow_passes"] == 2
        assert feature["observations_since_demotion"] == 2000


class TestAdvanceShadowCountersSync:
    def test_passing_run_increments_passes_and_adds_observations(self):
        row = _feature_row(
            status="shadow_only",
            consecutive_shadow_passes=1,
            observations_since_demotion=500,
        )
        svc = _load_service_from_rows([row])
        conn = _FakeConn(update_rowcount=1)

        svc.advance_shadow_counters_sync(conn, "momentum_z_fast", passed=True, new_observations=300)

        assert conn.committed is True
        feature = svc._features["momentum_z_fast"]
        assert feature["consecutive_shadow_passes"] == 2
        assert feature["observations_since_demotion"] == 800

    def test_failing_run_resets_passes_but_still_adds_observations(self):
        row = _feature_row(
            status="shadow_only",
            consecutive_shadow_passes=3,
            observations_since_demotion=500,
        )
        svc = _load_service_from_rows([row])
        conn = _FakeConn(update_rowcount=1)

        svc.advance_shadow_counters_sync(
            conn, "momentum_z_fast", passed=False, new_observations=300
        )

        feature = svc._features["momentum_z_fast"]
        assert feature["consecutive_shadow_passes"] == 0
        assert feature["observations_since_demotion"] == 800

    def test_is_one_transaction(self):
        row = _feature_row(status="shadow_only")
        svc = _load_service_from_rows([row])
        conn = _FakeConn(update_rowcount=1)

        svc.advance_shadow_counters_sync(conn, "momentum_z_fast", passed=True, new_observations=100)

        assert len(conn.executed) == 1
        assert conn.committed is True


class TestIsPromotionEligible:
    def test_true_when_both_floors_met(self):
        row = _feature_row(
            status="shadow_only",
            consecutive_shadow_passes=2,
            observations_since_demotion=2000,
        )
        svc = _load_service_from_rows([row])
        assert (
            svc.is_promotion_eligible(
                "momentum_z_fast",
                recovery_min_observations=2000,
                recovery_min_passes=2,
            )
            is True
        )

    def test_false_when_passes_unmet(self):
        row = _feature_row(
            status="shadow_only",
            consecutive_shadow_passes=1,
            observations_since_demotion=2000,
        )
        svc = _load_service_from_rows([row])
        assert (
            svc.is_promotion_eligible(
                "momentum_z_fast",
                recovery_min_observations=2000,
                recovery_min_passes=2,
            )
            is False
        )

    def test_false_when_observations_unmet(self):
        row = _feature_row(
            status="shadow_only",
            consecutive_shadow_passes=2,
            observations_since_demotion=1999,
        )
        svc = _load_service_from_rows([row])
        assert (
            svc.is_promotion_eligible(
                "momentum_z_fast",
                recovery_min_observations=2000,
                recovery_min_passes=2,
            )
            is False
        )

    def test_false_when_neither_met(self):
        row = _feature_row(
            status="shadow_only",
            consecutive_shadow_passes=0,
            observations_since_demotion=0,
        )
        svc = _load_service_from_rows([row])
        assert (
            svc.is_promotion_eligible(
                "momentum_z_fast",
                recovery_min_observations=2000,
                recovery_min_passes=2,
            )
            is False
        )

    def test_reads_floors_from_passed_arguments_not_hardcoded(self):
        # A feature that would fail against the APR defaults (2 / 2000) but
        # passes against a caller-supplied looser floor — proves the floors
        # are NOT hard-coded 2 / 2000 inside the method.
        row = _feature_row(
            status="shadow_only",
            consecutive_shadow_passes=1,
            observations_since_demotion=500,
        )
        svc = _load_service_from_rows([row])
        assert (
            svc.is_promotion_eligible(
                "momentum_z_fast",
                recovery_min_observations=500,
                recovery_min_passes=1,
            )
            is True
        )

    def test_false_for_unknown_feature(self):
        svc = _load_service_from_rows([_feature_row()])
        assert (
            svc.is_promotion_eligible(
                "ghost_feature",
                recovery_min_observations=2000,
                recovery_min_passes=2,
            )
            is False
        )


# ---------------------------------------------------------------------------
# T-151-09: parent_features arity contract (Phase 151 Plan 05)
#
# ROADMAP's Theory-Motivated Interaction Layer design-rules paragraph
# incorrectly says interaction features register with parent_features=[].
# Every live tier='1_interaction' row must carry exactly 2 non-empty
# parent_features (migration 169's own column comment: 1_interaction is "a
# deterministic combination of two tier-0 features").
# scripts/ops/alpha/ops_interaction_primitives_pilot.py's own ValueError
# guard is the second line of defense; this is the first -- modeled on
# tests/unit/test_spread_leg_pair_validity.py's live-DB-read-with-graceful-
# skip shape.
# ---------------------------------------------------------------------------

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"


def _fetch_interaction_rows() -> list[tuple[str, list[str] | None]] | None:
    """Returns [(feature_name, parent_features), ...] for every live
    tier='1_interaction' feature_registry row, or None if the DB is
    unreachable (caller must pytest.skip on None, not fail)."""
    import psycopg

    try:
        conn = psycopg.connect(_LIVE_DB_DSN)
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT feature_name, parent_features FROM feature_registry "
                "WHERE tier = '1_interaction'"
            )
            return cur.fetchall()
    finally:
        conn.close()


def test_every_interaction_row_has_exactly_two_parents():
    """Permanent regression guard: every tier='1_interaction' feature_registry
    row must have exactly 2 parent_features, neither empty/None. Stops a
    future migration from re-introducing ROADMAP's parent_features=[]."""
    rows = _fetch_interaction_rows()
    if rows is None:
        pytest.skip("Cannot connect to the live indicagent DB")

    assert rows, "expected at least one tier='1_interaction' row"
    bad_arity = []
    empty_parent = []
    for feature_name, parent_features in rows:
        if parent_features is None or len(parent_features) != 2:
            bad_arity.append((feature_name, parent_features))
            continue
        if any(not p for p in parent_features):
            empty_parent.append((feature_name, parent_features))

    assert not bad_arity, f"tier=1_interaction rows with parent_features arity != 2: {bad_arity}"
    assert not empty_parent, f"tier=1_interaction rows with an empty parent entry: {empty_parent}"


# ---------------------------------------------------------------------------
# Phase 151 Plan 06: tier='1_interaction' population cap (ROADMAP design rule)
#
# ROADMAP's Theory-Motivated Interaction Layer design rules are explicit: a
# curated layer, NOT a combinatorial factory. A combinatorial candidate pool
# (e.g. ~30K compound candidates run through BH-FDR at alpha=0.05) produces
# ~1,500 expected false discoveries and destroys the correction's power
# guarantees -- the deferred todo 019 design, rejected on statistical-power
# grounds before this phase existed. 50 tests at FDR=0.05 has well-understood
# power; 30K does not. The <=50 cap is the Musk-step-3 "simplify" applied at
# design time, made a permanent machine-enforced invariant here rather than
# staying a prose commitment a future migration can quietly breach.
# ---------------------------------------------------------------------------


def test_interaction_tier_population_within_cap():
    """Permanent cap guard: tier='1_interaction' population must never exceed
    ROADMAP Phase 151's design cap of 50 rows (see module comment above)."""
    import psycopg

    try:
        conn = psycopg.connect(_LIVE_DB_DSN)
    except Exception:
        pytest.skip("Cannot connect to the live indicagent DB")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM feature_registry WHERE tier = '1_interaction'")
            (count,) = cur.fetchone()
    finally:
        conn.close()

    assert count <= 50, (
        f"tier='1_interaction' population is {count}, exceeding ROADMAP Phase 151's "
        "design cap of 50 -- see module comment above for the BH-FDR power rationale"
    )
