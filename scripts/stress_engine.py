"""Deterministically estimate topology stress, bottlenecks, and single points of failure."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def _validate_topology(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes, edges = data.get("nodes"), data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Topology must contain 'nodes' and 'edges' arrays.")
    if not nodes:
        raise ValueError("Topology must contain at least one node.")
    normalized_nodes: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"].strip():
            raise ValueError(f"Node {index} must be an object with a non-empty string 'id'.")
        node_id = node["id"].strip()
        if node_id in ids:
            raise ValueError(f"Duplicate topology node id: {node_id}")
        ids.add(node_id)
        capacity = node.get("capacity_rps", 0)
        if (
            isinstance(capacity, bool)
            or not isinstance(capacity, (int, float))
            or not math.isfinite(capacity)
            or capacity < 0
        ):
            raise ValueError(f"Node {node_id!r} has an invalid capacity_rps.")
        normalized_nodes.append(
            {
                **node,
                "id": node_id,
                "label": str(node.get("label") or node_id),
                "type": str(node.get("type") or "service"),
                "capacity_rps": float(capacity),
            }
        )
    normalized_edges: list[dict[str, Any]] = []
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise ValueError(f"Edge {index} must be an object.")
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str) or source not in ids or target not in ids:
            raise ValueError(f"Edge {index} references an unknown source or target node.")
        latency = edge.get("latency_ms", 0)
        if (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or not math.isfinite(latency)
            or latency < 0
        ):
            raise ValueError(f"Edge {index} has an invalid latency_ms.")
        normalized_edges.append({**edge, "source": source, "target": target, "latency_ms": float(latency)})
    return normalized_nodes, normalized_edges


def _reachability(
    adjacency: dict[str, set[str]], start: str, removed: set[str] | None = None
) -> set[str]:
    excluded = removed or set()
    if start in excluded:
        return set()
    reached: set[str] = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current in reached or current in excluded:
            continue
        reached.add(current)
        pending.extend(adjacency[current] - reached - excluded)
    return reached


def _find_spofs(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> set[str]:
    ids = {node["id"] for node in nodes}
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in ids}
    incoming: dict[str, int] = defaultdict(int)
    for edge in edges:
        adjacency[edge["source"]].add(edge["target"])
        incoming[edge["target"]] += 1
    sources = sorted(node_id for node_id in ids if incoming[node_id] == 0)
    if not sources:
        sources = sorted(ids)
    baseline = {source: _reachability(adjacency, source) for source in sources}
    sinks = {node_id for node_id in ids if not adjacency[node_id]}
    spofs: set[str] = set()
    for candidate in sorted(ids):
        for source, reachable in baseline.items():
            relevant_sinks = reachable & sinks
            if candidate not in reachable:
                continue
            # Losing a source or a reachable sink necessarily loses that service path.
            if candidate == source or candidate in relevant_sinks:
                spofs.add(candidate)
                break
            remaining = _reachability(adjacency, source, {candidate})
            if relevant_sinks - remaining:
                spofs.add(candidate)
                break
    return spofs


def _scenario_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return _read_object(path)


def _positive_number(config: dict[str, Any], key: str, default: float, *, allow_zero: bool = False) -> float:
    value = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Scenario field {key!r} must be a finite number.")
    if value < 0 or (value == 0 and not allow_zero):
        requirement = "non-negative" if allow_zero else "greater than zero"
        raise ValueError(f"Scenario field {key!r} must be {requirement}.")
    return float(value)


def _analyze(topology: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    nodes, edges = _validate_topology(topology)
    traffic_multiplier = _positive_number(scenario, "traffic_multiplier", 1.0)
    baseline_rps = _positive_number(scenario, "baseline_rps", 100.0, allow_zero=True)
    warning_utilization = _positive_number(scenario, "warning_utilization", 0.8)
    if warning_utilization >= 1:
        raise ValueError("Scenario field 'warning_utilization' must be less than 1.")
    latency_warning_ms = _positive_number(scenario, "latency_warning_ms", 100.0, allow_zero=True)
    latency_critical_ms = _positive_number(scenario, "latency_critical_ms", 500.0)
    if latency_critical_ms <= latency_warning_ms:
        raise ValueError("'latency_critical_ms' must be greater than 'latency_warning_ms'.")
    raw_dropped = scenario.get("dropped_nodes", [])
    if not isinstance(raw_dropped, list) or any(not isinstance(node_id, str) for node_id in raw_dropped):
        raise ValueError("Scenario field 'dropped_nodes' must be an array of node IDs.")
    ids = {node["id"] for node in nodes}
    dropped = set(raw_dropped)
    unknown = dropped - ids
    if unknown:
        raise ValueError(f"Scenario drops unknown node(s): {', '.join(sorted(unknown))}")

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in ids}
    incoming: dict[str, int] = defaultdict(int)
    for edge in edges:
        adjacency[edge["source"]].add(edge["target"])
        incoming[edge["target"]] += 1
    sources = sorted(node_id for node_id in ids if incoming[node_id] == 0)
    if not sources:
        sources = sorted(ids)
    before_drop = set().union(*(_reachability(adjacency, source) for source in sources)) if sources else set()
    surviving_sources = [source for source in sources if source not in dropped]
    reachable_after_drop = (
        set().union(*(_reachability(adjacency, source, dropped) for source in surviving_sources))
        if surviving_sources
        else set()
    )
    unavailable = (before_drop - reachable_after_drop) - dropped
    spofs = _find_spofs(nodes, edges)
    reasons: dict[str, list[str]] = {node_id: [] for node_id in sorted(ids)}
    statuses = {node_id: "OK" for node_id in sorted(ids)}

    def mark(node_id: str, status: str, reason: str) -> None:
        priority = {"OK": 0, "WARNING": 1, "CRITICAL": 2}
        if priority[status] > priority[statuses[node_id]]:
            statuses[node_id] = status
        if reason not in reasons[node_id]:
            reasons[node_id].append(reason)

    for node_id in sorted(dropped):
        mark(node_id, "CRITICAL", "Node is explicitly dropped by the scenario.")
    for node_id in unavailable:
        failed = sorted(dropped)
        mark(
            node_id,
            "CRITICAL",
            "Unreachable after dropped node(s): " + ", ".join(failed) + ".",
        )
    for node in nodes:
        node_id = node["id"]
        if node_id in dropped:
            continue
        capacity = node["capacity_rps"]
        load = baseline_rps * traffic_multiplier
        if capacity <= 0:
            mark(node_id, "WARNING", "Capacity is unknown; utilization cannot be evaluated.")
        else:
            utilization = load / capacity
            if utilization >= 1:
                mark(node_id, "CRITICAL", f"Estimated load exceeds capacity ({utilization:.0%} utilization).")
            elif utilization >= warning_utilization:
                mark(node_id, "WARNING", f"Estimated utilization is elevated ({utilization:.0%}).")
        if node_id in spofs:
            mark(node_id, "WARNING", "Single point of failure: removing this component disconnects a source or reachable sink.")

    edge_results: list[dict[str, Any]] = []
    bottlenecks: list[dict[str, Any]] = []
    for edge in edges:
        annotated_edge = dict(edge)
        latency = edge["latency_ms"]
        if latency >= latency_critical_ms:
            edge_status = "CRITICAL"
            reason = f"Edge latency is {latency:g} ms (critical threshold {latency_critical_ms:g} ms)."
        elif latency >= latency_warning_ms and latency > 0:
            edge_status = "WARNING"
            reason = f"Edge latency is {latency:g} ms (warning threshold {latency_warning_ms:g} ms)."
        else:
            edge_status = "OK"
            reason = ""
        annotated_edge["status"] = edge_status
        if reason:
            bottleneck = {
                "source": edge["source"],
                "target": edge["target"],
                "latency_ms": latency,
                "status": edge_status,
            }
            bottlenecks.append(bottleneck)
            mark(edge["source"], edge_status, reason)
            mark(edge["target"], edge_status, reason)
        edge_results.append(annotated_edge)

    annotated_nodes: list[dict[str, Any]] = []
    for node in nodes:
        node_id = node["id"]
        load = baseline_rps * traffic_multiplier
        capacity = node["capacity_rps"]
        annotated_node = {
            **node,
            "load_rps": round(load, 3),
            "utilization": round(load / capacity, 4) if capacity > 0 else None,
            "status": statuses[node_id],
            "is_spof": node_id in spofs,
            "root_causes": reasons[node_id],
        }
        annotated_nodes.append(annotated_node)

    scenario_name = str(scenario.get("name") or "Deterministic stress scenario")
    result = {
        "topology": {"nodes": annotated_nodes, "edges": edge_results},
        "statuses": statuses,
        "root_causes": {
            node_id: "; ".join(reasons[node_id]) for node_id in sorted(reasons) if reasons[node_id]
        },
        "spofs": sorted(spofs),
        "latency_bottlenecks": bottlenecks,
        "analysis": (
            f"Estimated {baseline_rps * traffic_multiplier:g} requests/second per component "
            f"({traffic_multiplier:g}x baseline); {len(spofs)} SPOF(s), "
            f"{len(bottlenecks)} latency bottleneck(s), {len(dropped)} dropped component(s)."
        ),
        "scenario": scenario_name,
        "scenario_config": {
            "traffic_multiplier": traffic_multiplier,
            "baseline_rps": baseline_rps,
            "dropped_nodes": sorted(dropped),
            "warning_utilization": warning_utilization,
            "latency_warning_ms": latency_warning_ms,
            "latency_critical_ms": latency_critical_ms,
        },
    }
    result["recommendations"] = build_recommendations(result)
    return result


def build_recommendations(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Create actionable, deterministic remediation guidance for simulated findings."""
    nodes = result["topology"]["nodes"]
    edges = result["topology"]["edges"]
    labels = {node["id"]: node["label"] for node in nodes}
    scenario = result["scenario_config"]
    dropped_nodes = set(scenario["dropped_nodes"])
    recommendations: list[dict[str, Any]] = []

    def add(
        severity: str,
        category: str,
        component: str,
        finding: str,
        actions: list[str],
    ) -> None:
        recommendations.append(
            {
                "priority": "P1" if severity == "CRITICAL" else "P2",
                "severity": severity,
                "category": category,
                "component": component,
                "finding": finding,
                "actions": actions,
            }
        )

    for node in nodes:
        node_id = node["id"]
        label = node["label"]
        capacity = node["capacity_rps"]
        load = node["load_rps"]
        utilization = node["utilization"]
        status = node["status"]

        if node_id in dropped_nodes:
            add(
                "CRITICAL",
                "Availability",
                label,
                "This component is explicitly unavailable in the scenario.",
                [
                    "Restore the component and verify health checks before returning traffic.",
                    "Add a redundant instance in a separate failure domain and test automatic failover.",
                ],
            )
        elif any(
            cause.startswith("Unreachable after dropped node(s):")
            for cause in node["root_causes"]
        ):
            add(
                "CRITICAL",
                "Availability",
                label,
                "This component becomes unreachable after another component is dropped.",
                [
                    "Add an alternate path or redundant dependency so this component remains reachable during the failure.",
                    "Test the dependency failure and verify traffic is rerouted within the recovery objective.",
                ],
            )
        elif capacity > 0 and utilization is not None and utilization >= 1:
            target_utilization = 0.7
            required_instances = math.ceil(load / (capacity * target_utilization))
            required_capacity = math.ceil(load / target_utilization)
            add(
                "CRITICAL",
                "Capacity",
                label,
                f"Estimated demand is {load:g} RPS against {capacity:g} RPS per instance "
                f"({utilization:.0%} utilization).",
                [
                    f"Scale out to at least {required_instances} balanced instances "
                    f"(about {required_capacity} RPS aggregate capacity) to target 70% utilization.",
                    "Load-test the new capacity and configure autoscaling with a tested scale-out threshold.",
                ],
            )
        elif (
            capacity > 0
            and utilization is not None
            and utilization >= scenario["warning_utilization"]
        ):
            required_instances = math.ceil(load / (capacity * 0.7))
            add(
                "WARNING",
                "Capacity",
                label,
                f"Estimated utilization is {utilization:.0%}, above the "
                f"{scenario['warning_utilization']:.0%} warning threshold.",
                [
                    f"Review headroom and plan for at least {required_instances} balanced instance(s) "
                    "to target 70% utilization at the estimated load.",
                    "Configure autoscaling and alert before the component reaches its capacity limit.",
                ],
            )
        elif capacity <= 0:
            add(
                "WARNING",
                "Capacity",
                label,
                "Capacity is unknown, so the scenario cannot determine whether this component is saturated.",
                [
                    "Measure sustainable throughput with a representative load test and record capacity_rps.",
                    "Add utilization, queue-depth, and error-rate alerts before increasing production traffic.",
                ],
            )

        if node["is_spof"]:
            add(
                "CRITICAL" if node_id in dropped_nodes else "WARNING",
                "Resilience",
                label,
                "The topology contains no alternate path around this component for at least one source-to-sink path.",
                [
                    "Deploy redundant instances across independent failure domains behind health-checked routing.",
                    "Exercise instance, zone, and dependency failure scenarios and verify recovery objectives.",
                ],
            )

    for edge in edges:
        edge_status = edge["status"]
        if edge_status == "OK":
            continue
        source = labels.get(edge["source"], edge["source"])
        target = labels.get(edge["target"], edge["target"])
        severity = edge_status
        add(
            severity,
            "Latency",
            f"{source} -> {target}",
            f"Observed topology metadata reports {edge['latency_ms']:g} ms latency "
            f"({severity.lower()} threshold exceeded).",
            [
                "Trace this dependency under representative load and identify network, queueing, and service-time contributors.",
                "Review connection pooling, payload size, placement, and caching; consider asynchronous work where the request path allows it.",
                "Re-measure p95/p99 latency after changes and compare it with the service objective.",
            ],
        )

    if not recommendations:
        recommendations.append(
            {
                "priority": "P3",
                "severity": "INFO",
                "category": "Validation",
                "component": "Architecture",
                "finding": "No capacity, availability, or latency findings were raised for this scenario.",
                "actions": [
                    "Validate the estimate with a representative load test and a controlled failover exercise.",
                    "Set service-level objectives and alert thresholds for every critical dependency.",
                ],
            }
        )

    severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    recommendations.sort(
        key=lambda recommendation: (
            severity_order[recommendation["severity"]],
            recommendation["category"],
            recommendation["component"].casefold(),
        )
    )
    return recommendations


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic topology stress estimate.")
    parser.add_argument("topology", type=Path, help="Canonical topology JSON.")
    parser.add_argument(
        "scenario",
        type=Path,
        nargs="?",
        help="Optional JSON config with traffic_multiplier, baseline_rps, and dropped_nodes.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("annotated_topology.json"),
        help="Annotated JSON output path.",
    )
    args = parser.parse_args()
    try:
        topology = _read_object(args.topology)
        scenario = _scenario_config(args.scenario)
        result = _analyze(topology, scenario)
        if args.output.resolve() in {args.topology.resolve(), args.scenario.resolve() if args.scenario else None}:
            raise ValueError("Output path must differ from topology and scenario input paths.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"stress_engine: {exc}\n")
    print(f"Wrote annotated topology for {len(result['statuses'])} components to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
