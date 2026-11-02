"""CLI entry point for the stress-arch skill."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON input from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


async def _run_agent(command: str, args: argparse.Namespace) -> None:
    from backend.agents.blueprint_agent import BlueprintGeneratorAgent
    from backend.agents.fix_agent import ArchitecturalFixAgent
    from backend.agents.ingress_agent import IngressParserAgent
    from backend.agents.stress_agent import StressSimulatorAgent
    from backend.gateway.cli_gateway import CLIGateway

    gateway = CLIGateway()
    if command == "parse":
        source = args.input if args.input is not None else args.input_file.read_text(encoding="utf-8")
        agent = IngressParserAgent(gateway=gateway)
        task = {"task": source, "context": {"architecture_document": source}}
    elif command == "test":
        topology = _read_json(args.topology)
        agent = StressSimulatorAgent(gateway=gateway)
        task = {"task": args.scenario, "context": {"topology": topology}}
    elif command == "fix":
        annotated = _read_json(args.annotated)
        agent = ArchitecturalFixAgent(gateway=gateway)
        task = {"task": json.dumps(annotated, ensure_ascii=False)}
    else:
        topology = _read_json(args.topology)
        agent = BlueprintGeneratorAgent(gateway=gateway)
        task = {"task": json.dumps(topology, ensure_ascii=False)}

    _print_json(await agent.execute(task))


def _start_services() -> None:
    if sys.platform == "win32":
        command = ["cmd.exe", "/c", str(ROOT / "start.bat")]
    else:
        command = ["bash", str(ROOT / "start.sh")]
    subprocess.run(command, cwd=ROOT, check=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a stress-arch workflow using the platform's configured LLM gateway."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    parse = commands.add_parser("parse", help="Convert architecture input into canonical topology JSON.")
    source = parse.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Architecture prompt, OCR text, or Excalidraw JSON.")
    source.add_argument("--input-file", type=Path, help="UTF-8 text file containing architecture input.")

    test = commands.add_parser("test", help="Analyze a topology against a stress scenario.")
    test.add_argument("scenario", help="Scenario, such as '10x traffic surge' or 'database failure'.")
    test.add_argument("--topology", type=Path, required=True, help="Canonical topology JSON file.")

    fix = commands.add_parser("fix", help="Propose topology mutations for an annotated topology.")
    fix.add_argument("--annotated", type=Path, required=True, help="Annotated topology JSON file.")

    iac = commands.add_parser("iac", help="Generate Terraform and Docker Compose blueprint JSON.")
    iac.add_argument("--topology", type=Path, required=True, help="Canonical topology JSON file.")

    commands.add_parser("start", help="Start the local FastAPI backend and Next.js frontend.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        if args.command == "start":
            _start_services()
        else:
            asyncio.run(_run_agent(args.command, args))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"stress-arch: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
