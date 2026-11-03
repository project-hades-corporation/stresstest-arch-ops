import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import type { AppState, BinaryFiles } from "@excalidraw/excalidraw/types";

export type NodeStatus = "CRITICAL" | "WARNING" | "OK";

export type ScenarioType = "traffic_surge" | "database_outage" | "custom";

export interface CanvasSceneData {
  elements: ExcalidrawElement[];
  appState?: Partial<AppState>;
  files?: BinaryFiles;
}

export interface StressScenarioRequest {
  scenario_type: ScenarioType;
  architecture_name?: string;
  scenario_text?: string;
  traffic_multiplier?: number;
  baseline_rps?: number;
  dropped_nodes?: string[];
}

export interface AnnotatedTopology {
  topology: {
    nodes: Array<Record<string, unknown> & { id: string; status: NodeStatus }>;
    edges: Array<Record<string, unknown>>;
  };
  statuses: Record<string, NodeStatus>;
  element_statuses: Record<string, NodeStatus>;
  root_causes: Record<string, string>;
  spofs: string[];
  latency_bottlenecks: Array<Record<string, unknown>>;
  scenario: string;
  analysis: string;
  recommendations: Recommendation[];
}

export interface Recommendation {
  priority: "P1" | "P2" | "P3";
  severity: NodeStatus | "INFO";
  category: string;
  component: string;
  finding: string;
  actions: string[];
}

export interface SimulationReport {
  path: string;
  architecture_name?: string | null;
  markdown: string;
}

export interface CanvasElementLike {
  id: string;
  type: string;
  x?: number;
  y?: number;
  strokeColor?: string;
  backgroundColor?: string;
}

export interface StatusMap {
  [elementId: string]: NodeStatus;
}

export interface ThoughtEvent {
  type: string;
  agent?: string;
  step?: string;
  detail?: string;
  timestamp?: number;
}

export interface StressScenario {
  name: string;
  prompt: string;
}

export interface Blueprint {
  topology?: unknown;
  terraform_main?: string;
  terraform_variables?: string;
  docker_compose?: string;
  setup_commands?: string[];
  notes?: string;
}

export interface OrchestratorResponse {
  output?: Record<string, unknown>;
  scenario?: string;
  fixes?: Record<string, unknown>;
  blueprint?: Blueprint;
}
