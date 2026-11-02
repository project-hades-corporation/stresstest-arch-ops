"""Tests for passing uploaded architecture text into the ingress agent."""

import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.main import OrchestrationRequestBody, orchestrate


class UploadContextTests(unittest.TestCase):
    def test_architecture_text_is_forwarded_to_ingress(self) -> None:
        captured: dict[str, object] = {}

        class FakeOrchestrator:
            def __init__(self, agents: dict, default_agent: str) -> None:
                self.default_agent = default_agent

            async def dispatch(self, task: dict) -> dict:
                captured["task"] = task
                return {"nodes": [], "edges": []}

        request = OrchestrationRequestBody(
            task="Simulate a regional outage",
            context={"architecture_document": "API gateway connects to PostgreSQL."},
        )
        with (
            patch("backend.main.CLIGateway"),
            patch("backend.main.Orchestrator", FakeOrchestrator),
        ):
            result = asyncio.run(orchestrate(request))

        self.assertEqual(
            captured["task"],
            {
                "task": "Simulate a regional outage",
                "context": {"architecture_document": "API gateway connects to PostgreSQL."},
            },
        )
        self.assertEqual(result["output"], {"nodes": [], "edges": []})

    def test_rejects_non_string_architecture_text(self) -> None:
        request = OrchestrationRequestBody(
            task="Test",
            context={"architecture_document": ["not", "text"]},
        )

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(orchestrate(request))

        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
