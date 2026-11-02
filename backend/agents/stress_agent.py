"""Agent that evaluates stress scenarios against a topology."""

from backend.agents.base_agent import BaseAgent
from backend.gateway.cli_gateway import CLIGateway
from backend.gateway.llm_provider import LLMGateway
from backend.models.topology_schema import AnnotatedTopology

CHAOS_SYSTEM_PROMPT = """You are the Stress Simulator (Chaos Engine). Given a Canonical Topology JSON and a test scenario, annotate the topology.
Return AnnotatedTopology JSON:
{
  "topology": { "nodes": [], "edges": [] },
  "statuses": {"api_gateway": "CRITICAL"},
  "root_causes": {"api_gateway": "cause description"},
  "analysis": "narrative analysis",
  "scenario": "scenario name"
}
Node statuses: OK | WARNING | CRITICAL."""


class StressSimulatorAgent(BaseAgent):
    """Runs chaos analysis and annotates topology with statuses."""

    def __init__(self, gateway: LLMGateway | CLIGateway) -> None:
        super().__init__(
            name="stress_simulator",
            role="Chaos Engine",
            system_prompt=CHAOS_SYSTEM_PROMPT,
            gateway=gateway,
            output_schema=AnnotatedTopology,
        )
