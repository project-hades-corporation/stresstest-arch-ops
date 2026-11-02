"""Multi-agent orchestrator: session state, event bus, task routing."""

import asyncio
import time
from typing import Any, Awaitable, Callable

from backend.agents.base_agent import AgentResult, BaseAgent


class SessionState:
    """Thread-safe (asyncio-lock guarded) shared session state."""

    def __init__(self) -> None:
        self.graph: dict[str, Any] = {"nodes": [], "edges": []}
        self.scenario_results: list[dict[str, Any]] = []
        self.iteration_logs: list[dict[str, Any]] = []
        self._lock: asyncio.Lock = asyncio.Lock()

    async def record_iteration(self, entry: dict[str, Any]) -> None:
        async with self._lock:
            self.iteration_logs.append(entry)

    async def record_scenario(self, result: dict[str, Any]) -> None:
        async with self._lock:
            self.scenario_results.append(result)


class EventBus:
    """Minimal async event bus for agent/orchestrator events."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def emit(self, event: dict[str, Any]) -> None:
        self._queue.put_nowait(event)

    async def consume(self) -> dict[str, Any] | None:
        return await self._queue.get()


class Orchestrator:
    """Event-driven multi-agent orchestrator."""

    def __init__(
        self,
        agents: dict[str, BaseAgent],
        default_agent: str = "primary",
        event_bus: EventBus | None = None,
    ) -> None:
        self.state = SessionState()
        self.agents = agents
        self.default_agent = default_agent
        self.event_bus = event_bus or EventBus()

    def set_graph(self, graph: dict[str, Any]) -> None:
        """Update canvas topology graph snapshot."""
        self.state.graph = graph

    async def dispatch(self, task: dict[str, Any], agent_name: str | None = None) -> dict[str, Any]:
        """Route a task asynchronously to an agent and log execution telemetry."""
        agent_name = agent_name or str(task.get("agent") or self.default_agent)
        if agent_name not in self.agents:
            raise KeyError(f"Unknown agent: {agent_name}")
        agent: BaseAgent = self.agents[agent_name]

        started = time.monotonic()
        self.event_bus.emit({"type": "task_started", "task": task, "agent": agent_name})
        output = await agent.execute(task)
        finished = time.monotonic()
        latency_ms = (finished - started) * 1000

        await self.state.record_iteration(
            {
                "agent": agent_name,
                "task": task,
                "started_at": started,
                "finished_at": finished,
                "latency_ms": latency_ms,
                "status": str(output.get("status") or "completed"),
            }
        )
        await self.state.record_scenario(
            {"agent": agent_name, "task": task, "output": output, "latency_ms": latency_ms}
        )
        self.event_bus.emit(
            {
                "type": "task_finished",
                "task": task,
                "agent": agent_name,
                "latency_ms": latency_ms,
                "status": str(output.get("status") or "completed"),
            }
        )
        return output
