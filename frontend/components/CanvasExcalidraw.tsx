"use client";

import { memo, useCallback, useEffect, useRef } from "react";
import { Excalidraw } from "@excalidraw/excalidraw";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import type { AppState, BinaryFiles, ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { CanvasSceneData, StatusMap } from "../src/types";

interface CanvasProps {
  statusMap: StatusMap;
  initialData: CanvasSceneData;
  onLocalChange?: (
    elements: readonly ExcalidrawElement[],
    appState: AppState,
    files: BinaryFiles
  ) => void;
}

const STATUS_COLORS = {
  CRITICAL: { stroke: "#ef4444", background: "#4b1d27" },
  WARNING: { stroke: "#f59e0b", background: "#4b351b" },
  OK: { stroke: "#22c55e", background: "#163b2b" },
};

const Canvas = memo(function Canvas({ statusMap, initialData, onLocalChange }: CanvasProps) {
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null);
  const elementsRef = useRef<readonly ExcalidrawElement[]>([]);
  const handleApi = useCallback((api: ExcalidrawImperativeAPI) => {
    apiRef.current = api;
  }, []);

  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    const elements = elementsRef.current.map((element) => {
      const colors = statusMap[element.id] ? STATUS_COLORS[statusMap[element.id]] : undefined;
      if (!colors || !("strokeColor" in element)) return element;
      return {
        ...element,
        strokeColor: colors.stroke,
        backgroundColor: colors.background,
        fillStyle: "solid" as const,
      };
    });
    api.updateScene({ elements });
  }, [statusMap]);

  return (
    <div style={{ position: "relative", height: "100%", width: "100%" }}>
      <Excalidraw
        theme="dark"
        initialData={initialData}
        excalidrawAPI={handleApi}
        onChange={(elements, appState, files) => {
          elementsRef.current = elements;
          onLocalChange?.(elements, appState, files);
        }}
      />
    </div>
  );
});

export default Canvas;
