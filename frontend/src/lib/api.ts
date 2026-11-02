import type {
  AnnotatedTopology,
  Blueprint,
  CanvasSceneData,
  SimulationReport,
  StressScenarioRequest,
} from "../types";
import type { AppState } from "@excalidraw/excalidraw/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

export interface GenerateRequest {
  prompt: string;
  system_prompt: string;
  model_override?: string;
  json_mode?: boolean;
}

export interface GenerateResponse {
  output?: string;
  error?: string;
}

export async function generateCompletion(
  prompt: string,
  systemPrompt: string,
  opts: { modelOverride?: string; jsonMode?: boolean } = {}
): Promise<string> {
  const res = await fetch(`${API_BASE_URL}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      system_prompt: systemPrompt,
      model_override: opts.modelOverride,
      json_mode: opts.jsonMode ?? false,
    } satisfies GenerateRequest),
  });
  const data = (await res.json()) as GenerateResponse;
  if (!res.ok) throw new Error(data.error || `Backend error: ${res.status}`);
  if (data.output === undefined) throw new Error("Backend returned no output");
  return data.output;
}

export interface RunScenarioRequest {
  task: string;
  context?: Record<string, unknown>;
}

export interface RunScenarioResponse {
  output?: Record<string, unknown>;
  fixes?: Record<string, unknown>;
  blueprint?: Blueprint;
}

async function responseError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown; error?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (typeof data.error === "string") return data.error;
  } catch {
    // The response body may not be JSON.
  }
  return `Backend error: ${response.status}`;
}

export function normalizeCanvasScene(canvas: CanvasSceneData): CanvasSceneData {
  if (!canvas.appState) return canvas;
  const appState: Partial<AppState> = { ...canvas.appState };
  delete appState.collaborators;
  delete appState.width;
  delete appState.height;
  delete appState.offsetLeft;
  delete appState.offsetTop;
  delete appState.isLoading;
  return { ...canvas, appState };
}

export async function loadCanvas(): Promise<CanvasSceneData> {
  const response = await fetch(`${API_BASE_URL}/canvas`);
  if (!response.ok) throw new Error(await responseError(response));
  const data = (await response.json()) as CanvasSceneData;
  if (!Array.isArray(data.elements)) throw new Error("Backend returned invalid canvas data.");
  return normalizeCanvasScene(data);
}

export async function saveCanvas(canvas: CanvasSceneData): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/canvas`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(normalizeCanvasScene(canvas)),
  });
  if (!response.ok) throw new Error(await responseError(response));
}

export async function simulateStress(
  scenario: StressScenarioRequest
): Promise<{ output: AnnotatedTopology; report: SimulationReport }> {
  const response = await fetch(`${API_BASE_URL}/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(scenario),
  });
  if (!response.ok) throw new Error(await responseError(response));
  const data = (await response.json()) as {
    output?: AnnotatedTopology;
    report?: SimulationReport;
  };
  if (
    !data.output?.statuses ||
    !data.output.element_statuses ||
    !Array.isArray(data.output.recommendations) ||
    typeof data.report?.path !== "string" ||
    typeof data.report.markdown !== "string"
  ) {
    throw new Error("Backend returned an incomplete simulation report.");
  }
  return { output: data.output, report: data.report };
}

export async function loadLatestReport(): Promise<SimulationReport | null> {
  const response = await fetch(`${API_BASE_URL}/reports/latest`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(await responseError(response));
  const report = (await response.json()) as Partial<SimulationReport>;
  if (typeof report.path !== "string" || typeof report.markdown !== "string") {
    throw new Error("Backend returned an incomplete saved report.");
  }
  return { path: report.path, markdown: report.markdown };
}

export async function generateDeployment(): Promise<Blueprint> {
  const response = await fetch(`${API_BASE_URL}/deployment`, { method: "POST" });
  if (!response.ok) throw new Error(await responseError(response));
  const data = (await response.json()) as { blueprint?: Blueprint };
  if (!data.blueprint) throw new Error("Backend returned no deployment blueprint.");
  return data.blueprint;
}

export async function runStressScenario(
  scenario: string,
  architecture?: string
): Promise<RunScenarioResponse> {
  const res = await fetch(`${API_BASE_URL}/orchestrate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task: scenario,
      context: architecture ? { architecture_document: architecture } : undefined,
    } satisfies RunScenarioRequest),
  });
  const data = (await res.json()) as RunScenarioResponse & { error?: string; detail?: string };
  if (!res.ok) {
    throw new Error(data.error || data.detail || `Backend error: ${res.status}`);
  }
  return data;
}

export async function applyFixes(fixes: Record<string, unknown>): Promise<{ ok: boolean; output?: Record<string, unknown> }> {
  const res = await fetch(`${API_BASE_URL}/orchestrate/fixes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fixes }),
  });
  const data = (await res.json()) as { ok?: boolean; output?: Record<string, unknown> };
  if (!res.ok) throw new Error((data as { error?: string }).error || `Backend error: ${res.status}`);
  return { ok: Boolean(data.ok), output: data.output };
}
