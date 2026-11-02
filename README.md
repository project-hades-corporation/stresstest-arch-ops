# LLM Gateway

Provider-agnostic LLM gateway built on [LiteLLM](https://github.com/BerriAI/litellm),
exposing a single async interface for every supported provider.

## Quick start

### One-command local setup

The setup scripts verify Python 3.10+ and Node.js 18+, reuse an existing
Python virtual environment or create `.venv`, and install backend and frontend
dependencies:

```bash
# Unix / macOS
chmod +x setup.sh
./setup.sh

# Windows
setup.bat
```

When setup finishes, open the workspace in your IDE, open your agent chat /
Copilot tab, and type: "Run the stress-arch skill to analyze my architecture."
The setup scripts do not start the application; use the commands below when
you want to launch it.
Use **Import** to load an `.excalidraw`/JSON scene, rebuild PNG/JPG/WEBP/BMP
diagrams as editable Excalidraw shapes, labels, and connectors instead of
retaining them as flat images, or extract editable text from TIFF images, PDFs,
Word `.doc`/`.docx`, Markdown, and text files. Image OCR and diagram
reconstruction run in the browser; `.doc` files are parsed by the local Next.js
server. Reconstructed diagrams are approximate and should be reviewed. Files
are limited to 10 MB, PDFs to 30 pages, and extracted text to 40,000 characters.

After setup has completed once, start the app without reinstalling packages:

```bash
# Unix / macOS / Windows Git Bash
bash ./start.sh

# Windows Command Prompt
start.bat
```

The start scripts reuse healthy services if they are already running and show
the backend and frontend log locations if startup fails.

Running a simulation creates a detailed Markdown report at
`reports/stress-report.md`. Each subsequent run replaces that same file with
the latest scenario results. The canvas shows a **View report & recommendations**
action after a run and restores the latest report after reload; the report
includes component and connection findings,
scenario assumptions, prioritized deterministic remediation guidance, and
limitations of the estimate. Capacity and replica targets are estimates, not
validated production settings.

### Containerized setup

With Docker Compose installed, start the backend and frontend with:

```bash
docker-compose up
```

The Compose backend expects a host Ollama service on port `11434`; AI CLIs
installed on the host are not automatically available inside containers.
For a manual Python setup, install the project dependencies from the repository
root:

```bash
python -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

On Windows Command Prompt, use `.venv\Scripts\python.exe -m pip install -r requirements.txt`.

Copy `.env.example` to `.env` and adjust provider settings if needed.

## Zero-API-key / local-first usage

The gateway is **keyless by default** and works out of the box with locally
installed model tooling — no user API key or secret required:

- **Ollama** (default): `DEFAULT_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_MODEL=gemma4:latest`
- **OpenCode**: set `DEFAULT_PROVIDER=opencode`, `OPENCODE_BASE_URL=http://localhost:8080/v1`, `OPENCODE_MODEL=<model>` — the OpenCode local server is OpenAI-compatible and authenticates via the local CLI (no key).
- **LiteLLM Proxy**: set `DEFAULT_PROVIDER=litellm`, `LITELLM_BASE_URL=http://localhost:4000`, `LITELLM_API_KEY=<proxy-key>`, `LITELLM_MODEL=<virtual-model>` — an OpenAI-compatible gateway that holds provider keys and routes to providers (Gemini, Claude, Kimi, Copilot, ...), so end users never handle raw provider keys.
- **Any local OpenAI-compatible server**: `DEFAULT_PROVIDER=custom`, `CUSTOM_BASE_URL=http://localhost:8000/v1` (LM Studio / vLLM / llama.cpp), no key needed.

This means end users can simply run the app inside their existing terminal
tooling (e.g. OpenCode CLI / Copilot-assisted workflows) against local models
and never provision a provider API key themselves.

For hosted providers (OpenAI / Anthropic / Gemini), set the respective
`*_API_KEY` / `*_MODEL` / `*_FALLBACK_MODELS` variables in `.env`.

## Keyless CLI Gateway (`backend/gateway/cli_gateway.py`)

For users who already have AI CLIs installed (Copilot, Claude, Gemini, Grok,
Kimi, OpenCode, Ollama) and do not want to manage API keys at all:

1. **Dynamic binary discovery** – on startup, scan `$PATH` for the configured
   AI tool binaries (`copilot`, `gemini`, `claude`, `ollama`, `opencode`, `grok`, `kimi`).
2. **Local proxy endpoints** – probe local daemons (`OLLAMA_BASE_URL`, VS Code
   Copilot bridge at `http://127.0.0.1:3030/v1`).
3. **Fallback chain** (`CLIGateway.generate`):
   - Priority 1: direct async CLI subprocess (`CLIRunner` via
     `asyncio.create_subprocess_exec`) – e.g. `ollama run <model> <prompt>`.
   - Priority 2: local HTTP daemon if detected.
   - Priority 3: standard `.env` API key via the hosted gateway.

Unified keyless interface:

```python
from backend.gateway.cli_gateway import CLIGateway

gateway = CLIGateway()
text = await gateway.generate(
    prompt="Summarize this in one sentence",
    system_prompt="You are a concise summarizer.",
    provider_hint="auto",  # or "ollama" | "claude" | "copilot" | "opencode" | ...
)
```

## Configuration (`.env`)

| Variable | Provider | Description |
|---|---|---|
| `DEFAULT_PROVIDER` | all | `ollama` \| `openai` \| `anthropic` \| `gemini` \| `custom` |
| `OLLAMA_BASE_URL` | ollama | e.g. `http://localhost:11434` |
| `OLLAMA_MODEL` | ollama | e.g. `gemma4:latest` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_FALLBACK_MODELS` | openai | fallback models comma-separated |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_FALLBACK_MODELS` | anthropic | |
| `GOOGLE_API_KEY` / `GEMINI_MODEL` / `GEMINI_FALLBACK_MODELS` | gemini | |
| `CUSTOM_BASE_URL` / `CUSTOM_API_KEY` / `CUSTOM_MODEL` / `CUSTOM_FALLBACK_MODELS` | custom | OpenAI-compatible endpoint (vLLM, DeepSeek, Groq, …) |
| `OPENCODE_BASE_URL` / `OPENCODE_MODEL` / `OPENCODE_FALLBACK_MODELS` | opencode | Local OpenCode server (keyless, OpenAI-compatible) |
| `LITELLM_BASE_URL` / `LITELLM_API_KEY` / `LITELLM_MODEL` / `LITELLM_FALLBACK_MODELS` | litellm | LiteLLM Proxy server (keyless from the user's perspective) |
| `MAX_RETRIES` | all | Attempts per model (default `3`) |
| `RETRY_BACKOFF_FACTOR` | all | Exponential backoff base (default `0.5`) |
| `REQUEST_TIMEOUT` | all | Per-request timeout in seconds (default `30`) |

## Usage

```python
from backend.gateway.llm_provider import generate_completion

text = await generate_completion(
    prompt="Summarize this in one sentence",
    system_prompt="You are a concise summarizer.",
    model_override=None,        # or "openai/gpt-4o", "anthropic/claude-3-5-sonnet"
)

json_text = await generate_completion(
    prompt='Return {"status": "ok"}',
    system_prompt="Respond with valid JSON only.",
    json_mode=True,              # -> response_format json_object + validation
)
```

## Project structure

```text
scripts/            # Deterministic topology parsing, stress analysis, and reports
backend/
  agents/           # Base contract and individual ingress/stress/fix/blueprint agents
  gateway/          # Provider gateway and keyless CLI integrations
  models/           # Shared Pydantic schemas (topology, fixes, blueprints)
  tests/            # Backend smoke tests and agent pipeline checks
  requirements.txt  # Backend Python dependencies
  config.py         # Environment-backed settings
  orchestrator.py   # Agent routing, events, and session state
  main.py           # FastAPI application
reports/            # Latest simulation report; replaced on each run
frontend/
  components/       # Reusable UI components
  src/app/          # Next.js App Router pages and layout
  src/lib/          # API and WebSocket clients
  src/types.ts      # Shared frontend types
setup.sh
setup.bat
docker-compose.yml
README.md
```

The backend runs as the `backend` Python package (`backend.main:app`), so new
features can be organized by domain without adding modules to the repository
root. Backend test scripts are grouped under `backend/tests/`.

Key modules:
- `backend/config.py` – provider configuration and `.env` loading.
- `backend/gateway/llm_provider.py` – unified provider gateway with retries,
  model fallback, and structured-JSON handling.
- `backend/gateway/cli_gateway.py` – keyless CLI discovery, subprocess support,
  and local daemon probing.
- `backend/agents/` – base agent contract and focused worker implementations.
- `backend/models/topology_schema.py` – shared topology and output schemas.
- `backend/orchestrator.py` – agent routing, events, and session state.
- `backend/main.py` – FastAPI routes and application entry point.

## Test

```bash
python -m backend.tests.test_provider  # hosted/local provider connectivity via gateway
python -m backend.tests.test_gateway   # keyless CLI + local-daemon gateway test
python -m backend.tests.test_specialized_agents  # deterministic agent pipeline check
```

Pings the configured provider (Ollama: `/api/tags` + model presence; remote:
live completion) and exits non-zero on failure. The keyless gateway test
auto-detects installed CLI binaries on the host and verifies a single
completion prompt without requiring any API key.
