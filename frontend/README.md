# Architecture Stress Platform — Next.js Frontend

React 18 + Next.js 14 (App Router) + Material UI 6 + Excalidraw canvas.

## Commands

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
npm run build
npm start
```

## Features

- **Canvas** (`src/components/Canvas.tsx`): embeds `@excalidraw/excalidraw`; backend status annotations recolor elements (red = critical, yellow = warning, green = ok).
- **Scenario drawer** (`src/components/ScenarioDrawer.tsx`): preset + custom scenarios, "Run Stress Test" triggers backend orchestrator run.
- **Fix & recycle loop**: suggested fixes surfaced via API, "Apply Fixes to Canvas" re-runs simulation.
- **Deployment export** (`src/components/BlueprintModal.tsx`): Terraform / Docker Compose / shell commands in syntax-highlighted editor with copy button.

## Config

- `NEXT_PUBLIC_API_BASE_URL` — backend base URL (default `http://localhost:8000`).
- `NEXT_PUBLIC_WS_URL` — backend WebSocket URL used by the thought stream (defaults to the API base URL's `/ws/stress` endpoint).
