"""Unit tests for the CLI-first gateway interface."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.base_agent import BaseAgent
from backend.config import LLMSettings
from backend.gateway.cli_gateway import CLIGateway
from backend.gateway.llm_provider import LLMGateway


class SuccessfulCliRunner:
    def __init__(self, binary_available: bool = True) -> None:
        self.system_prompt = ""
        self.binary_available = binary_available

    def discover(self) -> list[str]:
        return ["copilot"]

    def resolve_binary(self, provider: str) -> str | None:
        return "copilot.exe" if self.binary_available else None

    def build_args(
        self, provider: str, prompt: str, system_prompt: str = "", model: str | None = None
    ) -> list[str]:
        self.system_prompt = system_prompt
        return ["copilot.exe", prompt]

    async def execute(self, args: list[str]) -> tuple[str, str, int]:
        return (
            json.dumps(
                {
                    "agent": "connectivity",
                    "task": "Check the connection",
                    "status": "completed",
                    "content": "ready",
                }
            ),
            "",
            0,
        )


class CliGatewayTests(unittest.TestCase):
    def test_base_agent_can_request_json_from_cli_gateway(self) -> None:
        runner = SuccessfulCliRunner()
        gateway = CLIGateway(LLMSettings(_env_file=None), runner)
        agent = BaseAgent(
            name="connectivity",
            role="connectivity",
            system_prompt="Answer briefly.",
            gateway=gateway,
        )

        result = asyncio.run(agent.execute({"task": "Check the connection"}))

        self.assertEqual(result["content"], "ready")
        self.assertEqual(result["status"], "completed")
        self.assertIn("Return only a valid JSON object", runner.system_prompt)

    def test_json_mode_is_forwarded_to_hosted_gateway_fallback(self) -> None:
        runner = SuccessfulCliRunner(binary_available=False)

        class HostedGateway(LLMGateway):
            def __init__(self) -> None:
                self.json_mode = False

            async def generate(
                self, prompt: str, system_prompt: str, *, json_mode: bool = False
            ) -> str:
                self.json_mode = json_mode
                return '{"ok": true}'

        hosted = HostedGateway()
        gateway = CLIGateway(LLMSettings(_env_file=None), runner, hosted)

        async def run() -> str:
            with patch.object(gateway, "_probe_local", new=AsyncMock(return_value=None)):
                return await gateway.generate(
                    "Return JSON", provider_hint="copilot", json_mode=True
                )

        result = asyncio.run(run())

        self.assertEqual(result, '{"ok": true}')
        self.assertTrue(hosted.json_mode)


if __name__ == "__main__":
    unittest.main()
