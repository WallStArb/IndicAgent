#!/usr/bin/env python3
"""
Phase 107 Service Inventory Audit Script.

Inventories ALL deployed services and their compliance state per HYGIENE criterion:
- HYGIENE-07: BaseAgent adoption
- HYGIENE-08: DatabaseManager usage
- HYGIENE-09: agent_id label consistency
- HYGIENE-01: Writer flush spans
- HYGIENE-02: Metric type violations

Outputs a markdown table to 107-00-SERVICE-INVENTORY.md with compliance status.
"""

import os
import re
import subprocess
import sys
from pathlib import Path


def discover_services() -> list[str]:
    """Discover all deployed indicagent systemd units."""
    result = subprocess.run(
        ["systemctl", "list-units", "--all", "indicagent-*"],
        capture_output=True,
        text=True,
    )
    services = []
    for line in result.stdout.splitlines():
        # Skip header and empty lines
        if not line.strip() or "UNIT" in line:
            continue
        # Extract unit name (first column)
        parts = line.split()
        if parts:
            unit = parts[0].lstrip("●").strip()  # Remove bullet for failed units
            # Filter out timers and targets
            if (
                unit.startswith("indicagent-")
                and not unit.endswith(".timer")
                and not unit.endswith(".target")
            ):
                services.append(unit.removesuffix(".service"))
    return sorted(services)


def find_service_file(service_name: str) -> Path | None:
    """Find the Python file for a given service name."""
    # Convert service name to potential file paths
    # e.g., indicagent-intelligence-pipeline -> intelligence_pipeline_agent.py

    # Remove indicagent- prefix and convert to snake_case
    name_part = service_name.replace("indicagent-", "")
    snake_name = name_part.replace("-", "_")

    # Try common patterns
    candidates = [
        f"services/{snake_name}.py",
        f"services/{snake_name}_agent.py",
        f"services/{snake_name}_service.py",
    ]

    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path

    return None


def check_base_agent(file_path: Path) -> bool:
    """Check if file contains class inheriting from BaseAgent."""
    try:
        content = file_path.read_text()
        # Look for class XAgent(BaseAgent) or class XAgent(BaseWriterAgent)
        return bool(
            re.search(r"class\s+\w*Agent\s*\(.*BaseAgent", content)
            or re.search(r"class\s+\w*Agent\s*\(.*BaseWriterAgent", content)
        )
    except Exception:
        return False


def check_database_manager(file_path: Path) -> bool:
    """Check if file uses DatabaseManager (not asyncpg.create_pool bypass)."""
    try:
        content = file_path.read_text()
        # Check for database_manager import (good)
        has_db_manager = "from src.core.database_manager import" in content
        # Check for asyncpg.create_pool bypass (bad)
        has_bypass = "asyncpg.create_pool" in content
        # Return True if uses database_manager properly
        return has_db_manager and not has_bypass
    except Exception:
        return False


def check_agent_id_label(file_path: Path) -> tuple[bool, str]:
    """Check metric label consistency for agent_id.

    Returns:
        (is_consistent, label_key_used) - is_consistent is True if only one label key used
    """
    try:
        content = file_path.read_text()
        # Count occurrences of each label key
        agent_count = len(re.findall(r'"agent":\s*\w+', content))
        agent_id_count = len(re.findall(r'"agent_id":\s*\w+', content))

        if agent_count > 0 and agent_id_count > 0:
            return (False, "mixed")
        elif agent_count > 0:
            return (True, "agent")
        elif agent_id_count > 0:
            return (True, "agent_id")
        else:
            return (True, "none")  # No metrics defined
    except Exception:
        return (False, "error")


def check_flush_span(file_path: Path) -> tuple[bool, str]:
    """Check if writer file uses observed_span for flush operations.

    Returns:
        (has_span, status) - status is "yes", "no", or "not_writer"
    """
    try:
        content = file_path.read_text()
        # Check if this is a writer agent
        is_writer = "Writer" in file_path.stem or "writer" in file_path.stem

        if not is_writer:
            return (False, "N/A")

        # Look for observed_span or start_as_current_span with flush
        has_flush_span = bool(
            re.search(r"observed_span.*flush|start_as_current_span.*flush", content)
        )

        return (has_flush_span, "yes" if has_flush_span else "no")
    except Exception:
        return (False, "error")


def check_metric_types(file_path: Path) -> tuple[bool, str]:
    """Check for metric type violations.

    Returns:
        (is_compliant, status) - status describes any violations found
    """
    try:
        content = file_path.read_text()

        violations = []

        # Check for shadow metrics as up_down_counter (should be point_gauge)
        if re.search(
            r"create_up_down_counter.*shadow_(n_resolved|win_rate|ev_r|ev_ci_lower|days_to_gate)",
            content,
            re.IGNORECASE,
        ):
            violations.append("shadow as up_down_counter")

        # Check for latency as counter (should be histogram)
        if re.search(r"create_counter.*latency", content, re.IGNORECASE):
            violations.append("latency as counter")

        return (len(violations) == 0, ", ".join(violations) if violations else "ok")
    except Exception:
        return (False, "error")


