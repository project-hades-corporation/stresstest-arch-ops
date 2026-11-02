"""Agent that generates infrastructure blueprints from a topology."""

from backend.agents.base_agent import BaseAgent
from backend.gateway.cli_gateway import CLIGateway
from backend.gateway.llm_provider import LLMGateway
from backend.models.topology_schema import BlueprintPlan


class BlueprintGeneratorAgent(BaseAgent):
    """Generates production IaC (Terraform + Docker Compose) from approved topology."""

    def __init__(self, gateway: LLMGateway | CLIGateway) -> None:
        super().__init__(
            name="blueprint_generator",
            role="Blueprint Generator",
            system_prompt=(
                "You are the Blueprint Generator. Given an approved canonical topology, "
                "output a BlueprintPlan JSON with terraform_main, terraform_variables, "
                "docker_compose, setup_commands and notes for production deployment."
            ),
            gateway=gateway,
            output_schema=BlueprintPlan,
        )
