"""FastAPI backend for the Architecture Stress Platform.

Endpoints:
    POST /generate            -> unified LLM generation
    POST /orchestrate          -> full specialized-agent pipeline (ingress -> chaos -> fix -> blueprint)
    POST /orchestrate/fixes   -> apply suggested fixes
    WS /ws/stress              -> real-time agent thought streaming
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scripts.generate_iac import generate_files
from scripts.parse_topology import SHAPE_TYPES, _canonical_existing, _excalidraw_topology, _slug
from scripts.stress_engine import _analyze
from scripts.stress_report import write_report
from backend.agents.blueprint_agent import BlueprintGeneratorAgent
from backend.agents.fix_agent import ArchitecturalFixAgent
from backend.agents.ingress_agent import IngressParserAgent
from backend.agents.stress_agent import StressSimulatorAgent
from backend.config import get_settings
from backend.gateway.cli_gateway import CLIGateway
from backend.gateway.llm_provider import generate_completion
from backend.orchestrator import Orchestrator

app = FastAPI(title="Architecture Stress Platform", version="0.1.0")
ROOT_DIR = Path(__file__).resolve().parents[1]
CANVAS_PATH = ROOT_DIR / "backend" / "storage" / "canvas.json"
OUTPUT_DIR = ROOT_DIR / "output"
REPORTS_DIR = ROOT_DIR / "reports"
MAX_CANVAS_BYTES = 8 * 1024 * 1024
MAX_CANVAS_ELEMENTS = 5_000
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://0.0.0.0:3000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# --------------------------------------------------------------------- #
# REST endpoints
# --------------------------------------------------------------------- #
class GenerateRequestBody(BaseModel):
    prompt: str
    system_prompt: str = ""
    model_override: str | None = None
    json_mode: bool = False


class OrchestrationRequestBody(BaseModel):
    task: str
    context: dict[str, Any] = Field(default_factory=dict)


class FixRequestBody(BaseModel):
    fixes: dict[str, Any]


class CanvasSaveRequest(BaseModel):
    elements: list[dict[str, Any]] = Field(max_length=MAX_CANVAS_ELEMENTS)
    appState: dict[str, Any] | None = None
    files: dict[str, Any] | None = None


class StressSimulationRequest(BaseModel):
    scenario_type: Literal["traffic_surge", "database_outage", "custom"]
    architecture_name: str | None = Field(default=None, max_length=80)
    scenario_text: str | None = Field(default=None, max_length=1_000)
    traffic_multiplier: float | None = Field(default=None, gt=0)
    baseline_rps: float = Field(default=100, ge=0)
    dropped_nodes: list[str] = Field(default_factory=list, max_length=MAX_CANVAS_ELEMENTS)


def _read_saved_canvas() -> dict[str, Any]:
    try:
        saved = json.loads(CANVAS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No saved canvas. Add or import architecture first.")
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not read the saved canvas: {exc}") from exc
    if not isinstance(saved, dict) or not isinstance(saved.get("elements"), list):
        raise HTTPException(status_code=500, detail="Saved canvas data is invalid.")
    return saved


def _canvas_topology_and_mapping(canvas: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    canonical = _canonical_existing(canvas)
    try:
        topology = canonical if canonical is not None else _excalidraw_topology(canvas)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse canvas topology: {exc}") from exc

    elements = canvas.get("elements")
    if not isinstance(elements, list):
        return topology, {}
    text_by_container: dict[str, list[str]] = {}
    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "text":
            continue
        container_id = element.get("containerId")
        text = str(element.get("text") or "").strip()
        if container_id and text:
            text_by_container.setdefault(str(container_id), []).append(text)

    used: set[str] = set()
    element_node_map: dict[str, str] = {}
    node_index = 0
    for element in elements:
        if not isinstance(element, dict):
            continue
        element_type = str(element.get("type") or "").lower()
        if element_type not in SHAPE_TYPES or (
            element_type == "text" and element.get("containerId")
        ):
            continue
        label = str(element.get("label") or element.get("text") or "").strip()
        element_id = str(element.get("id") or "")
        if not label and element_id:
            label = " ".join(text_by_container.get(element_id, []))
        if not label and element_type == "text":
            continue
        node_index += 1
        if not label:
            label = f"{element_type or 'node'} {node_index}"
        node_id = _slug(label, f"node_{node_index}")
        candidate = node_id
        suffix = 2
        while candidate in used:
            candidate = f"{node_id}_{suffix}"
            suffix += 1
        used.add(candidate)
        if element_id:
            element_node_map[element_id] = candidate
    return topology, element_node_map


def _database_node_ids(topology: dict[str, Any]) -> list[str]:
    database_terms = ("database", "postgres", "mysql", "mariadb", "mongo", "dynamodb", "sql", " db")
    return [
        str(node["id"])
        for node in topology.get("nodes", [])
        if isinstance(node, dict)
        and any(
            term in f"{node.get('id', '')} {node.get('label', '')} {node.get('type', '')}".lower()
            for term in database_terms
        )
    ]


def _status_for_canvas_elements(
    topology: dict[str, Any], element_node_map: dict[str, str], node_statuses: dict[str, str]
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for element_id, node_id in element_node_map.items():
        status = node_statuses.get(node_id)
        if status:
            statuses[element_id] = status
    return statuses


@app.get("/canvas")
async def get_canvas() -> dict[str, Any]:
    if not CANVAS_PATH.exists():
        return {"elements": []}
    return _read_saved_canvas()


@app.post("/canvas")
async def save_canvas(body: CanvasSaveRequest) -> dict[str, Any]:
    canvas = body.model_dump(exclude_none=True)
    serialized = json.dumps(canvas, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > MAX_CANVAS_BYTES:
        raise HTTPException(status_code=413, detail="Canvas must be 8 MB or smaller.")
    try:
        CANVAS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=CANVAS_PATH.parent,
                prefix="canvas-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(serialized)
            os.replace(temporary_path, CANVAS_PATH)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save canvas: {exc}") from exc
    return {"ok": True, "element_count": len(body.elements)}


@app.post("/simulate")
async def simulate_stress(body: StressSimulationRequest) -> dict[str, Any]:
    canvas = _read_saved_canvas()
    topology, element_node_map = _canvas_topology_and_mapping(canvas)
    if not topology["nodes"]:
        raise HTTPException(status_code=422, detail="Add at least one architecture component before simulating.")

    if body.scenario_type == "traffic_surge":
        name = "Traffic Surge"
        multiplier = body.traffic_multiplier or 10.0
        dropped_nodes = body.dropped_nodes
    elif body.scenario_type == "database_outage":
        name = "Database Outage"
        multiplier = body.traffic_multiplier or 1.0
        dropped_nodes = body.dropped_nodes or _database_node_ids(topology)
        if not dropped_nodes:
            raise HTTPException(status_code=422, detail="No database component was found in the current canvas.")
    else:
        name = (body.scenario_text or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Enter a description for the custom scenario.")
        multiplier = body.traffic_multiplier or 1.0
        dropped_nodes = body.dropped_nodes

    scenario = {
        "name": name,
        "traffic_multiplier": multiplier,
        "baseline_rps": body.baseline_rps,
        "dropped_nodes": dropped_nodes,
    }
    try:
        result = _analyze(topology, scenario)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["element_statuses"] = _status_for_canvas_elements(
        topology, element_node_map, result["statuses"]
    )
    try:
        report_filename, report_markdown = write_report(
            REPORTS_DIR, result, body.architecture_name
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Simulation completed, but its report could not be saved: {exc}"
        ) from exc
    report_path = f"reports/{report_filename}"
    return {
        "output": result,
        "report": {
            "path": report_path,
            "architecture_name": (body.architecture_name or "").strip() or None,
            "markdown": report_markdown,
        },
    }


@app.get("/reports/latest")
async def get_latest_report() -> dict[str, str]:
    try:
        report_path = max(
            (path for path in REPORTS_DIR.glob("stress-report*.md") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=404, detail="No simulation report has been generated yet."
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not read the latest simulation report: {exc}"
        ) from exc
    try:
        markdown = report_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No simulation report has been generated yet.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not read the latest simulation report: {exc}") from exc
    return {"path": f"reports/{report_path.name}", "markdown": markdown}


@app.post("/deployment")
async def generate_deployment() -> dict[str, Any]:
    canvas = _read_saved_canvas()
    topology, _ = _canvas_topology_and_mapping(canvas)
    if not topology["nodes"]:
        raise HTTPException(status_code=422, detail="Add at least one architecture component before generating IaC.")
    try:
        files = generate_files(topology, OUTPUT_DIR)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not generate deployment files: {exc}") from exc
    return {
        "blueprint": {
            "terraform_main": files["main.tf"],
            "terraform_variables": files["variables.tf"],
            "docker_compose": files["docker-compose.yml"],
            "setup_commands": ["terraform init", "terraform validate", "terraform plan", "docker compose config"],
            "notes": f"Generated files were saved to {OUTPUT_DIR}. Review cloud inputs and security assumptions before deployment.",
        },
        "output_directory": str(OUTPUT_DIR),
        "files": list(files),
    }


@app.post("/generate")
async def generate(body: GenerateRequestBody) -> dict[str, Any]:
    if get_settings().use_keyless_cli and not body.model_override and not body.json_mode:
        text = await CLIGateway().generate(
            prompt=body.prompt,
            system_prompt=body.system_prompt,
        )
        return {"output": text}

    text = await generate_completion(
        prompt=body.prompt,
        system_prompt=body.system_prompt,
        model_override=body.model_override,
        json_mode=body.json_mode,
    )
    return {"output": text}


@app.post("/orchestrate")
async def orchestrate(body: OrchestrationRequestBody) -> dict[str, Any]:
    architecture_document = body.context.get("architecture_document")
    if architecture_document is not None and (
        not isinstance(architecture_document, str) or len(architecture_document) > 40_000
    ):
        raise HTTPException(
            status_code=422,
            detail="Architecture text must be a string of 40,000 characters or fewer.",
        )

    cli_gateway = CLIGateway()
    orchestrator = Orchestrator(
        agents={
            "ingress_parser": IngressParserAgent(gateway=cli_gateway),
            "stress_simulator": StressSimulatorAgent(gateway=cli_gateway),
            "architectural_fix": ArchitecturalFixAgent(gateway=cli_gateway),
            "blueprint_generator": BlueprintGeneratorAgent(gateway=cli_gateway),
        },
        default_agent="ingress_parser",
    )
    canonical_out = await orchestrator.dispatch({"task": body.task, "context": body.context})
    annotated = canonical_out if isinstance(canonical_out, dict) else {}
    return {"output": annotated}


@app.post("/orchestrate/fixes")
async def orchestrate_fixes(body: FixRequestBody) -> dict[str, Any]:
    return {"ok": True, "output": {"applied": True, "fixes": body.fixes}}


# --------------------------------------------------------------------- #
# WebSocket: real-time agent thought streaming
# --------------------------------------------------------------------- #
@app.websocket("/ws/stress")
async def stress_websocket(ws: WebSocket) -> None:
    await ws.accept()

    async def send_thought(event: dict[str, Any]) -> None:
        await ws.send_json(event)

    try:
        async for raw in ws.iter_text():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "detail": "WebSocket messages must be valid JSON."})
                continue
            if not isinstance(data, dict):
                await ws.send_json({"type": "error", "detail": "WebSocket messages must be JSON objects."})
                continue

            scenario = str(data.get("scenario") or data.get("task") or "10x traffic spike on the API gateway")

            cli_gateway = CLIGateway()
            parser = IngressParserAgent(gateway=cli_gateway)
            chaos = StressSimulatorAgent(gateway=cli_gateway)
            fixer = ArchitecturalFixAgent(gateway=cli_gateway)
            bp = BlueprintGeneratorAgent(gateway=cli_gateway)

            await send_thought(
                {"type": "thought", "agent": "ingress_parser", "step": "parse", "detail": f"Parsing scenario: {scenario}"}
            )
            canonical = await parser.execute({"task": scenario})
            await send_thought(
                {"type": "thought", "agent": "stress_simulator", "step": "chaos", "detail": f"Running chaos analysis for: {scenario}"}
            )
            annotated = await chaos.execute({"task": json.dumps(canonical), "context": {"scenario": scenario}})
            await send_thought(
                {"type": "thought", "agent": "architectural_fix", "step": "fix", "detail": "Generating architectural fixes"}
            )
            fixes = await fixer.execute({"task": json.dumps(annotated)})
            await send_thought(
                {"type": "thought", "agent": "blueprint_generator", "step": "blueprint", "detail": "Generating deployment blueprint"}
            )
            blueprint = await bp.execute({"task": json.dumps(canonical)})

            await ws.send_json(
                {
                    "type": "pipeline_result",
                    "scenario": scenario,
                    "output": annotated,
                    "fixes": fixes,
                    "blueprint": blueprint,
                }
            )
            break
    except WebSocketDisconnect:
        return

    await ws.close()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
