"""Provider connectivity smoke test for the LLM Gateway.

Reads the provider configuration from the environment / ``.env`` file and
verifies that the configured provider is reachable and able to complete a
minimal request.

Usage:
    python -m backend.tests.test_provider

Exit codes:
    0 -> all checks passed
    1 -> one or more checks failed
"""

import asyncio

import httpx

from backend.config import LLMSettings, PROVIDER_NAMES, ProviderName, get_settings
from backend.gateway.llm_provider import GatewayError, LLMGateway

PROVIDER_LABELS = {
    ProviderName.OLLAMA.value: "Ollama (local)",
    ProviderName.OPENAI.value: "OpenAI",
    ProviderName.ANTHROPIC.value: "Anthropic",
    ProviderName.GEMINI.value: "Google Gemini",
    ProviderName.CUSTOM.value: "Custom (OpenAI-compatible)",
    ProviderName.OPENCODE.value: "OpenCode (local)",
    ProviderName.LITELLM.value: "LiteLLM Proxy (local)",
}
TEST_PROMPT = "Reply with the single word: ok"
TEST_SYSTEM_PROMPT = "You are a connectivity test. Answer briefly."


async def check_ollama(settings: LLMSettings) -> tuple[bool, str]:
    """Ping the Ollama server and confirm the configured model is available."""
    base_url = (settings.ollama_base_url or "http://localhost:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
    except Exception as exc:  # noqa: BLE001
        return False, f"Cannot reach Ollama at {base_url}: {exc}"

    if resp.status_code != 200:
        return False, f"Ollama /api/tags returned HTTP {resp.status_code}"

    try:
        payload = resp.json()
        models = [m.get("name") for m in payload.get("models") or []]
    except Exception:  # noqa: BLE001
        return False, "Ollama /api/tags returned a malformed payload"

    configured = settings.ollama_model
    if configured and configured not in models:
        return (
            False,
            f"Configured model '{configured}' not found. Available: {', '.join(models)}",
        )
    return True, f"Ollama reachable at {base_url}; model '{configured}' available."


async def check_opencode(settings: LLMSettings) -> tuple[bool, str]:
    """Ping the local OpenCode server (OpenAI-compatible, keyless)."""
    base_url = (settings.opencode_base_url or "http://localhost:8080/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/models")
    except Exception as exc:  # noqa: BLE001
        return False, f"Cannot reach OpenCode server at {base_url}: {exc}"
    if resp.status_code != 200:
        return False, f"OpenCode server at {base_url} returned HTTP {resp.status_code}"
    return True, f"OpenCode server reachable at {base_url}."


async def check_remote_provider(settings: LLMSettings) -> tuple[bool, str]:
    """Run a real (tiny) completion against the configured remote provider."""
    try:
        gateway = LLMGateway(settings)
        content = await gateway.generate(
            TEST_PROMPT,
            TEST_SYSTEM_PROMPT,
            model_override=None,
            json_mode=False,
            temperature=0.0,
            max_tokens=32,
        )
        reply = (content or "").strip()
        if not reply:
            return False, "Provider returned an empty response."
        return True, f"Completion OK (reply: {reply!r})."
    except GatewayError as exc:
        return False, f"Gateway failed after retries/fallbacks: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Provider call failed: {exc}"


async def run_all_checks(settings: LLMSettings) -> list[tuple[str, bool, str]]:
    """Run all connectivity checks for the currently configured provider."""
    checks: list[tuple[str, bool, str]] = []

    default_provider = (settings.default_provider or ProviderName.OLLAMA.value).lower()
    if default_provider not in PROVIDER_NAMES:
        return [(f"Provider '{default_provider}'", False, "Unknown provider configured.")]

    checks.append(
        (f"Configuration ({default_provider})", True, "Settings loaded OK.")
    )

    if default_provider == ProviderName.OLLAMA.value:
        ok, msg = await check_ollama(settings)
        checks.append(("Ollama connectivity", ok, msg))
        if ok:
            ok_gen, msg_gen = await check_remote_provider(settings)
            checks.append(("Ollama generation", ok_gen, msg_gen))
    elif default_provider == ProviderName.OPENCODE.value:
        ok, msg = await check_opencode(settings)
        checks.append(("OpenCode server connectivity", ok, msg))
    else:
        ok, msg = await check_remote_provider(settings)
        checks.append((f"{PROVIDER_LABELS.get(default_provider, default_provider)} connectivity", ok, msg))

    return checks


async def main() -> int:
    settings = get_settings()
    checks = await run_all_checks(settings)

    failed = False
    for name, ok, msg in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {msg}")
        if not ok:
            failed = True

    if failed:
        print("\nProvider connectivity check FAILED.")
        return 1
    print("\nProvider connectivity check PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
