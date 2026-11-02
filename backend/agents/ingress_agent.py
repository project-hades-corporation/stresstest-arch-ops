"""Agent that converts user input into canonical topology."""

from backend.agents.base_agent import BaseAgent
from backend.gateway.cli_gateway import CLIGateway
from backend.gateway.llm_provider import LLMGateway
from backend.models.topology_schema import CanonicalTopology

INGRESS_SYSTEM_PROMPT = """You are the Ingress Parser. Convert user input, including architecture text extracted from documents or OCR, into a Canonical Topology JSON. Use the architecture document context as the system description and preserve its components and connections.
Canonical Topology JSON shape:
{
  "nodes": [{"id": "api_gateway", "label": "API Gateway", "type": "api_gateway", "capacity_rps": 1000}],
  "edges": [{"source": "client", "target": "api_gateway", "protocol": "http", "latency_ms": 5}]
}
Respond with ONLY valid JSON of type CanonicalTopology."""


class IngressParserAgent(BaseAgent):
    """Parses raw input (text/image/Excalidraw) into a Canonical Topology."""

    def __init__(self, gateway: LLMGateway | CLIGateway) -> None:
        super().__init__(
            name="ingress_parser",
            role="Canonical Topology Ingress",
            system_prompt=INGRESS_SYSTEM_PROMPT,
            gateway=gateway,
            output_schema=CanonicalTopology,
        )
