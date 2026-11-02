"""Agent that proposes architectural fixes for failure points."""

from backend.agents.base_agent import BaseAgent
from backend.gateway.cli_gateway import CLIGateway
from backend.gateway.llm_provider import LLMGateway
from backend.models.topology_schema import FixPlan


class ArchitecturalFixAgent(BaseAgent):
    """Generates topology mutations to fix CRITICAL/WARNING failure points."""

    def __init__(self, gateway: LLMGateway | CLIGateway) -> None:
        super().__init__(
            name="architectural_fix",
            role="Architectural Fix Agent",
            system_prompt=(
                "You are the Architectural Fix Agent. Given an annotated topology with "
                "CRITICAL/WARNING statuses and root causes, output a FixPlan JSON with "
                "`original` topology and `mutations` (e.g. inject load balancer, "
                "duplicate DB into primary/replica, add circuit breakers) plus `rationale`."
            ),
            gateway=gateway,
            output_schema=FixPlan,
        )
