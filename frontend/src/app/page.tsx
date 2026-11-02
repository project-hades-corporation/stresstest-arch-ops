"use client";

import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Stack,
  Toolbar,
  Typography,
} from "@mui/material";
import ArchitectureOutlinedIcon from "@mui/icons-material/ArchitectureOutlined";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import CodeOutlinedIcon from "@mui/icons-material/CodeOutlined";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import SaveOutlinedIcon from "@mui/icons-material/SaveOutlined";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import type { AppState, BinaryFiles } from "@excalidraw/excalidraw/types";
import type { ImportedDataState } from "@excalidraw/excalidraw/data/types";
import BlueprintModal from "../../components/BlueprintViewer";
import ScenarioDrawer from "../../components/ScenarioPanel";
import SimulationReportDialog from "../../components/SimulationReportDialog";
import {
  generateDeployment,
  loadLatestReport,
  loadCanvas,
  normalizeCanvasScene,
  saveCanvas,
  simulateStress,
} from "../lib/api";
import { extractArchitectureFile } from "../lib/architectureUpload";
import { convertImageToDiagram } from "../lib/imageToDiagram";
import type {
  Blueprint,
  CanvasSceneData,
  NodeStatus,
  SimulationReport,
  StressScenarioRequest,
} from "../types";

const Canvas = dynamic(() => import("../../components/CanvasExcalidraw"), {
  ssr: false,
  loading: () => (
    <Stack spacing={2} sx={{ height: "100%", alignItems: "center", justifyContent: "center" }}>
      <CircularProgress size={28} />
      <Typography color="text.secondary">Loading canvas…</Typography>
    </Stack>
  ),
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("Could not read the imported image."));
    };
    reader.onerror = () => reject(new Error("Could not read the imported image."));
    reader.readAsDataURL(file);
  });
}

function removeImportedImage(
  scene: CanvasSceneData,
  fileName: string,
  dataUrl: string,
  conversionKey: string,
  previouslySavedScene: CanvasSceneData
): { scene: CanvasSceneData; removedElements: number } {
  const matchingFileIds = new Set(
    Object.entries(scene.files ?? {})
      .filter(([, binaryFile]) => binaryFile.dataURL === dataUrl)
      .map(([fileId]) => fileId)
  );

  const imageIds = new Set(
    scene.elements
      .filter(
        (element) =>
          element.type === "image" &&
          element.fileId !== null &&
          matchingFileIds.has(element.fileId)
      )
      .map((element) => element.id)
  );
  const generatedIds = new Set(
    [...scene.elements, ...previouslySavedScene.elements]
      .filter(
        (element) => element.customData?.imageToDiagramSource === conversionKey
      )
      .map((element) => element.id)
  );
  if (imageIds.size === 0 && generatedIds.size === 0) {
    return { scene, removedElements: 0 };
  }

  const files: BinaryFiles = { ...scene.files };
  for (const fileId of matchingFileIds) {
    if (imageIds.size > 0) delete files[fileId];
  }

  const elements = scene.elements.filter(
    (element) =>
      !imageIds.has(element.id) &&
      !generatedIds.has(element.id) &&
      !(element.type === "text" && element.text.includes(fileName))
  );
  return {
    scene: { ...scene, elements, files },
    removedElements: scene.elements.length - elements.length,
  };
}

const STATUS_LEGEND: Array<{ label: string; color: string }> = [
  { label: "Healthy", color: "#22c55e" },
  { label: "Bottleneck", color: "#f59e0b" },
  { label: "Critical failure", color: "#ef4444" },
];

const CONVERTIBLE_IMAGE_EXTENSIONS = new Set(["bmp", "jpeg", "jpg", "png", "webp"]);

