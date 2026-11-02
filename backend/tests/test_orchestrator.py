"""Multi-agent orchestrator test: keyless end-to-end agent task through the bus."""

import asyncio

from backend.agents.base_agent import BaseAgent
from backend.config import get_settings
from backend.gateway.cli_gateway import CLIGateway, CLIRunner
from backend.orchestrator import Orchestrator

TEST_TASK = "Reply with the single word: ok"


async def main() -> int:
    settings = get_settings()
    runner = CLIRunner(settings)
    gateway = CLIGateway(settings, runner)

    agent = BaseAgent(
        name="test_agent",
        role="connectivity",
        system_prompt="You are a connectivity test. Answer briefly.",
        gateway=gateway,
    )
    orchestrator = Orchestrator(agents={"test_agent": agent}, default_agent="test_agent")
    orchestrator.set_graph({"nodes": [{"id": "n1", "type": "test"}], "edges": []})

    output = await orchestrator.dispatch({"task": TEST_TASK, "agent": "test_agent"})

    log = orchestrator.state.iteration_logs[-1]
    scenario = orchestrator.state.scenario_results[-1]
    print("[INFO] iteration_log:", log)
    print("[INFO] scenario_result keys:", sorted(scenario.keys()))

    ok = (
        output.get("status") == "completed"
        and isinstance(output.get("structured"), dict)
        and isinstance(output.get("thoughts"), list)
        and bool(log.get("agent"))
        and bool(scenario.get("output"))
    )
    if ok:
        print("[PASS] Orchestrator keyless agent execution OK")
        return 0
    print("[FAIL] Orchestrator keyless agent execution failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
