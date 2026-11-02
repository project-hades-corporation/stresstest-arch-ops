"""WebSocket lifecycle tests for the stress endpoint."""

import unittest

from fastapi.testclient import TestClient

from backend.main import app


class StressWebSocketTests(unittest.TestCase):
    def test_idle_client_can_disconnect_cleanly(self) -> None:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/stress"):
                pass

    def test_invalid_json_receives_error_without_starting_pipeline(self) -> None:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/stress") as websocket:
                websocket.send_text("not-json")
                self.assertEqual(
                    websocket.receive_json(),
                    {"type": "error", "detail": "WebSocket messages must be valid JSON."},
                )


if __name__ == "__main__":
    unittest.main()
