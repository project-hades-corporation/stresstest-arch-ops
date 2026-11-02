"""CORS configuration tests for the local frontend."""

import unittest

from fastapi.testclient import TestClient

from backend.main import app


class CorsTests(unittest.TestCase):
    def test_frontend_json_post_preflight_is_allowed(self) -> None:
        with TestClient(app) as client:
            response = client.options(
                "/orchestrate",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:3000")
        self.assertIn("POST", response.headers["access-control-allow-methods"])

    def test_unknown_origin_is_not_allowed(self) -> None:
        with TestClient(app) as client:
            response = client.options(
                "/orchestrate",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )

        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
