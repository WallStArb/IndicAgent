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
