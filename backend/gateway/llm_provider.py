"""Unified, provider-agnostic LLM Gateway.

Wraps LiteLLM behind a single async interface so callers never deal with
provider specifics. Supports Ollama, OpenAI, Anthropic, Google Gemini and any
OpenAI-compatible custom endpoint, with retries, fallback models and
structured-JSON handling.
"""

import asyncio
import json
import random
import re
from typing import Any

import litellm
from litellm import acompletion

from backend.config import (
    LLMSettings,
    PROVIDER_NAMES,
    ProviderConfig,
    ProviderName,
    get_provider_name,
    get_settings,
)


class GatewayError(Exception):
    """Raised when every provider/model attempt has failed."""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from raw LLM output.

    Handles plain JSON, JSON wrapped in markdown code fences, and JSON with
    leading/trailing prose.
    """
    cleaned = (text or "").strip()
    fence = _JSON_FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    parsed: Any = None
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except (json.JSONDecodeError, TypeError):
                parsed = None
    if not isinstance(parsed, dict):
        raise GatewayError("LLM response could not be parsed as a JSON object.")
    return parsed


class LLMGateway:
    """Single async entry point across all supported LLM providers."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        model_override: str | None = None,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text from the best-configured model, with retries & fallbacks."""
        provider_name = get_provider_name(self.settings, model_override)
        provider_key = (
            provider_name if provider_name in PROVIDER_NAMES else ProviderName.OLLAMA.value
        )
        config = self.settings.get_provider_config(provider_key)

        candidates = self._candidate_models(provider_key, config, model_override)
        if not candidates:
            raise GatewayError(f"No models available for provider '{provider_key}'.")

        attempts_per_model = max(1, self.settings.max_retries)
        last_error: Exception | None = None

        for provider_cand, model in candidates:
            use_json = json_mode
            degraded = False
            attempt = 0
            while attempt < attempts_per_model:
                attempt += 1
                try:
                    content = await self._completion_once(
                        prompt=prompt,
                        system_prompt=system_prompt,
                        model=model,
                        provider=provider_cand,
                        config=self.settings.get_provider_config(provider_cand),
                        json_mode=use_json,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    if not use_json or not json_mode:
                        return content
                    extract_json_object(content)
                    return content
                except Exception as exc:  # noqa: BLE001 - gateway must not leak raw provider errors
                    last_error = exc
                    if use_json and not degraded and attempt >= attempts_per_model:
                        # Last JSON attempt failed -> degrade to unconstrained generation on this model.
                        degraded = True
                        use_json = False
                        attempt -= 1
                        continue
                    if attempt < attempts_per_model:
                        await self._backoff(attempt - 1)
                        continue
                    break  # exhausted retries for this candidate -> next fallback

        raise GatewayError(f"All LLM attempts failed. Last error: {last_error}")

    async def _completion_once(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        provider: str,
        config: ProviderConfig,
        *,
        json_mode: bool,
        temperature: float | None,
        max_tokens: int | None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        call_kwargs: dict[str, Any] = {
            "model": self._model_identifier(provider, model),
            "messages": messages,
            "timeout": self.settings.request_timeout,
        }
        if temperature is not None:
            call_kwargs["temperature"] = temperature
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens
        if json_mode:
            call_kwargs["response_format"] = {"type": "json_object"}
        if provider in (ProviderName.CUSTOM.value, ProviderName.OPENCODE.value, ProviderName.LITELLM.value):
            # OpenAI-compatible custom / local server (vLLM, DeepSeek, Groq,
            # OpenCode, LiteLLM Proxy, ...) - keyless when the endpoint does
            # not require a user key (OpenCode, LiteLLM proxy hold auth locally).
            call_kwargs["custom_llm_provider"] = "openai"
            if config.base_url:
                call_kwargs["base_url"] = config.base_url
            if config.api_key:
                call_kwargs["api_key"] = config.api_key
        elif provider == ProviderName.OLLAMA.value:
            call_kwargs["base_url"] = config.base_url or self.settings.ollama_base_url
        elif config.api_key:
            call_kwargs["api_key"] = config.api_key

        response = await acompletion(**call_kwargs)
        content = response.choices[0].message.content
        return content if content is not None else ""

    @staticmethod
    def _model_identifier(provider: str, model: str) -> str:
        if provider in (ProviderName.CUSTOM.value, ProviderName.OPENCODE.value, ProviderName.LITELLM.value):
            # OpenAI-compatible custom endpoint (vLLM, DeepSeek, Groq, OpenCode, LiteLLM Proxy, ...)
            return model
        return f"{provider}/{model}"

    def _candidate_models(
        self,
        provider_key: str,
        config: ProviderConfig,
        model_override: str | None,
    ) -> list[tuple[str, str]]:
        """Ordered list of (provider, model) candidates to try."""
        candidates: list[tuple[str, str]] = []
        if model_override:
            if "/" in model_override:
                override_provider, _, override_model = model_override.partition("/")
                candidates.append((override_provider.strip(), override_model.strip()))
            else:
                candidates.append((provider_key, model_override))
        elif config.model:
            candidates.append((provider_key, config.model))
        for fallback in config.fallback_models or []:
            if fallback and all(f != fallback for _, f in candidates):
                candidates.append((provider_key, fallback))
        return candidates

    async def _backoff(self, attempt: int) -> None:
        delay = self.settings.retry_backoff_factor * (2 ** (attempt - 1))
        await asyncio.sleep(delay * (0.5 + random.random()))


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    """Process-wide singleton gateway."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


async def generate_completion(
    prompt: str,
    system_prompt: str,
    model_override: str = None,
    *,
    json_mode: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Single unified interface for LLM generation across all providers.

    Args:
        prompt: User prompt.
        system_prompt: Optional system/instruction prompt.
        model_override: Optional ``"provider/model"`` (e.g. ``"openai/gpt-4o"``)
            or bare model name (resolved against the default provider).
        json_mode: Request structured JSON output and validate the reply.

    Returns:
        The generated text (JSON string when ``json_mode`` is enabled).
    """
    return await get_gateway().generate(
        prompt,
        system_prompt,
        model_override,
        json_mode=json_mode,
        temperature=temperature,
        max_tokens=max_tokens,
    )