def audit_service(service_name: str) -> dict[str, str]:
    """Audit a single service for all HYGIENE criteria."""
    file_path = find_service_file(service_name)

    if file_path is None:
        return {
            "service": service_name,
            "file": "NOT FOUND",
            "base_agent": "ERROR",
            "db_manager": "ERROR",
            "agent_id": "ERROR",
            "flush_span": "N/A",
            "metric_types": "ERROR",
        }

    # BaseAgent check
    base_agent = "GREEN" if check_base_agent(file_path) else "RED"

    # DatabaseManager check (only applicable for DB services)
    is_db_service = any(
        term in file_path.stem for term in ["writer", "pipeline", "compute", "tracker", "auditor"]
    )
    if is_db_service:
        db_manager = "GREEN" if check_database_manager(file_path) else "RED"
    else:
        db_manager = "N/A"

    # agent_id label check
    agent_id_consistent, agent_id_label = check_agent_id_label(file_path)
    agent_id = "GREEN" if agent_id_consistent else f"RED ({agent_id_label})"

    # Flush span check
    has_flush_span, flush_span_status = check_flush_span(file_path)
    if flush_span_status == "N/A":
        flush_span = "N/A"
    else:
        flush_span = "GREEN" if has_flush_span else "RED"

    # Metric types check
    metric_types_compliant, metric_types_status = check_metric_types(file_path)
    metric_types = "GREEN" if metric_types_compliant else f"RED ({metric_types_status})"

    return {
        "service": service_name,
        "file": str(file_path),
        "base_agent": base_agent,
        "db_manager": db_manager,
        "agent_id": agent_id,
        "flush_span": flush_span,
        "metric_types": metric_types,
    }


def generate_inventory_report(services: list[dict[str, str]]) -> str:
    """Generate markdown inventory report."""
    lines = [
        "# Phase 107 Service Inventory",
        "",
        f"**Generated:** {os.popen('date -u +"%Y-%m-%d %H:%M:%S UTC"').read().strip()}",
        f"**Total services:** {len(services)}",
        "",
        "## Compliance Matrix",
        "",
        "| Service | BaseAgent | DB Pool | agent_id | Flush Span | Metric Types | Notes |",
        "|---------|-----------|---------|----------|------------|--------------|-------|",
    ]

    for svc in services:
        notes = ""
        if svc["file"] == "NOT FOUND":
            notes = "File not found"
        lines.append(
            f"| {svc['service']} | {svc['base_agent']} | {svc['db_manager']} | "
            f"{svc['agent_id']} | {svc['flush_span']} | {svc['metric_types']} | {notes} |"
        )

    # Summary statistics
    lines.extend(
        [
            "",
            "## Summary Statistics",
            "",
        ]
    )

    # BaseAgent
    base_agent_green = sum(1 for s in services if s["base_agent"] == "GREEN")
    base_agent_total = sum(1 for s in services if s["base_agent"] in ("GREEN", "RED"))
    lines.extend(
        [
            f"**BaseAgent:** {base_agent_green}/{base_agent_total} compliant",
        ]
    )

    # DatabaseManager
    db_green = sum(1 for s in services if s["db_manager"] == "GREEN")
    db_total = sum(1 for s in services if s["db_manager"] in ("GREEN", "RED"))
    if db_total > 0:
        lines.append(f"**DatabaseManager:** {db_green}/{db_total} compliant")

    # agent_id label
    agent_id_green = sum(1 for s in services if s["agent_id"] == "GREEN")
    agent_id_total = sum(1 for s in services if "GREEN" in s["agent_id"] or "RED" in s["agent_id"])
    if agent_id_total > 0:
        lines.append(f"**agent_id label:** {agent_id_green}/{agent_id_total} consistent")

    # Flush span
    flush_green = sum(1 for s in services if s["flush_span"] == "GREEN")
    flush_total = sum(1 for s in services if s["flush_span"] in ("GREEN", "RED"))
    if flush_total > 0:
        lines.append(f"**Flush span coverage:** {flush_green}/{flush_total} writers")

    # Metric types
    metric_green = sum(1 for s in services if s["metric_types"] == "GREEN")
    metric_total = sum(
        1 for s in services if "GREEN" in s["metric_types"] or "RED" in s["metric_types"]
    )
    if metric_total > 0:
        lines.append(f"**Metric types:** {metric_green}/{metric_total} compliant")

    # File not found count
    missing_files = sum(1 for s in services if s["file"] == "NOT FOUND")
    if missing_files > 0:
        lines.append(f"**Missing files:** {missing_files} services")

    return "\n".join(lines)


def main():
    """Main entry point."""
    print("Discovering services...")
    services = discover_services()
    print(f"Found {len(services)} services")

    print("Auditing services...")
    audit_results = []
    missing_count = 0
    for service in services:
        print(f"  Auditing {service}...")
        result = audit_service(service)
        audit_results.append(result)
        if result["file"] == "NOT FOUND":
            missing_count += 1

    print("Generating report...")
    report = generate_inventory_report(audit_results)

    # Write report
    output_path = Path(".planning/phases/107-infrastructure-hygiene/107-00-SERVICE-INVENTORY.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)

    print(f"Report written to {output_path}")

    # Exit with code 1 if any service file not found
    if missing_count > 0:
        print(f"ERROR: {missing_count} service files not found")
        sys.exit(1)

    print("Audit complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
