"""Keyless, CLI-first LLM Gateway.

Architecture (fallback chain) for ``generate``:
  1. Direct async subprocess execution of an authenticated AI CLI binary
     discovered on the system ``$PATH`` (e.g. ``claude -p``, ``copilot -p``,
     ``ollama run <model> <prompt>``).
  2. Local HTTP daemon if detected (Ollama at ``OLLAMA_BASE_URL``, VS Code
     Copilot API bridge at ``http://127.0.0.1:3030/v1``).
  3. Standard ``.env`` API key via the hosted :class:`~gateway.LLMGateway`.

The unified entry point is :meth:`CLIGateway.generate`.
"""

import asyncio
import os
from typing import AsyncIterator, Optional

import httpx
import litellm
from litellm import acompletion

from backend.config import LLMSettings, get_settings
from backend.gateway.llm_provider import GatewayError, LLMGateway

# Discovery / resolution order for provider-agnostic keyless usage.
CLI_PROVIDER_ORDER: list[str] = [
    "copilot",
    "gemini",
    "claude",
    "ollama",
    "opencode",
    "grok",
    "kimi",
]

# Default stdout-print flags for CLI-based "chat" CLIs (override via env if needed).
DEFAULT_PRINT_FLAGS: dict[str, str] = {
    "claude": "-p",
    "gemini": "-p",
    "copilot": "-p",
    "grok": "-p",
    "kimi": "-p",
}

COPILOT_BRIDGE_BASE_URL = "http://127.0.0.1:3030/v1"


