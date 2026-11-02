"""Convert Excalidraw exports, architecture text, or OCR text into topology JSON."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
SHAPE_TYPES = {
    "diamond",
    "ellipse",
    "frame",
    "hexagon",
    "rectangle",
    "rhombus",
    "roundedrectangle",
    "text",
    "trapezoid",
}
ARROW_SPLIT = re.compile(r"\s*(?:->|→|➜|⟶|-->|=>)\s*")
CAPACITY = re.compile(r"\b(?:capacity\s*[:=]?\s*)?([\d,]+)\s*(?:rps|req(?:uests)?/s)\b", re.I)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("The Excalidraw export must contain a JSON object.")
    return value


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or fallback


def _infer_type(label: str) -> str:
    value = label.lower()
    if any(token in value for token in ("gateway", "load balancer", "ingress", "proxy")):
        return "api_gateway"
    if any(token in value for token in ("postgres", "mysql", "database", " db", "sql")):
        return "database"
    if any(token in value for token in ("redis", "cache", "memcached")):
        return "cache"
    if any(token in value for token in ("queue", "kafka", "rabbit", "broker")):
        return "queue"
    if any(token in value for token in ("client", "browser", "user")):
        return "client"
    return "service"


def _capacity(label: str) -> int:
    match = CAPACITY.search(label)
    return int(match.group(1).replace(",", "")) if match else 0


def _canonical_existing(data: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(data.get("nodes"), list) or not isinstance(data.get("edges"), list):
        return None
    nodes: list[dict[str, Any]] = []
    for index, value in enumerate(data["nodes"]):
        if not isinstance(value, dict):
            raise ValueError(f"Canonical topology node {index} must be an object.")
        label = str(value.get("label") or value.get("id") or f"service_{index + 1}").strip()
        node_id = _slug(str(value.get("id") or label), f"service_{index + 1}")
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "type": str(value.get("type") or _infer_type(label)),
                "capacity_rps": int(value.get("capacity_rps") or _capacity(label)),
            }
        )
    ids = {node["id"] for node in nodes}
    edges: list[dict[str, Any]] = []
    for index, value in enumerate(data["edges"]):
        if not isinstance(value, dict):
            raise ValueError(f"Canonical topology edge {index} must be an object.")
        source = _slug(str(value.get("source") or ""), "")
        target = _slug(str(value.get("target") or ""), "")
        if source not in ids or target not in ids:
            raise ValueError(f"Canonical topology edge {index} references an unknown node.")
        edges.append(
            {
                "source": source,
                "target": target,
                "protocol": str(value.get("protocol") or "http"),
                "latency_ms": max(0, int(value.get("latency_ms") or 0)),
            }
        )
    return {"nodes": nodes, "edges": edges}


def _new_id(label: str, fallback: str, used: set[str]) -> str:
    base = _slug(label, fallback)
    node_id = base
    suffix = 2
    while node_id in used:
        node_id = f"{base}_{suffix}"
        suffix += 1
    used.add(node_id)
    return node_id


def _text_topology(text: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    used: set[str] = set()
    labels: dict[str, str] = {}

    def add_node(label: str) -> str:
        label = " ".join(label.split()).strip(" -:|")
        if not label:
            raise ValueError("Architecture text contains an empty component label.")
        normalized = label.casefold()
        if normalized in labels:
            return labels[normalized]
        node_id = _new_id(label, f"node_{len(nodes) + 1}", used)
        labels[normalized] = node_id
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "type": _infer_type(label),
                "capacity_rps": _capacity(label),
            }
        )
        return node_id

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        pieces = ARROW_SPLIT.split(line)
        if len(pieces) > 1:
            chain = [add_node(piece) for piece in pieces if piece.strip()]
            edges.extend(
                {"source": source, "target": target, "protocol": "http", "latency_ms": 0}
                for source, target in zip(chain, chain[1:])
            )
        else:
            add_node(line)
    return {"nodes": nodes, "edges": edges}


def _distance_to_box(x: float, y: float, element: dict[str, Any]) -> float:
    left = float(element.get("x") or 0)
    top = float(element.get("y") or 0)
    right = left + max(0.0, float(element.get("width") or 0))
    bottom = top + max(0.0, float(element.get("height") or 0))
    dx = max(left - x, 0.0, x - right)
    dy = max(top - y, 0.0, y - bottom)
    return (dx * dx + dy * dy) ** 0.5


def _excalidraw_topology(data: dict[str, Any]) -> dict[str, Any]:
    elements = data.get("elements")
    if not isinstance(elements, list):
        raise ValueError("Excalidraw JSON must contain an 'elements' array.")
    element_by_id = {
        str(element.get("id")): element
        for element in elements
        if isinstance(element, dict) and element.get("id") is not None
    }
    text_by_container: dict[str, list[str]] = {}
    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "text":
            continue
        container_id = element.get("containerId")
        content = str(element.get("text") or "").strip()
        if container_id and content:
            text_by_container.setdefault(str(container_id), []).append(content)

    nodes: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    element_to_node: dict[str, str] = {}
    shape_elements: list[dict[str, Any]] = []
    standalone_texts: list[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        element_type = str(element.get("type") or "").lower()
        element_id = str(element.get("id") or "")
        if element_type in {"arrow", "line"}:
            continue
        if element_type not in SHAPE_TYPES:
            continue
        if element_type == "text" and element.get("containerId"):
            continue
        label = str(element.get("label") or element.get("text") or "").strip()
        if not label and element_id:
            label = " ".join(text_by_container.get(element_id, []))
        if not label and element_type == "text":
            continue
        if not label:
            label = f"{element_type or 'node'} {len(nodes) + 1}"
        node_id = _new_id(label, f"node_{len(nodes) + 1}", used_ids)
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "type": _infer_type(label),
                "capacity_rps": _capacity(label),
            }
        )
        if element_id:
            element_to_node[element_id] = node_id
        shape_elements.append(element)

    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "text" or element.get("containerId"):
            continue
        text = str(element.get("text") or "").strip()
        if text:
            standalone_texts.append(text)

    if not nodes and standalone_texts:
        return _text_topology("\n".join(standalone_texts))

    # Standalone text can encode explicit relationships, e.g. "web -> api -> db".
    text_edges = _text_topology("\n".join(standalone_texts)) if standalone_texts else {"nodes": [], "edges": []}
    by_label = {node["label"].casefold(): node["id"] for node in nodes}
    for text_node in text_edges["nodes"]:
        if text_node["label"].casefold() not in by_label:
            node_id = _new_id(text_node["label"], f"node_{len(nodes) + 1}", used_ids)
            text_node["id"] = node_id
            nodes.append(text_node)
            by_label[text_node["label"].casefold()] = node_id
    for edge in text_edges["edges"]:
        source_label = next(node["label"] for node in text_edges["nodes"] if node["id"] == edge["source"])
        target_label = next(node["label"] for node in text_edges["nodes"] if node["id"] == edge["target"])
        edges_from_text = (by_label[source_label.casefold()], by_label[target_label.casefold()])
        text_edges.setdefault("_resolved_edges", []).append(edges_from_text)

    edges: list[dict[str, Any]] = []
    for source_id, target_id in text_edges.get("_resolved_edges", []):
        edges.append({"source": source_id, "target": target_id, "protocol": "http", "latency_ms": 0})

    def bound_node(binding: Any) -> str | None:
        if not isinstance(binding, dict) or not binding.get("elementId"):
            return None
        bound_id = str(binding["elementId"])
        if bound_id in element_to_node:
            return element_to_node[bound_id]
        container = element_by_id.get(bound_id, {}).get("containerId")
        return element_to_node.get(str(container)) if container else None

    def endpoint_node(x: float, y: float) -> str | None:
        if not shape_elements:
            return None
        nearest = min(shape_elements, key=lambda item: _distance_to_box(x, y, item))
        if _distance_to_box(x, y, nearest) > 64:
            return None
        return element_to_node.get(str(nearest.get("id") or ""))

    for element in elements:
        if not isinstance(element, dict) or element.get("type") not in {"arrow", "line"}:
            continue
        points = element.get("points")
        start = bound_node(element.get("startBinding"))
        end = bound_node(element.get("endBinding"))
        if isinstance(points, list) and points and isinstance(points[0], (list, tuple)):
            origin_x, origin_y = float(element.get("x") or 0), float(element.get("y") or 0)
            first = (origin_x + float(points[0][0]), origin_y + float(points[0][1]))
            last_point = points[-1]
            last = (origin_x + float(last_point[0]), origin_y + float(last_point[1]))
            start = start or endpoint_node(*first)
            end = end or endpoint_node(*last)
        if not start or not end:
            continue
        label = " ".join(text_by_container.get(str(element.get("id") or ""), []))
        protocol_match = re.search(r"\b(http|https|grpc|tcp|udp|sql)\b", label, re.I)
        latency_match = re.search(r"\b(\d+)\s*ms\b", label, re.I)
        edges.append(
            {
                "source": start,
                "target": end,
                "protocol": protocol_match.group(1).lower() if protocol_match else "http",
                "latency_ms": int(latency_match.group(1)) if latency_match else 0,
            }
        )
    if not nodes:
        raise ValueError("No supported shapes, text, or nodes were found in the Excalidraw export.")
    return {"nodes": nodes, "edges": edges}


def _image_text(path: Path) -> str:
    executable = shutil.which("tesseract")
    if not executable:
        raise ValueError(
            "Image OCR requires the Tesseract executable on PATH. Install Tesseract, "
            "or provide an Excalidraw JSON/text export instead."
        )
    result = subprocess.run(
        [executable, str(path), "stdout", "-l", "eng", "--psm", "6"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        detail = result.stderr.strip() or f"Tesseract exited with status {result.returncode}."
        raise ValueError(f"OCR failed for {path}: {detail}")
    return result.stdout


def _convert(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Input file does not exist: {path}")
    if path.suffix.lower() in IMAGE_SUFFIXES:
        text = _image_text(path)
        topology = _text_topology(text)
        if not topology["edges"]:
            print(
                "Warning: OCR found no explicit arrow relationships; topology contains labels only.",
                file=sys.stderr,
            )
        return topology
    data = _read_json(path)
    existing = _canonical_existing(data)
    return existing if existing is not None else _excalidraw_topology(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract canonical nodes and edges from Excalidraw JSON or an image."
    )
    parser.add_argument("input", type=Path, help="Excalidraw JSON export or image file.")
    parser.add_argument("--output", type=Path, default=Path("topology.json"), help="Output JSON path.")
    args = parser.parse_args()
    try:
        topology = _convert(args.input)
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output paths must be different.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(topology, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"parse_topology: {exc}\n")
    print(f"Wrote {len(topology['nodes'])} nodes and {len(topology['edges'])} edges to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
