"""Specialized worker agents tests (keyless, stub gateways)."""

import asyncio
import json

from backend.agents.blueprint_agent import BlueprintGeneratorAgent
from backend.agents.fix_agent import ArchitecturalFixAgent
from backend.agents.ingress_agent import IngressParserAgent
from backend.agents.stress_agent import StressSimulatorAgent
from backend.models.topology_schema import (
    AnnotatedTopology,
    CanonicalTopology,
    TopologyEdge,
    TopologyNode,
)
from backend.orchestrator import Orchestrator


class StubGateway:
    """Deterministic gateway stub returning canned structured JSON."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def generate(self, prompt: str = "", system_prompt: str = "", **kwargs) -> str:
        return json.dumps(self.payload)


async def main() -> int:
    canonical_payload = {
        "nodes": [
            {"id": "api_gateway", "label": "API Gateway", "type": "api_gateway", "capacity_rps": 1000},
            {"id": "redis", "label": "Redis Cache", "type": "cache", "capacity_rps": 10_000},
        ],
        "edges": [{"source": "client", "target": "api_gateway", "protocol": "http", "latency_ms": 5}],
    }

    # 1) Ingress parser.
    ingress = IngressParserAgent(gateway=StubGateway(canonical_payload))
    ingress_out = await ingress.execute({"task": "Excalidraw JSON export: client -> api_gateway -> redis"})
    assert isinstance(ingress_out, dict) and "nodes" in ingress_out, ingress_out
    print("[PASS] IngressParserAgent ->", ingress_out)

    # 2) Stress simulator.
    chaos = StressSimulatorAgent(gateway=StubGateway({
        "topology": canonical_payload,
        "statuses": {"api_gateway": "CRITICAL", "redis": "OK"},
        "root_causes": {"api_gateway": "traffic spike overwhelmed capacity"},
        "analysis": "Spike caused critical saturation.",
        "scenario": "10x traffic spike on API Gateway",
    }))
    chaos_out = await chaos.execute({
        "task": json.dumps(canonical_payload),
        "context": {"scenario": "10x traffic spike on API Gateway"},
    })
    assert chaos_out.get("statuses", {}).get("api_gateway") == "CRITICAL", chaos_out
    print("[PASS] StressSimulatorAgent ->", chaos_out)

    # 3) Architectural fix.
    fixer = ArchitecturalFixAgent(gateway=StubGateway({
        "original": canonical_payload,
        "mutations": [
            {"op": "inject_load_balancer", "target": "api_gateway"},
            {"op": "duplicate_db", "source": "redis", "target": "redis_replica"},
        ],
        "rationale": "Add LB + replica to survive spike.",
    }))
    fix_out = await fixer.execute({"task": json.dumps(canonical_payload)})
    assert isinstance(fix_out, dict) and isinstance(fix_out.get("mutations"), list), fix_out
    print("[PASS] ArchitecturalFixAgent ->", fix_out)

    # 4) Blueprint generator.
    blueprinter = BlueprintGeneratorAgent(gateway=StubGateway({
        "topology": canonical_payload,
        "terraform_main": 'resource "aws_..." {}',
        "terraform_variables": 'variable "region" {}',
        "docker_compose": "services: {}",
        "setup_commands": ["docker compose up -d"],
        "notes": "Production blueprint.",
    }))
    blueprint_out = await blueprinter.execute({"task": json.dumps(canonical_payload)})
    assert isinstance(blueprint_out, dict) and "docker_compose" in blueprint_out, blueprint_out
    print("[PASS] BlueprintGeneratorAgent ->", blueprint_out)

    # 5) Orchestrator pipeline: ingress -> chaos -> fix -> blueprint.
    orch = Orchestrator(
        agents={
            "ingress_parser": ingress,
            "stress_simulator": chaos,
            "architectural_fix": fixer,
            "blueprint_generator": blueprinter,
        },
        default_agent="ingress_parser",
    )
    canonical = (await orch.dispatch({"task": "client -> api_gateway -> redis"})).get("nodes")
    annotated = await orch.dispatch({
        "task": json.dumps({"nodes": canonical or [], "edges": []}),
        "context": {"scenario": "10x traffic spike on API Gateway"},
        "agent": "stress_simulator",
    })
    fixes = await orch.dispatch({
        "task": json.dumps({"nodes": [], "edges": []}),
        "agent": "architectural_fix",
    })
    blueprint = await orch.dispatch({
        "task": json.dumps({"nodes": [], "edges": []}),
        "agent": "blueprint_generator",
    })
    assert len(orch.state.iteration_logs) == 4, orch.state.iteration_logs
    print("[PASS] Orchestrator 4-agent pipeline OK; logs:", len(orch.state.iteration_logs))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