class CLIRunner:
    """Async subprocess wrapper around installed AI CLI executables."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Binary discovery
    # ------------------------------------------------------------------ #
    def discover(self, names: Optional[list[str]] = None) -> list[str]:
        """Scan ``$PATH`` for installed AI CLI binaries. Returns provider names."""
        names = list(names) if names is not None else list(CLI_PROVIDER_ORDER)
        found: list[str] = []
        path_value = os.environ.get("PATH") or os.defpath
        for name in names:
            binary = self.resolve_binary(name)
            if binary is not None:
                found.append(name)
        return found

    def resolve_binary(self, provider: str) -> Optional[str]:
        """Return absolute path to installed CLI binary, or ``None``."""
        name = (provider or "").lower()
        if not name:
            return None
        path_value = os.environ.get("PATH") or os.defpath
        for dir_ in path_value.split(os.pathsep):
            if not dir_:
                continue
            candidate = os.path.join(dir_, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
            if os.name == "nt":
                candidate_exe = os.path.join(dir_, f"{name}.exe")
                if os.path.isfile(candidate_exe) and os.access(candidate_exe, os.X_OK):
                    return candidate_exe
        return None

    # ------------------------------------------------------------------ #
    # Subprocess execution / streaming
    # ------------------------------------------------------------------ #
    async def execute(
        self, args: list[str], timeout: float = 60.0
    ) -> tuple[str, str, int]:
        """Run CLI command; returns ``(stdout, stderr, returncode)``."""
        if not args:
            return "", "No CLI command configured", -1
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return "", f"Command timed out after {timeout}s: {' '.join(args)}", -1
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "", f"Command timed out after {timeout}s: {' '.join(args)}", -1
        stdout = stdout_b.decode("utf-8", errors="replace") if isinstance(stdout_b, bytes) else (stdout_b or "")
        stderr = stderr_b.decode("utf-8", errors="replace") if isinstance(stderr_b, bytes) else (stderr_b or "")
        return (stdout or "").strip(), (stderr or "").strip(), proc.returncode

    async def stream_tokens(
        self, args: list[str], timeout: float = 180.0
    ) -> AsyncIterator[str]:
        """Stream stdout lines from a CLI process as tokens."""
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout,
        )
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
                if not line:
                    break
                token = line.decode("utf-8", errors="replace").strip()
                if token:
                    yield token
        except asyncio.TimeoutError:
            proc.kill()
            raise
        finally:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            try:
                await proc.wait()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ #
    # Arg construction
    # ------------------------------------------------------------------ #
    def build_args(
        self,
        provider: str,
        prompt: str,
        system_prompt: str = "",
        model: str | None = None,
    ) -> list[str]:
        """Build CLI argv for ``provider``. ``system_prompt`` folds into prompt."""
        provider = (provider or "").lower()
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        binary = self.resolve_binary(provider) or provider

        if provider == "ollama":
            resolved_model = model or self.settings.ollama_model
            return [binary, "run", resolved_model, full_prompt]
        if provider == "opencode":
            return [binary, "run", full_prompt]
        flag = DEFAULT_PRINT_FLAGS.get(provider, "-p")
        return [binary, flag, full_prompt]


class CLIGateway:
    """Keyless LLM gateway: CLI subprocess -> local daemon -> env API key."""

    def __init__(
        self,
        settings: LLMSettings | None = None,
        cli_runner: CLIRunner | None = None,
        llm_gateway: LLMGateway | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cli_runner = cli_runner or CLIRunner(self.settings)
        self.llm_gateway = llm_gateway or LLMGateway(self.settings)

    # ------------------------------------------------------------------ #
    # Unified keyless interface
    # ------------------------------------------------------------------ #
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        provider_hint: str = "auto",
        *,
        json_mode: bool = False,
    ) -> str:
        """Generate text keylessly via CLI/local-daemon/env-key fallback chain."""
        for provider in self._candidate_providers(provider_hint):
            result = await self._generate_for(
                provider, prompt, system_prompt, json_mode=json_mode
            )
            if result is not None:
                return result
        raise GatewayError("Keyless LLM gateway: all provider attempts failed.")

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _candidate_providers(self, provider_hint: str) -> list[str]:
        hint = (provider_hint or "auto").strip().lower()
        if hint and hint != "auto":
            return [hint]
        installed = self.cli_runner.discover()
        return [p for p in CLI_PROVIDER_ORDER if p in installed]

    async def _generate_for(
        self, provider: str, prompt: str, system_prompt: str, *, json_mode: bool = False
    ) -> Optional[str]:
        # Priority 1: direct async CLI subprocess execution.
        try:
            binary = self.cli_runner.resolve_binary(provider)
            if binary:
                cli_system_prompt = system_prompt
                if json_mode:
                    cli_system_prompt = (
                        f"{system_prompt}\n\n" if system_prompt else ""
                    ) + "Return only a valid JSON object without markdown fences or prose."
                args = self.cli_runner.build_args(provider, prompt, cli_system_prompt)
                stdout, stderr, rc = await self.cli_runner.execute(args)
                if rc == 0 and stdout.strip():
                    return stdout.strip()
        except Exception:  # noqa: BLE001 - fall through to next priority
            pass

        # Priority 2: local HTTP daemon (Ollama / Copilot bridge / LiteLLM proxy).
        local = await self._probe_local()
        if local is not None:
            base_url, model = local
            try:
                content = await self._completion_openai_compatible(
                    base_url, model, prompt, system_prompt, json_mode=json_mode
                )
                if content.strip():
                    return content.strip()
            except Exception:  # noqa: BLE001
                pass

        # Priority 3: standard .env API key via hosted gateway.
        try:
            return await self.llm_gateway.generate(
                prompt, system_prompt, json_mode=json_mode
            )
        except Exception:  # noqa: BLE001
            return None

    async def _probe_local(self) -> Optional[tuple[str, str]]:
        """Probe local daemons; returns ``(base_url, model)`` or ``None``."""
        ollama_base = (self.settings.ollama_base_url or "http://localhost:11434").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                if (await client.get(f"{ollama_base}/api/tags")).status_code == 200:
                    return (ollama_base, self.settings.ollama_model or "llama3")
        except Exception:  # noqa: BLE001
            pass
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                if (
                    await client.get(f"{COPILOT_BRIDGE_BASE_URL}/models")
                ).status_code == 200:
                    return (COPILOT_BRIDGE_BASE_URL, self.settings.openai_model or "gpt-4o-mini")
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _completion_openai_compatible(
        self,
        base_url: str,
        model: str,
        prompt: str,
        system_prompt: str,
        *,
        json_mode: bool = False,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        base = base_url.rstrip("/")
        if base.endswith("11434"):
            # Ollama native provider path.
            kwargs = {
                "model": f"ollama/{model}",
                "messages": messages,
                "api_base": base,
                "timeout": self.settings.request_timeout,
            }
        else:
            # Generic OpenAI-compatible endpoint (Copilot bridge, LiteLLM proxy, ...).
            kwargs = {
                "model": model,
                "messages": messages,
                "api_base": base,
                "custom_llm_provider": "openai",
                "api_key": self.settings.openai_api_key or "dummy",
                "timeout": self.settings.request_timeout,
            }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await acompletion(**kwargs)
        content = response.choices[0].message.content
        return content if content is not None else ""
