---
name: stress-arch
description: "Use for architecture parsing, topology modeling, chaos or stress testing, failure remediation, Terraform or Docker Compose generation, and starting the Architecture Stress Platform. Trigger for /stress-arch commands or @stress-arch mentions."
argument-hint: "parse [input] | test [scenario] | fix | iac | start"
user-invocable: true
disable-model-invocation: false
---

# Stress Architecture

Use this skill to turn architecture descriptions into canonical topology, test
failure scenarios, suggest architectural changes, generate infrastructure
blueprints, and start the local platform. `/stress-arch` exposes this workflow
as a slash command; `@stress-arch` and related architecture/stress requests
should also load the skill automatically.

## Command routing

Run commands from the repository root. Architecture parsing, stress estimates,
and blueprint generation use the standard-library deterministic helpers in
[`scripts/`](../../../scripts/). They need no LLM credentials.
[`scripts/stress_arch.py`](../../../scripts/stress_arch.py) is the existing
AI-backed `fix` and local service `start` wrapper.

The helpers run with Python 3 and the standard library:

```powershell
python .\scripts\<helper>.py ...
```

```bash
python ./scripts/<helper>.py ...
```

Use the repository virtual environment if available. Image OCR additionally
requires the Tesseract executable on `PATH`; Excalidraw JSON parsing does not.

### `/stress-arch parse`

Read the current Excalidraw canvas/export or image path. Save an Excalidraw
export as JSON when the canvas itself is not available as a file. Parse it into
canonical `nodes` and `edges`:

```bash
python ./scripts/parse_topology.py ./excalidraw.json --output ./topology.json
python ./scripts/parse_topology.py ./architecture.png --output ./topology.json
```

Image OCR uses Tesseract to recognize labels and explicit arrow text; it cannot
recover unlabeled visual connectors. If the image yields no explicit
relationships, report that limitation instead of inventing edges. Preserve
the output JSON for subsequent commands.

### `/stress-arch test [scenario]`

Use a scenario supplied by the user, or ask for its traffic multiplier,
baseline request rate, and dropped node IDs if they are missing. Save those
values as JSON (for example
`{"name":"traffic surge","traffic_multiplier":10,"baseline_rps":100,"dropped_nodes":[]}`),
then pass it with the canonical topology:

```bash
python ./scripts/stress_engine.py ./topology.json ./scenario.json --output ./annotated_topology.json
```

The deterministic engine estimates the same baseline request rate on each
component, flags capacity utilization, detects graph SPOFs, and identifies
edge latency thresholds. It does not generate live traffic or measure runtime
latency. Capacity values of zero mean unknown and are reported as warnings.

### `/stress-arch fix`

Use the annotated JSON produced by `test` and generate proposed architectural
mutations for critical or warning findings:

```bash
python ./scripts/stress_arch.py fix --annotated ./annotated_topology.json
```

Explain the proposed changes and rationale. Treat mutations as recommendations,
not applied changes.

### `/stress-arch iac`

Generate AWS ECS/Fargate Terraform and Docker Compose from an approved
canonical topology. Files are written under `./output/` by default; change
that to a report directory if requested:

```bash
python ./scripts/generate_iac.py ./topology.json --output-dir ./output
```

The Terraform baseline uses an existing VPC and at least two private subnets;
it creates ECS/Fargate app services and managed RDS for database nodes (client
nodes are not deployed). Provide region, image URIs, and infrastructure inputs
before applying it. Database endpoint/secret metadata is output separately;
wire each application's task role to only the secrets it needs. Review
networking, secrets, scaling, persistence, health checks, and cost assumptions
before presenting it as production-deployable. Never fabricate credentials or
apply infrastructure changes.

### `/stress-arch start`

Start the local FastAPI backend and Next.js frontend using the repository's
existing startup scripts. They check dependencies and service health:

```powershell
.\.venv\Scripts\python.exe .\scripts\stress_arch.py start
```

```bash
./.venv/bin/python ./scripts/stress_arch.py start
```

This delegates to `start.bat` on Windows and `start.sh` elsewhere. Report any
startup error and the log location shown by the script; do not claim the
services are running unless startup succeeds.

## Output and safety

- Keep command outputs in their structured JSON shape; summarize relevant
  fields without inventing nodes, findings, fixes, or deployment values.
- Validate that required input files exist and contain JSON objects. If
  required topology or scenario context is missing, ask for it rather than
  producing a success-shaped guess.
- `test` is a deterministic estimate, not a live load test. `fix` uses the
  configured AI agent. Do not apply generated mutations or infrastructure
  without explicit authorization.
