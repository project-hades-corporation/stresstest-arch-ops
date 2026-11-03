"""Render and persist detailed Markdown reports for deterministic stress runs."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ARCHITECTURE_NAME = "Default architecture"
DEFAULT_REPORT_FILENAME = "stress-report.md"


def _cell(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def architecture_slug(architecture_name: str | None) -> str:
    """Return a filesystem-safe slug for an architecture name."""
    slug = re.sub(r"[^a-z0-9]+", "-", (architecture_name or "").strip().lower()).strip("-")
    return slug[:80].strip("-") or "architecture"


def report_filename(architecture_name: str | None) -> str:
    """Map an architecture name to its report file.

    The default name keeps the legacy ``stress-report.md`` filename so existing
    single-architecture setups keep working. Named architectures get a dedicated
    ``stress-report-<slug>.md`` file, which is replaced only when the same name is
    simulated again.
    """
    if not (architecture_name or "").strip():
        return DEFAULT_REPORT_FILENAME
    return f"stress-report-{architecture_slug(architecture_name)}.md"


def _format_rps(value: Any) -> str:
    return "Unknown" if value is None else f"{value:g} RPS"


def _format_utilization(value: Any) -> str:
    return "Unknown" if value is None else f"{value:.0%}"


def render_report(
    result: dict[str, Any],
    architecture_name: str | None = None,
    filename: str | None = None,
) -> str:
    nodes = result["topology"]["nodes"]
    edges = result["topology"]["edges"]
    labels = {node["id"]: node["label"] for node in nodes}
    scenario = result["scenario_config"]
    recommendations = result["recommendations"]
    display_name = (architecture_name or "").strip() or DEFAULT_ARCHITECTURE_NAME
    report_file = filename or report_filename(architecture_name)
    status_counts = {
        status: sum(node["status"] == status for node in nodes)
        for status in ("CRITICAL", "WARNING", "OK")
    }
    findings = [
        recommendation
        for recommendation in recommendations
        if recommendation["severity"] != "INFO"
    ]
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lines = [
        "# Architecture Stress Test Report",
        "",
        f"- **Generated (UTC):** {generated_at}",
        f"- **Architecture:** {_cell(display_name)}",
        f"- **Report file:** `reports/{report_file}` "
        "(replaced only when this architecture is simulated again)",
        f"- **Scenario:** {_cell(result['scenario'])}",
        f"- **Overall result:** {status_counts['CRITICAL']} critical component(s), "
        f"{status_counts['WARNING']} warning component(s), {len(findings)} actionable finding(s)",
        "",
        "## Executive summary",
        "",
        result["analysis"],
        "",
        "The findings and recommendations below are based on the saved architecture and "
        "scenario inputs. Recommendations are proposals; this report does not modify the architecture.",
        "",
        "## Scenario and assumptions",
        "",
        f"- **Baseline request rate:** {scenario['baseline_rps']:g} RPS per component",
        f"- **Traffic multiplier:** {scenario['traffic_multiplier']:g}x",
        f"- **Estimated request rate:** "
        f"{scenario['baseline_rps'] * scenario['traffic_multiplier']:g} RPS per component",
        f"- **Dropped components:** "
        f"{', '.join(_cell(node_id) for node_id in scenario['dropped_nodes']) or 'None'}",
        f"- **Capacity warning threshold:** {scenario['warning_utilization']:.0%}",
        f"- **Latency thresholds:** warning at {scenario['latency_warning_ms']:g} ms; "
        f"critical at {scenario['latency_critical_ms']:g} ms",
        "",
        "## Architecture inventory",
        "",
        f"**{len(nodes)} component(s)** and **{len(edges)} connection(s)** were included in this run.",
        "",
        "| Component ID | Component | Type | Status | Capacity | Estimated load | Utilization | SPOF |",
        "|---|---|---|---|---:|---:|---:|:---:|",
    ]
    for node in nodes:
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    node["id"],
                    node["label"],
                    node["type"],
                    node["status"],
                    _format_rps(node["capacity_rps"]),
                    _format_rps(node["load_rps"]),
                    _format_utilization(node["utilization"]),
                    "Yes" if node["is_spof"] else "No",
                )
            )
            + " |"
        )

    lines.extend(["", "## Connection assessment", ""])
    if edges:
        lines.extend(
            [
                "| Source | Target | Protocol | Latency | Status |",
                "|---|---|---|---:|---|",
            ]
        )
        for edge in edges:
            lines.append(
                "| "
                + " | ".join(
                    _cell(value)
                    for value in (
                        edge["source"],
                        edge["target"],
                        edge.get("protocol", "unspecified"),
                        f"{edge['latency_ms']:g} ms",
                        edge["status"],
                    )
                )
                + " |"
            )
    else:
        lines.append("No connections were detected in the architecture.")

    lines.extend(["", "## Findings and root causes", ""])
    finding_index = 0
    for node in nodes:
        causes = node.get("root_causes") or []
        if not causes:
            continue
        finding_index += 1
        lines.extend(
            [
                f"### {finding_index}. [{node['status']}] {_cell(node['label'])}",
                "",
                f"- **Component ID:** `{_cell(node['id'])}`",
                f"- **Capacity:** {_format_rps(node['capacity_rps'])}",
                f"- **Estimated load:** {_format_rps(node['load_rps'])}",
                f"- **Utilization:** {_format_utilization(node['utilization'])}",
            ]
        )
        lines.extend(f"- **Cause:** {_cell(cause)}" for cause in causes)
        lines.append("")

    for edge in edges:
        if edge["status"] == "OK":
            continue
        finding_index += 1
        lines.extend(
            [
                f"### {finding_index}. [{edge['status']}] "
                f"{_cell(labels.get(edge['source'], edge['source']))} -> "
                f"{_cell(labels.get(edge['target'], edge['target']))}",
                "",
                f"- **Measured topology latency:** {edge['latency_ms']:g} ms",
                f"- **Configured thresholds:** warning {scenario['latency_warning_ms']:g} ms; "
                f"critical {scenario['latency_critical_ms']:g} ms",
                "",
            ]
        )

    if finding_index == 0:
        lines.extend(["No component or connection findings were raised for this scenario.", ""])

    lines.extend(["## Prioritized recommendations", ""])
    if recommendations:
        for index, recommendation in enumerate(recommendations, start=1):
            lines.extend(
                [
                    f"### {index}. {recommendation['priority']} — "
                    f"[{recommendation['severity']}] {recommendation['category']}: "
                    f"{_cell(recommendation['component'])}",
                    "",
                    f"**Finding:** {_cell(recommendation['finding'])}",
                    "",
                    "**Recommended actions:**",
                ]
            )
            lines.extend(f"{action_index}. {_cell(action)}" for action_index, action in enumerate(recommendation["actions"], start=1))
            lines.append("")
    else:
        lines.extend(["No recommendations were generated.", ""])

    lines.extend(
        [
            "## Methodology and limitations",
            "",
            "- This is a deterministic topology estimate, not a live load test or measured production telemetry.",
            "- The current model applies the same baseline request rate, multiplied by the scenario factor, to every component; it does not infer per-route traffic, fan-out, queue depth, retries, or autoscaling behavior.",
            "- Capacity utilization is calculated only when `capacity_rps` is provided. Missing or zero capacity is reported as unknown, not as unlimited capacity.",
            "- Single points of failure are inferred from directed source-to-sink reachability in the topology graph; the model does not validate deployment zones, replicas, health checks, or failover configuration.",
            "- Connection latency uses values present in the topology metadata. Missing latency is treated as zero by the estimator and is not evidence that the dependency is latency-free.",
            "- Validate proposed changes with workload-specific load tests, failure-injection exercises, service-level objectives, and operational review before deployment.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(
    report_directory: Path,
    result: dict[str, Any],
    architecture_name: str | None = None,
) -> tuple[str, str]:
    """Write the report for one architecture and return (filename, markdown)."""
    filename = report_filename(architecture_name)
    report_directory.mkdir(parents=True, exist_ok=True)
    report_path = report_directory / filename
    markdown = render_report(result, architecture_name, filename)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=report_directory,
            prefix="stress-report-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(markdown)
        os.replace(temporary_path, report_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return filename, markdown