export default function Home() {
  const [canvasScene, setCanvasScene] = useState<CanvasSceneData>({ elements: [] });
  const [canvasReady, setCanvasReady] = useState(false);
  const [statusMap, setStatusMap] = useState<Record<string, NodeStatus>>({});
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [deploymentOpen, setDeploymentOpen] = useState(false);
  const [deploymentLoading, setDeploymentLoading] = useState(false);
  const [blueprint, setBlueprint] = useState<Blueprint | null>(null);
  const [error, setError] = useState("");
  const [simulationSummary, setSimulationSummary] = useState("");
  const [simulationReport, setSimulationReport] = useState<SimulationReport | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [canvasRevision, setCanvasRevision] = useState(0);
  const [importProgress, setImportProgress] = useState("");
  const [importing, setImporting] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const initialCanvasScene = useRef<CanvasSceneData>({ elements: [] });

  useEffect(() => {
    let active = true;
    loadCanvas()
      .then((scene) => {
        if (active) {
          initialCanvasScene.current = scene;
          setCanvasScene(scene);
        }
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "Could not load the saved canvas.");
        }
      })
      .finally(() => {
        if (active) setCanvasReady(true);
      });
    loadLatestReport()
      .then((report) => {
        if (active && report) setSimulationReport(report);
      })
      .catch((reportError: unknown) => {
        if (active) {
          setError(
            reportError instanceof Error
              ? reportError.message
              : "Could not load the latest simulation report."
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const handleCanvasChange = useCallback(
    (elements: readonly ExcalidrawElement[], appState: AppState, files: BinaryFiles) => {
      setCanvasScene({ elements: Array.from(elements), appState, files });
    },
    []
  );

  const persistCanvas = useCallback(async () => {
    setError("");
    setSaving(true);
    try {
      await saveCanvas(canvasScene);
    } catch (saveError) {
      const message = saveError instanceof Error ? saveError.message : "Could not save the canvas.";
      setError(message);
      throw saveError;
    } finally {
      setSaving(false);
    }
  }, [canvasScene]);

  useEffect(() => {
    if (!canvasReady) return;
    const timer = window.setTimeout(() => {
      void saveCanvas(canvasScene).catch((saveError: unknown) => {
        setError(saveError instanceof Error ? saveError.message : "Could not save the canvas.");
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [canvasReady, canvasScene]);

  const handleRun = async (scenario: StressScenarioRequest) => {
    setError("");
    setRunning(true);
    setSimulationSummary("");
    setSimulationReport(null);
    try {
      await saveCanvas(canvasScene);
      const result = await simulateStress(scenario);
      setStatusMap(result.output.element_statuses);
      setSimulationSummary(result.output.analysis);
      setSimulationReport(result.report);
      setDrawerOpen(false);
    } catch (runError) {
      const message = runError instanceof Error ? runError.message : "The simulation could not be completed.";
      setError(message);
      throw runError;
    } finally {
      setRunning(false);
    }
  };

  const handleDeployment = async () => {
    setError("");
    setDeploymentLoading(true);
    try {
      await saveCanvas(canvasScene);
      const generated = await generateDeployment();
      setBlueprint(generated);
      setDeploymentOpen(true);
    } catch (deploymentError) {
      setError(
        deploymentError instanceof Error
          ? deploymentError.message
          : "Could not generate the deployment files."
      );
    } finally {
      setDeploymentLoading(false);
    }
  };

  const handleImport = async (file?: File) => {
    if (!file) return;
    setError("");
    setImporting(true);
    setImportProgress("Reading file...");
    try {
      const extension = file.name.split(".").pop()?.toLowerCase();
      if (extension === "excalidraw" || extension === "json") {
        const parsed: unknown = JSON.parse(await file.text());
        if (!isRecord(parsed) || !Array.isArray(parsed.elements)) {
          throw new Error("Choose a valid Excalidraw export with an elements array.");
        }
        const elements = parsed.elements;
        if (
          !elements.every(
            (element) =>
              isRecord(element) &&
              typeof element.id === "string" &&
              typeof element.type === "string"
          )
        ) {
          throw new Error("The Excalidraw export contains an invalid element.");
        }
        const { restore } = await import("@excalidraw/excalidraw");
        const restored = restore(
          parsed as ImportedDataState,
          null,
          canvasScene.elements
        );
        const scene = normalizeCanvasScene({
          elements: restored.elements,
          appState: restored.appState,
          files: restored.files,
        });
        await saveCanvas(scene);
        initialCanvasScene.current = scene;
        setCanvasScene(scene);
        setStatusMap({});
        setSimulationSummary("");
        setCanvasRevision((revision) => revision + 1);
        return;
      }

      const { convertToExcalidrawElements } = await import("@excalidraw/excalidraw");
      const isImage = CONVERTIBLE_IMAGE_EXTENSIONS.has(extension ?? "");
      let baseScene = canvasScene;
      let replacedElements = 0;
      let importedElements: ExcalidrawElement[];
      if (isImage) {
        const conversionKey = `${file.name}:${file.size}:${file.lastModified}`;
        const cleaned = removeImportedImage(
          canvasScene,
          file.name,
          await readFileAsDataUrl(file),
          conversionKey,
          initialCanvasScene.current
        );
        baseScene = cleaned.scene;
        replacedElements = cleaned.removedElements;
        const diagramSkeleton = await convertImageToDiagram(file, setImportProgress);
        importedElements = convertToExcalidrawElements(diagramSkeleton).map((element) => ({
          ...element,
          customData: {
            ...element.customData,
            imageToDiagramSource: conversionKey,
          },
        }));
      } else {
        const text = await extractArchitectureFile(file, setImportProgress);
        const rightEdge = canvasScene.elements.reduce(
          (edge, element) => Math.max(edge, element.x + Math.max(element.width, 0)),
          100
        );
        importedElements = convertToExcalidrawElements([
          {
            type: "text",
            x: rightEdge + 80,
            y: 100,
            text: `${file.name}\n\n${text}`,
          },
        ]);
      }

      const scene = normalizeCanvasScene({
        ...baseScene,
        elements: [...baseScene.elements, ...importedElements],
      });
      await saveCanvas(scene);
      initialCanvasScene.current = scene;
      setCanvasScene(scene);
      setCanvasRevision((revision) => revision + 1);
      setImportProgress(
        isImage
          ? `${replacedElements > 0 ? `Replaced ${replacedElements} previous image elements. ` : ""}Converted ${file.name} into editable diagram elements. Review labels and connections for accuracy.`
          : `Extracted content from ${file.name} and added it to the canvas.`
      );
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : "Could not import that canvas file.");
    } finally {
      if (fileInput.current) fileInput.current.value = "";
      window.setTimeout(() => setImportProgress(""), 6000);
      setImporting(false);
    }
  };

  return (
    <Box className="platform-shell">
      <AppBar position="static" elevation={0} className="platform-appbar">
        <Toolbar className="platform-toolbar">
          <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", flexGrow: 1, minWidth: 0 }}>
            <Box className="brand-mark">
              <ArchitectureOutlinedIcon fontSize="small" />
            </Box>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }} noWrap>
                Stress Architecture
              </Typography>
              <Typography variant="caption" color="text.secondary" noWrap>
                Design · simulate · deploy
              </Typography>
            </Box>
          </Stack>

          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <input
              ref={fileInput}
              hidden
              type="file"
              accept=".excalidraw,.json,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.pdf,.doc,.docx,.md,.markdown,.txt,application/json,image/*,application/pdf"
              onChange={(event) => void handleImport(event.target.files?.[0])}
            />
            <Button
              className="toolbar-action"
              startIcon={<CloudUploadOutlinedIcon />}
              onClick={() => fileInput.current?.click()}
              disabled={importing}
            >
              {importing ? "Importing" : "Import"}
            </Button>
            <Button
              className="toolbar-action"
              startIcon={saving ? <CircularProgress size={16} /> : <SaveOutlinedIcon />}
              onClick={() => void persistCanvas().catch(() => undefined)}
              disabled={!canvasReady || saving}
            >
              {saving ? "Saving" : "Save"}
            </Button>
            <Button
              className="toolbar-action"
              startIcon={
                deploymentLoading ? <CircularProgress size={16} /> : <CodeOutlinedIcon />
              }
              onClick={() => void handleDeployment()}
              disabled={!canvasReady || deploymentLoading}
            >
              Deploy
            </Button>
            <Button
              variant="contained"
              startIcon={<PlayArrowRoundedIcon />}
              onClick={() => setDrawerOpen(true)}
              disabled={!canvasReady || running}
            >
              Simulate
            </Button>
          </Stack>
        </Toolbar>
      </AppBar>

      <Box component="main" className="platform-main">
        {error ? (
          <Alert severity="error" onClose={() => setError("")} className="platform-alert">
            {error}
          </Alert>
        ) : null}
        {importProgress ? (
          <Alert severity="info" onClose={() => setImportProgress("")} className="platform-alert">
            {importProgress}
          </Alert>
        ) : null}
        <Box className="canvas-heading">
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Architecture canvas
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              Map your services, connect dependencies, then run a deterministic stress scenario.
            </Typography>
          </Box>
          <Chip
            size="small"
            variant="outlined"
            label={canvasReady ? `${canvasScene.elements.length} elements` : "Loading canvas"}
          />
        </Box>

        <Box className="canvas-toolbar">
          <Stack
            direction="row"
            spacing={2}
            sx={{ alignItems: "center" }}
            divider={<Divider orientation="vertical" flexItem />}
          >
            {STATUS_LEGEND.map((item) => (
              <Stack key={item.label} direction="row" spacing={0.75} sx={{ alignItems: "center" }}>
                <Box className="status-dot" sx={{ backgroundColor: item.color }} />
                <Typography variant="caption" color="text.secondary">
                  {item.label}
                </Typography>
              </Stack>
            ))}
          </Stack>
          {running ? (
            <Chip
              size="small"
              icon={<CircularProgress size={12} />}
              label="Simulating"
              color="primary"
            />
          ) : simulationSummary || simulationReport ? (
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={1}
              sx={{ alignItems: { sm: "center" }, minWidth: 0 }}
            >
              <Typography variant="caption" color="text.secondary" className="simulation-summary">
                {simulationSummary || "Latest simulation report is ready."}
              </Typography>
              <Button
                size="small"
                variant="outlined"
                onClick={() => setReportOpen(true)}
                disabled={!simulationReport}
                sx={{ flexShrink: 0 }}
              >
                View report &amp; recommendations
              </Button>
            </Stack>
          ) : null}
        </Box>

        <Box className="canvas-frame">
          {canvasReady ? (
            <Canvas
              key={canvasRevision}
              statusMap={statusMap}
              initialData={initialCanvasScene.current}
              onLocalChange={handleCanvasChange}
            />
          ) : (
            <Stack spacing={2} sx={{ height: "100%", alignItems: "center", justifyContent: "center" }}>
              <CircularProgress size={28} />
              <Typography color="text.secondary">Loading your saved architecture…</Typography>
            </Stack>
          )}
        </Box>
      </Box>

      <ScenarioDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onRun={handleRun}
        running={running}
      />
      <BlueprintModal
        open={deploymentOpen}
        onClose={() => setDeploymentOpen(false)}
        blueprint={blueprint}
      />
      <SimulationReportDialog
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        report={simulationReport}
      />
    </Box>
  );
}
