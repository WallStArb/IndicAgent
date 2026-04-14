"""Smoke tests for Grafana dashboard JSON files."""
import json
import pathlib


def test_operations_json_parses_and_has_required_rows():
    """operations.json must parse and contain required row titles."""
    data = json.loads(pathlib.Path("production/grafana/dashboards/operations.json").read_text())
    assert data.get("title") is not None
    panels = data.get("panels", [])
    panel_titles = [p.get("title", "") for p in panels]
    # Verify required row/panel titles exist
    assert any("Service Health" in t or "service_health" in t.lower() for t in panel_titles), \
        "Missing 'Service Health' row/panel"
    assert any("Data Quality" in t or "data_quality" in t.lower() or "completeness" in t.lower() for t in panel_titles), \
        "Missing 'Data Quality' row/panel"


def test_operations_json_no_archived_service_names():
    """operations.json must not reference archived service names."""
    raw = pathlib.Path("production/grafana/dashboards/operations.json").read_text()
    archived_names = [
        "feature_compute_agent",
        "signal_generator_agent",
        "feature_compute_service",
        "lifecycle_tracker",
        "indicagent-lifecycle-tracker",
        "bar_replay",
        "indicator_service",
        "market_analysis_service",
        "generator_service",
        "tracker_service",
        "lifecycle_service",
    ]
    for name in archived_names:
        assert name not in raw, f"Archived name '{name}' found in operations.json"


def test_pipeline_health_json_parses_and_has_latency_row():
    """pipeline-health.json must parse and contain latency/throughput rows."""
    data = json.loads(pathlib.Path("production/grafana/dashboards/pipeline-health.json").read_text())
    assert data.get("title") is not None
    panels = data.get("panels", [])
    panel_titles = [p.get("title", "") for p in panels]
    assert any("latency" in t.lower() or "p95" in t.lower() or "Latency" in t for t in panel_titles), \
        "Missing latency row/panel"
    assert any("throughput" in t.lower() or "Throughput" in t for t in panel_titles), \
        "Missing throughput row/panel"


def test_signals_i8_json_parses_and_has_signal_funnel():
    """signals-i8.json must parse and contain signal funnel row."""
    data = json.loads(pathlib.Path("production/grafana/dashboards/signals-i8.json").read_text())
    assert data.get("title") is not None
    panels = data.get("panels", [])
    panel_titles = [p.get("title", "") for p in panels]
    assert any("funnel" in t.lower() or "generated" in t.lower() or "Signal" in t for t in panel_titles), \
        "Missing signal funnel row/panel"


def test_service_overview_json_removed():
    """service-overview.json must be removed (replaced by operations.json)."""
    path = pathlib.Path("production/grafana/dashboards/service-overview.json")
    assert not path.exists(), "service-overview.json must be removed (replaced by operations.json)"


def test_no_dashboard_has_archived_service_names():
    """No dashboard JSON may reference archived service names."""
    archived = [
        "feature_compute_agent", "signal_generator_agent",
        "feature_compute_service", "lifecycle_tracker",
        "indicagent-lifecycle-tracker", "bar_replay",
        "indicator_service", "market_analysis_service",
        "generator_service", "tracker_service", "lifecycle_service",
    ]
    dashboard_dir = pathlib.Path("production/grafana/dashboards")
    for jf in dashboard_dir.glob("*.json"):
        raw = jf.read_text()
        for name in archived:
            assert name not in raw, f"Archived name '{name}' found in {jf.name}"
