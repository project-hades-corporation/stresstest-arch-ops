"""Multi-agent layer: base agent contract, structured outputs, thoughts."""

import json
import time
from typing import Any, Optional, Type

from pydantic import BaseModel, Field

from backend.gateway.cli_gateway import CLIGateway
from backend.gateway.llm_provider import LLMGateway


class AgentStep(BaseModel):
    """Structured, timestamped thought/step captured during agent execution."""

    agent: str = ""
    step: str = ""
    detail: str = ""
    timestamp: float = Field(default_factory=lambda: time.time())


class AgentResult(BaseModel):
    """Validated output contract every agent must return downstream."""

    agent: str = ""
    task: str = ""
    status: str = "completed"
    content: str = ""
    structured: dict[str, Any] = Field(default_factory=dict)
    thoughts: list[AgentStep] = Field(default_factory=list)
    model: Optional[str] = None
    latency_ms: Optional[float] = None


class BaseAgent:
    """Base class for all orchestrated agents.

    Wraps a keyless-capable LLM gateway, enforces a Pydantic output schema and
    records structured step-by-step thoughts for the frontend.
    """

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        gateway: LLMGateway | CLIGateway,
        output_schema: Type[BaseModel] = AgentResult,
    ) -> None:
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.gateway = gateway
        self.output_schema = output_schema

    async def execute(self, payload: dict) -> dict:
        """Execute agent task and return a validated dict."""
        start = time.monotonic()
        task = str(payload.get("task") or payload.get("prompt") or "General task")
        context: dict[str, Any] = dict(payload.get("context") or {})
        prompt = self._build_prompt(task, context)

        thoughts = [AgentStep(agent=self.name, step="task_received", detail=task)]
        content = ""
        mode = "text"
        status = "completed"

        # Primary path: structured JSON output (validated downstream).
        try:
            content = await self.gateway.generate(
                prompt=prompt, system_prompt=self.system_prompt, json_mode=True
            )
            mode = "json"
        except Exception:  # noqa: BLE001 - fall back to unstructured generation
            content = await self.gateway.generate(
                prompt=prompt, system_prompt=self.system_prompt
            )

        structured: dict[str, Any] = {}
        parsed: Any = content
        if isinstance(content, str) and content.strip():
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                parsed = {"raw": content}

        validated: Any = None
        status = "completed"
        validated_content: Any = content
        if isinstance(parsed, dict):
            try:
                validated = self.output_schema.model_validate(parsed)
                dump = validated.model_dump()
                structured = dump if isinstance(dump, dict) else {}
                status = str(getattr(validated, "status", None) or "completed") or "completed"
                validated_content = (
                    getattr(validated, "content", None)
                    or parsed.get("content")
                    or parsed.get("result")
                    or content
                )
            except Exception:  # noqa: BLE001 - keep partial content rather than failing hard
                status = "failed"
        else:
            status = "failed"
        content = str(validated_content or content or "")

        thoughts.append(
            AgentStep(
                agent=self.name,
                step="llm_response",
                detail=str(content)[:500],
            )
        )

        if validated is not None:
            return validated.model_dump()

        output = AgentResult(
            agent=self.name,
            task=task,
            status=status,
            content=str(content),
            structured=structured if isinstance(structured, dict) else {},
            thoughts=thoughts,
            latency_ms=(time.monotonic() - start) * 1000,
        )
        return output.model_dump()

    def _build_prompt(self, task: str, context: dict[str, Any]) -> str:
        parts = [f"Task: {task}"]
        if context:
            parts.append("Context:\n" + json.dumps(context, default=str))
        return "\n\n".join(parts)


# Backwards-friendly alias for composed agents.
class NarrativeAgent(BaseAgent):
    """Convenience agent focused on narrative/structured prose outputs."""
