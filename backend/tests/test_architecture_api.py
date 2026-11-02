"""Canvas persistence, deterministic simulation, and deployment API tests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.main as main


def _canvas() -> dict:
    return {
        "elements": [
            {"id": "client-shape", "type": "rectangle", "text": "Client", "x": 0, "y": 0, "width": 100, "height": 50},
            {"id": "gateway-shape", "type": "rectangle", "x": 150, "y": 0, "width": 120, "height": 60},
            {"id": "gateway-label", "type": "text", "containerId": "gateway-shape", "text": "API Gateway capacity 500 rps"},
            {"id": "database-shape", "type": "rectangle", "x": 330, "y": 0, "width": 120, "height": 60},
            {"id": "database-label", "type": "text", "containerId": "database-shape", "text": "Postgres database capacity 200 rps"},
            {
                "id": "gateway-arrow",
                "type": "arrow",
                "x": 270,
                "y": 30,
                "points": [[0, 0], [60, 0]],
                "startBinding": {"elementId": "gateway-shape"},
                "endBinding": {"elementId": "database-shape"},
            },
            {"id": "arrow-label", "type": "text", "containerId": "gateway-arrow", "text": "https 120ms"},
        ]
    }


class ArchitectureApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        self.canvas_path = temporary_root / "storage" / "canvas.json"
        self.output_directory = temporary_root / "report"
        self.report_directory = temporary_root / "reports"
        self.canvas_patch = patch.object(main, "CANVAS_PATH", self.canvas_path)
        self.output_patch = patch.object(main, "OUTPUT_DIR", self.output_directory)
        self.reports_patch = patch.object(main, "REPORTS_DIR", self.report_directory)
        self.canvas_patch.start()
        self.output_patch.start()
        self.reports_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.reports_patch.stop()
        self.output_patch.stop()
        self.canvas_patch.stop()
        self.temporary_directory.cleanup()

    def test_canvas_can_be_saved_and_loaded(self) -> None:
        canvas = _canvas()
        saved = self.client.post("/canvas", json=canvas)

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["element_count"], len(canvas["elements"]))
        self.assertEqual(self.client.get("/canvas").json(), canvas)

    def test_database_outage_returns_element_statuses_and_latency(self) -> None:
        self.client.post("/canvas", json=_canvas())

        response = self.client.post("/simulate", json={"scenario_type": "database_outage"})

        self.assertEqual(response.status_code, 200)
        output = response.json()["output"]
        self.assertEqual(output["statuses"]["postgres_database_capacity_200_rps"], "CRITICAL")
        self.assertEqual(output["element_statuses"]["database-shape"], "CRITICAL")
        self.assertEqual(len(output["latency_bottlenecks"]), 1)
        self.assertTrue(
            any(
                recommendation["category"] == "Availability"
                and recommendation["severity"] == "CRITICAL"
                for recommendation in output["recommendations"]
            )
        )

    def test_traffic_surge_flags_capacity_and_returns_canonical_graph(self) -> None:
        self.client.post("/canvas", json=_canvas())

        response = self.client.post(
            "/simulate",
            json={"scenario_type": "traffic_surge", "traffic_multiplier": 10},
        )

        self.assertEqual(response.status_code, 200)
        output = response.json()["output"]
        self.assertEqual(output["scenario"], "Traffic Surge")
        self.assertEqual(output["statuses"]["api_gateway_capacity_500_rps"], "CRITICAL")
        self.assertEqual(len(output["topology"]["nodes"]), 3)
        self.assertEqual(len(output["topology"]["edges"]), 1)
        capacity_recommendation = next(
            recommendation
            for recommendation in output["recommendations"]
            if recommendation["category"] == "Capacity"
            and recommendation["component"] == "API Gateway capacity 500 rps"
        )
        self.assertIn("at least 3 balanced instances", capacity_recommendation["actions"][0])

    def test_capacity_bottleneck_gets_a_warning_recommendation(self) -> None:
        self.client.post(
            "/canvas",
            json={
                "elements": [
                    {
                        "id": "worker",
                        "type": "rectangle",
                        "text": "Worker capacity 110 rps",
                    }
                ]
            },
        )

        response = self.client.post(
            "/simulate",
            json={
                "scenario_type": "traffic_surge",
                "traffic_multiplier": 1,
                "baseline_rps": 100,
            },
        )

        self.assertEqual(response.status_code, 200)
        output = response.json()["output"]
        self.assertEqual(output["statuses"]["worker_capacity_110_rps"], "WARNING")
        recommendation = next(
            item
            for item in output["recommendations"]
            if item["category"] == "Capacity"
        )
        self.assertEqual(recommendation["severity"], "WARNING")
        self.assertIn("above the 80% warning threshold", recommendation["finding"])

    def test_simulation_saves_detailed_report_and_updates_the_same_file(self) -> None:
        self.client.post("/canvas", json=_canvas())

        first_response = self.client.post(
            "/simulate",
            json={"scenario_type": "traffic_surge", "traffic_multiplier": 10},
        )
        first_report = first_response.json()["report"]
        report_file = self.report_directory / "stress-report.md"
        first_contents = report_file.read_text(encoding="utf-8")

        second_response = self.client.post(
            "/simulate",
            json={
                "scenario_type": "custom",
                "scenario_text": "Reduced traffic baseline",
                "traffic_multiplier": 1,
                "dropped_nodes": [],
            },
        )
        second_report = second_response.json()["report"]
        second_contents = report_file.read_text(encoding="utf-8")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_report["path"], "reports/stress-report.md")
        self.assertEqual(second_report["path"], first_report["path"])
        self.assertEqual(second_contents, second_report["markdown"])
        self.assertNotEqual(first_contents, second_contents)
        self.assertIn("## Scenario and assumptions", second_contents)
        self.assertIn("## Architecture inventory", second_contents)
        self.assertIn("## Findings and root causes", second_contents)
        self.assertIn("## Prioritized recommendations", second_contents)
        self.assertIn("## Methodology and limitations", second_contents)
        self.assertIn("Reduced traffic baseline", second_contents)
        saved_report = self.client.get("/reports/latest")
        self.assertEqual(saved_report.status_code, 200)
        self.assertEqual(saved_report.json(), second_report)

    def test_latest_report_is_not_found_before_a_simulation(self) -> None:
        response = self.client.get("/reports/latest")

        self.assertEqual(response.status_code, 404)
        self.assertIn("No simulation report", response.json()["detail"])

    def test_deployment_generates_report_files_from_saved_canvas(self) -> None:
        self.client.post("/canvas", json=_canvas())

        response = self.client.post("/deployment")

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(set(result["files"]), {"main.tf", "variables.tf", "docker-compose.yml"})
        self.assertIn("aws_db_instance", result["blueprint"]["terraform_main"])
        self.assertTrue((self.output_directory / "main.tf").is_file())
        self.assertTrue((self.output_directory / "variables.tf").is_file())
        self.assertTrue((self.output_directory / "docker-compose.yml").is_file())

    def test_database_outage_requires_database_node(self) -> None:
        self.client.post(
            "/canvas",
            json={"elements": [{"id": "web", "type": "rectangle", "text": "Web service"}]},
        )

        response = self.client.post("/simulate", json={"scenario_type": "database_outage"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("No database component", response.json()["detail"])

    def test_canvas_is_required_before_simulation(self) -> None:
        response = self.client.post("/simulate", json={"scenario_type": "traffic_surge"})

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
