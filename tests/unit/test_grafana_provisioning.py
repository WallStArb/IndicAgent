"""Tests for Grafana provisioning YAML files."""

import pathlib

import yaml


def test_contact_points_example_valid_yaml():
    """Smoke test that contact-points.example.yml parses as valid YAML with required keys."""
    path = pathlib.Path("production/grafana/provisioning/alerting/contact-points.example.yml")
    data = yaml.safe_load(path.read_text())
    assert "contactPoints" in data or "apiVersion" in data
    contact_names = [cp["name"] for cp in data.get("contactPoints", [])]
    assert "telegram-critical" in contact_names
    assert "discord-ops" in contact_names


def test_alert_rules_valid_yaml_and_complete():
    """Smoke test that alert-rules.yml parses as valid YAML and contains all required rules."""
    data = yaml.safe_load(
        pathlib.Path("production/grafana/provisioning/alerting/alert-rules.yml").read_text()
    )
    groups = data.get("groups", [])
    assert len(groups) >= 1
    all_rule_names = [r["title"] for g in groups for r in g.get("rules", [])]
    required = [
        "provider_dead",
        "service_crash_looping",
        "signals_dropped",
        "signal_dlq_growing",
        "data_completeness_critical",
        "consumer_lag_writer",
        "bar_flow_stale",
        "output_buffer_pressure",
        "gap_fill_dlq_growing",
        "data_completeness_soft",
    ]
    for name in required:
        assert name in all_rule_names, f"Missing rule: {name}"
