"""Central configuration for the provider-agnostic LLM Gateway.

All settings are loaded from environment variables / a ``.env`` file via
``pydantic-settings`` (see ``.env.example`` for the full list).

Supported providers
-------------------
- ``ollama``   -> local models served by Ollama (``OLLAMA_BASE_URL``,
                  ``OLLAMA_MODEL``)
- ``openai``   -> OpenAI (``OPENAI_API_KEY``, ``OPENAI_MODEL``)
- ``anthropic`` -> Anthropic (``ANTHROPIC_API_KEY``, ``ANTHROPIC_MODEL``)
- ``gemini``   -> Google Gemini (``GOOGLE_API_KEY``, ``GEMINI_MODEL``)
- ``custom``   -> any OpenAI-compatible endpoint (vLLM, DeepSeek, Groq, ...)
                  (``CUSTOM_BASE_URL``, ``CUSTOM_API_KEY``, ``CUSTOM_MODEL``)
- ``opencode`` -> local OpenCode server (OpenAI-compatible, keyless)
                  (``OPENCODE_BASE_URL``, ``OPENCODE_MODEL``)

Every provider group exposes a primary ``*_MODEL`` plus an optional
comma-separated ``*_FALLBACK_MODELS`` list for graceful degradation.
"""

from functools import lru_cache
from enum import Enum

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderName(str, Enum):
    """Canonical identifiers for supported LLM providers."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    CUSTOM = "custom"
    OPENCODE = "opencode"
    LITELLM = "litellm"


PROVIDER_NAMES: list[str] = [p.value for p in ProviderName]


def _split_fallbacks(value: str | None) -> list[str]:
    """Parse a comma-separated list of fallback model names."""
    if not value:
        return []
    return [m.strip() for m in value.split(",") if m and m.strip()]


class ProviderConfig(BaseModel):
    """Connection details and model list for a single provider."""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)


class LLMSettings(BaseSettings):
    """Runtime configuration, sourced from a ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Provider that receives the default traffic when no override is given.
    default_provider: str = ProviderName.OLLAMA.value
    use_keyless_cli: bool = False

    # Ollama (local models)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:latest"
    ollama_fallback_models: str = ""

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_fallback_models: str = "gpt-4o"

    # Anthropic
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-sonnet-latest"
    anthropic_fallback_models: str = "claude-3-5-haiku-latest"

    # Google Gemini
    google_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_fallback_models: str = "gemini-1.5-flash"

    # OpenAI-compatible custom endpoints (DeepSeek, Groq, vLLM, ...)
    custom_base_url: str = ""
    custom_api_key: str = ""
    custom_model: str = ""
    custom_fallback_models: str = ""

    # OpenCode local server (OpenAI-compatible API, keyless - uses the
    # locally authenticated OpenCode CLI, no user API key required).
    opencode_base_url: str = "http://localhost:8080/v1"
    opencode_model: str = ""
    opencode_fallback_models: str = ""

    # LiteLLM Proxy server (OpenAI-compatible gateway). Holds provider keys
    # server-side and routes to providers - used keylessly to serve flows that
    # would otherwise require end-user API keys (Gemini CLI, Claude CLI, Kimi,
    # Copilot, ...).
    litellm_base_url: str = ""
    litellm_api_key: str = ""
    litellm_model: str = ""
    litellm_fallback_models: str = ""

    # Gateway behaviour
    max_retries: int = 3
    retry_backoff_factor: float = 0.5
    request_timeout: float = 30.0

    # -- helpers ------------------------------------------------------------
    def get_provider_config(self, provider: str) -> ProviderConfig:
        """Return the connection config for ``provider``."""
        if provider == ProviderName.OLLAMA.value:
            return ProviderConfig(
                api_key="ollama",
                base_url=self.ollama_base_url or None,
                model=self.ollama_model or None,
                fallback_models=_split_fallbacks(self.ollama_fallback_models),
            )
        if provider == ProviderName.OPENAI.value:
            return ProviderConfig(
                api_key=self.openai_api_key,
                base_url=None,
                model=self.openai_model or None,
                fallback_models=_split_fallbacks(self.openai_fallback_models),
            )
        if provider == ProviderName.ANTHROPIC.value:
            return ProviderConfig(
                api_key=self.anthropic_api_key,
                base_url=None,
                model=self.anthropic_model or None,
                fallback_models=_split_fallbacks(self.anthropic_fallback_models),
            )
        if provider == ProviderName.GEMINI.value:
            return ProviderConfig(
                api_key=self.google_api_key,
                base_url=None,
                model=self.gemini_model or None,
                fallback_models=_split_fallbacks(self.gemini_fallback_models),
            )
        if provider == ProviderName.CUSTOM.value:
            return ProviderConfig(
                api_key=self.custom_api_key or None,
                base_url=self.custom_base_url or None,
                model=self.custom_model or None,
                fallback_models=_split_fallbacks(self.custom_fallback_models),
            )
        if provider == ProviderName.OPENCODE.value:
            # OpenCode local server (OpenAI-compatible, authenticated locally
            # via the OpenCode CLI - no user-supplied API key needed).
            return ProviderConfig(
                api_key=None,
                base_url=self.opencode_base_url or None,
                model=self.opencode_model or None,
                fallback_models=_split_fallbacks(self.opencode_fallback_models),
            )
        if provider == ProviderName.LITELLM.value:
            # LiteLLM Proxy server (OpenAI-compatible, keyless from the end
            # user's perspective - the proxy holds provider keys internally).
            return ProviderConfig(
                api_key=self.litellm_api_key or None,
                base_url=self.litellm_base_url or None,
                model=self.litellm_model or None,
                fallback_models=_split_fallbacks(self.litellm_fallback_models),
            )
        raise ValueError(f"Unknown provider: {provider!r}")

    def get_model(self, provider: str) -> str:
        """Return the primary model name configured for ``provider``."""
        config = self.get_provider_config(provider)
        if not config.model:
            raise ValueError(f"No model configured for provider {provider!r}.")
        return config.model


@lru_cache
def get_settings() -> LLMSettings:
    """Cached settings instance (re-reads ``.env`` per process lifetime)."""
    return LLMSettings()


def get_provider_name(settings: LLMSettings, model_override: str | None = None) -> str:
    """Resolve the provider to use, honouring an optional ``provider/model`` override."""
    override = (model_override or "").strip()
    if override and "/" in override:
        return override.split("/", 1)[0].strip()
    return settings.default_provider
