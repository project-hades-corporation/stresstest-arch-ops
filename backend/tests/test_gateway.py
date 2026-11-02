"""Keyless LLM Gateway test.

Auto-detects installed AI CLI binaries on the host machine via ``$PATH`` and
verifies a single completion prompt end-to-end **without requiring any AI API
key**.

Usage:
    python -m backend.tests.test_gateway

Exit codes:
    0 -> keyless completion succeeded
    1 -> no provider / completion failed
"""

import asyncio

from backend.config import get_settings
from backend.gateway.cli_gateway import CLIGateway, CLIRunner

TEST_PROMPT = "Reply with the single word: ok"
TEST_SYSTEM_PROMPT = "You are a connectivity test. Answer briefly."


async def run_checks() -> int:
    settings = get_settings()
    runner = CLIRunner(settings)
    gateway = CLIGateway(settings, runner)

    installed = runner.discover()
    print(f"[INFO] Discovered CLI providers on this host: {installed}")

    try:
        result = await gateway.generate(
            TEST_PROMPT,
            system_prompt=TEST_SYSTEM_PROMPT,
            provider_hint="auto",
        )
        print(f"[PASS] Keyless completion OK via auto-detected provider chain (reply: {result!r})")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Keyless completion failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_checks()))
