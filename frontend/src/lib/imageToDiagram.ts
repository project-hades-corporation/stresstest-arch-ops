import type { ExcalidrawElementSkeleton } from "@excalidraw/excalidraw/data/transform";

interface OCRLine {
  text: string;
  confidence: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface Region {
  x: number;
  y: number;
  width: number;
  height: number;
  hue: number;
}

interface DiagramNode {
  id: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  hue: number;
}

const COMPONENT_WORDS =
  /\b(application|database|redis|cache|gateway|service|server|queue|client|browser|worker|storage|api|frontend|backend)\b/i;
const RELATION_WORDS =
  /\b(read|write|hit|miss|request|response|send|receive|connect|fetch|query|publish|consume|replicate|flow|call)\b/i;
const CANVAS_ORIGIN_X = 40;
const CANVAS_ORIGIN_Y = 40;

export async function convertImageToDiagram(
  file: File,
  onProgress: (message: string) => void
): Promise<ExcalidrawElementSkeleton[]> {
  onProgress("Reading labels and diagram layout locally...");
  const image = await createImageBitmap(file);
  const canvasWidth = Math.min(700, image.width);
  const canvasHeight = Math.max(1, Math.round((image.height / image.width) * canvasWidth));
  const outputScale = canvasWidth / image.width;
  const canvas = document.createElement("canvas");
  canvas.width = canvasWidth;
  canvas.height = canvasHeight;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) {
    image.close();
    throw new Error("Could not prepare the image for diagram conversion.");
  }
  context.drawImage(image, 0, 0, canvasWidth, canvasHeight);
  const pixelData = context.getImageData(0, 0, canvasWidth, canvasHeight);
  image.close();

  const tesseract = await import("tesseract.js");
  const worker = await tesseract.createWorker("eng");
  let lines: OCRLine[];
  try {
    const result = await worker.recognize(file, {}, { blocks: true });
    lines = mergeComponentLabelLines(
      readOCRLines(result.data.blocks ?? [], outputScale)
        .filter((line) => !/\b(blog|algomaster)\b/i.test(line.text))
    );
  } finally {
    await worker.terminate();
  }
  if (lines.length === 0) {
    throw new Error("No readable labels were found. Try a sharper, higher-contrast diagram.");
  }

  onProgress("Rebuilding editable shapes and connectors...");
  const regions = findColorRegions(pixelData.data, canvasWidth, canvasHeight);
  const nodes = buildNodes(regions, lines, canvasWidth, canvasHeight);
  const nodeElements = nodes.map((node) => ({
    type: "rectangle" as const,
    id: node.id,
    x: node.x,
    y: node.y,
    width: node.width,
    height: node.height,
    roundness: { type: 3 as const },
    strokeColor: strokeForHue(node.hue),
    backgroundColor: fillForHue(node.hue),
    fillStyle: "solid" as const,
    label: {
      text: node.label,
      fontSize: 20,
      strokeColor: "#f8fafc",
    },
  }));
  const relationLines = lines.filter(
    (line) => RELATION_WORDS.test(line.text) && line.confidence >= 20
  );
  const arrows = relationLines
    .map((line, index) => buildArrow(line, nodes, index))
    .filter((arrow): arrow is NonNullable<typeof arrow> => arrow !== null)
    .flatMap(({ arrow, label }) => [arrow, label]);
  return [...nodeElements, ...arrows];
}

function readOCRLines(
  blocks: Array<{
    paragraphs: Array<{
      lines: Array<{
        text: string;
        confidence: number;
        bbox: { x0: number; y0: number; x1: number; y1: number };
        words?: Array<{
          text: string;
          confidence: number;
          bbox: { x0: number; y0: number; x1: number; y1: number };
        }>;
      }>;
    }>;
  }>,
  scale: number
): OCRLine[] {
  return blocks.flatMap((block) =>
    block.paragraphs.flatMap((paragraph) =>
      paragraph.lines.flatMap((line) => {
        const words = line.words?.filter((word) => word.text.trim() && word.confidence >= 15) ?? [];
        if (words.length === 0) {
          const text = line.text.trim();
          if (text.length < 2 || line.confidence < 15) return [];
          return [toOCRLine(text, line.confidence, line.bbox, scale)];
        }

        const orderedWords = [...words].sort((left, right) => left.bbox.x0 - right.bbox.x0);
        const groups: typeof orderedWords[] = [];
        for (const word of orderedWords) {
          const group = groups[groups.length - 1];
          const previous = group?.[group.length - 1];
          const gap = previous ? word.bbox.x0 - previous.bbox.x1 : 0;
          const lineHeight = previous
            ? Math.max(
                previous.bbox.y1 - previous.bbox.y0,
                word.bbox.y1 - word.bbox.y0
              )
            : 0;
          if (!group || gap > Math.max(28, lineHeight * 2)) groups.push([word]);
          else group.push(word);
        }
        return groups.flatMap((group) => {
          const text = group.map((word) => word.text).join(" ").trim();
          if (text.length < 2) return [];
          const bbox = {
            x0: Math.min(...group.map((word) => word.bbox.x0)),
            y0: Math.min(...group.map((word) => word.bbox.y0)),
            x1: Math.max(...group.map((word) => word.bbox.x1)),
            y1: Math.max(...group.map((word) => word.bbox.y1)),
          };
          const confidence =
            group.reduce((sum, word) => sum + word.confidence, 0) / group.length;
          return [toOCRLine(text, confidence, bbox, scale)];
        });
      })
    )
  );
}

function toOCRLine(
  text: string,
  confidence: number,
  bbox: { x0: number; y0: number; x1: number; y1: number },
  scale: number
): OCRLine {
  return {
    text,
    confidence,
    x: bbox.x0 * scale,
    y: bbox.y0 * scale,
    width: (bbox.x1 - bbox.x0) * scale,
    height: (bbox.y1 - bbox.y0) * scale,
  };
}

function mergeComponentLabelLines(lines: OCRLine[]): OCRLine[] {
  const result: OCRLine[] = [];
  for (const line of [...lines].sort((left, right) => left.y - right.y || left.x - right.x)) {
    const category = componentCategory(line.text);
    const target = category && !RELATION_WORDS.test(line.text)
      ? [...result].reverse().find((candidate) => {
          if (componentCategory(candidate.text) !== category || RELATION_WORDS.test(candidate.text)) {
            return false;
          }
          const verticalGap = line.y - (candidate.y + candidate.height);
          const horizontalDistance = Math.abs(
            candidate.x + candidate.width / 2 - (line.x + line.width / 2)
          );
          return (
            verticalGap < Math.max(candidate.height, line.height, 18) * 2 &&
            horizontalDistance < Math.max(candidate.width, line.width, 48)
          );
        })
      : undefined;
    if (target) {
      const right = Math.max(target.x + target.width, line.x + line.width);
      const bottom = Math.max(target.y + target.height, line.y + line.height);
      target.text = `${target.text} ${line.text}`;
      target.x = Math.min(target.x, line.x);
      target.y = Math.min(target.y, line.y);
      target.width = right - target.x;
      target.height = bottom - target.y;
      target.confidence = Math.min(target.confidence, line.confidence);
    } else {
      result.push({ ...line });
    }
  }
  return result;
}

function componentCategory(text: string): string | undefined {
  if (/\b(application|app|client|browser)\b/i.test(text)) return "application";
  if (/\b(cache|redis)\b/i.test(text)) return "cache";
  if (/\b(database|db|postgres|mysql|sql)\b/i.test(text)) return "database";
  if (/\b(gateway|api)\b/i.test(text)) return "gateway";
  if (/\b(queue|worker|storage|service|server|frontend|backend)\b/i.test(text)) return "service";
  return undefined;
}

function findColorRegions(data: Uint8ClampedArray, width: number, height: number): Region[] {
  const mask = new Uint8Array(width * height);
  for (let index = 0; index < mask.length; index += 1) {
    const pixel = index * 4;
    const red = data[pixel];
    const green = data[pixel + 1];
    const blue = data[pixel + 2];
    const chroma = Math.max(red, green, blue) - Math.min(red, green, blue);
    if (chroma > 45 && Math.max(red, green, blue) > 90) mask[index] = 1;
  }

  const expanded = mask.slice();
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const index = y * width + x;
      if (!mask[index]) continue;
      expanded[index - 1] = 1;
      expanded[index + 1] = 1;
      expanded[index - width] = 1;
      expanded[index + width] = 1;
    }
  }

  const visited = new Uint8Array(width * height);
  const regions: Region[] = [];
  const minimumArea = Math.max(160, width * height * 0.0007);
  for (let start = 0; start < expanded.length; start += 1) {
    if (!expanded[start] || visited[start]) continue;
    const queue = [start];
    visited[start] = 1;
    let minX = width;
    let minY = height;
    let maxX = 0;
    let maxY = 0;
    let area = 0;
    let hueSum = 0;
    for (let cursor = 0; cursor < queue.length; cursor += 1) {
      const index = queue[cursor];
      const x = index % width;
      const y = Math.floor(index / width);
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      const pixel = index * 4;
      hueSum += hueOf(data[pixel], data[pixel + 1], data[pixel + 2]);
      area += 1;
      const neighbors = [
        x > 0 ? index - 1 : -1,
        x < width - 1 ? index + 1 : -1,
        y > 0 ? index - width : -1,
        y < height - 1 ? index + width : -1,
      ];
      for (const neighbor of neighbors) {
        if (neighbor < 0) continue;
        if (!visited[neighbor] && expanded[neighbor]) {
          visited[neighbor] = 1;
          queue.push(neighbor);
        }
      }
    }
    if (area < minimumArea) continue;
    const regionWidth = maxX - minX + 1;
    const regionHeight = maxY - minY + 1;
    if (regionWidth < 24 || regionHeight < 24) continue;
    regions.push({
      x: minX,
      y: minY,
      width: regionWidth,
      height: regionHeight,
      hue: hueSum / area,
    });
  }
  return regions.sort((left, right) => right.width * right.height - left.width * left.height);
}

function buildNodes(
  regions: Region[],
  lines: OCRLine[],
  width: number,
  height: number
): DiagramNode[] {
  const scale = 1;
  const candidates = lines
    .filter((line) => COMPONENT_WORDS.test(line.text) && !RELATION_WORDS.test(line.text))
    .sort((left, right) => right.confidence - left.confidence);
  const usedLabels = new Set<OCRLine>();
  const nodes = regions.slice(0, 16).map((region, index) => {
    const centerX = region.x + region.width / 2;
    const centerY = region.y + region.height / 2;
    const nearest = candidates
      .filter((line) => !usedLabels.has(line))
      .map((line) => ({
        line,
        distance: Math.hypot(
          centerX - (line.x + line.width / 2) * scale,
          centerY - (line.y + line.height / 2) * scale
        ),
      }))
      .sort((left, right) => left.distance - right.distance)[0];
    const maxDistance = Math.hypot(width, height) * 0.38;
    const sourceText = nearest && nearest.distance <= maxDistance ? nearest.line : null;
    if (sourceText) usedLabels.add(sourceText);
    return {
      id: `image_node_${index + 1}`,
      label: sourceText?.text ?? `Component ${index + 1}`,
      x: CANVAS_ORIGIN_X + region.x / scale,
      y: CANVAS_ORIGIN_Y + region.y / scale,
      width: Math.max(100, region.width / scale),
      height: Math.max(70, region.height / scale),
      hue: region.hue,
    };
  });

  for (const line of candidates) {
    if (usedLabels.has(line)) continue;
    const x = (line.x + line.width / 2) * scale;
    const y = (line.y + line.height / 2) * scale;
    nodes.push({
      id: `image_node_${nodes.length + 1}`,
      label: line.text,
      x: CANVAS_ORIGIN_X + Math.max(0, x - 90),
      y: CANVAS_ORIGIN_Y + Math.max(0, y - 45),
      width: 180,
      height: 90,
      hue: 220,
    });
    usedLabels.add(line);
  }

  if (nodes.length < 2) {
    throw new Error(
      "I found text, but not enough diagram components to reconstruct editable shapes. Try a clearer image."
    );
  }
  return nodes;
}

function buildArrow(
  line: OCRLine,
  nodes: DiagramNode[],
  index: number
): { arrow: ExcalidrawElementSkeleton; label: ExcalidrawElementSkeleton } | null {
  const text = line.text.toLowerCase();
  const sourceHint = text.match(/\bfrom\s+([\w-]+)/)?.[1];
  const targetHint = text.match(/\bto\s+([\w-]+)/)?.[1];
  const hintedSource = sourceHint && nodes.find((node) => node.label.toLowerCase().includes(sourceHint));
  const hintedTarget = targetHint && nodes.find((node) => node.label.toLowerCase().includes(targetHint));
  let source = hintedSource;
  let target = hintedTarget;
  const app = nodes.find((node) => /\b(application|app|client|browser)\b/i.test(node.label));
  const cache = nodes.find((node) => /\b(cache|redis)\b/i.test(node.label));
  const database = nodes.find((node) => /\b(database|db|postgres|mysql|sql)\b/i.test(node.label));

  if (!source || !target) {
    if (/\b(read|fetch|query|consume)\b/.test(text) && /\b(from|cache|database|db)\b/.test(text)) {
      source = sourceHint?.match(/db|database|sql|postgres|mysql/)
        ? database
        : sourceHint?.match(/cache|redis/)
          ? cache
          : /\bfrom\s+(?:the\s+)?(?:db|database)\b/.test(text)
            ? database
            : cache ?? database;
      target = app ?? nodes.find((node) => node !== source);
    } else if (/\b(write|send|publish|store)\b/.test(text) && /\b(to|cache|database|db)\b/.test(text)) {
      source = app ?? nodes[0];
      target = targetHint?.match(/db|database|sql|postgres|mysql/)
        ? database
        : targetHint?.match(/cache|redis/)
          ? cache
          : /\bto\s+(?:the\s+)?(?:db|database)\b/.test(text)
            ? database
            : cache ?? database;
    }
  }

  if (!source || !target || source === target) {
    const lineX = line.x + line.width / 2;
    const lineY = line.y + line.height / 2;
    const closest = nodes
      .map((node) => ({
        node,
        distance: Math.hypot(
          node.x + node.width / 2 - (CANVAS_ORIGIN_X + lineX),
          node.y + node.height / 2 - (CANVAS_ORIGIN_Y + lineY)
        ),
      }))
      .sort((left, right) => left.distance - right.distance);
    source = closest[0]?.node;
    target = closest.find((entry) => entry.node !== source)?.node;
  }
  if (!source || !target) return null;

  const sourceX = source.x + source.width / 2;
  const sourceY = source.y + source.height / 2;
  const targetX = target.x + target.width / 2;
  const targetY = target.y + target.height / 2;
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const sourceOffset = Math.min(
    Math.abs(dx) > 0 ? source.width / (2 * Math.abs(dx)) : Infinity,
    Math.abs(dy) > 0 ? source.height / (2 * Math.abs(dy)) : Infinity,
    0.42
  );
  const targetOffset = Math.min(
    Math.abs(dx) > 0 ? target.width / (2 * Math.abs(dx)) : Infinity,
    Math.abs(dy) > 0 ? target.height / (2 * Math.abs(dy)) : Infinity,
    0.42
  );
  const startX = sourceX + dx * sourceOffset;
  const startY = sourceY + dy * sourceOffset;
  const endX = targetX - dx * targetOffset;
  const endY = targetY - dy * targetOffset;
  const originX = Math.min(startX, endX);
  const originY = Math.min(startY, endY);
  return {
    arrow: {
      type: "arrow",
      id: `image_arrow_${index + 1}`,
      x: originX,
      y: originY,
      width: Math.max(1, Math.abs(endX - startX)),
      height: Math.max(1, Math.abs(endY - startY)),
      points: [
        [startX - originX, startY - originY],
        [endX - originX, endY - originY],
      ],
      endArrowhead: "arrow",
      strokeColor: "#fbbf24",
      strokeWidth: 4,
    },
    label: {
      type: "text",
      x: CANVAS_ORIGIN_X + (startX + endX) / 2 - 70,
      y: CANVAS_ORIGIN_Y + (startY + endY) / 2 - 12,
      text: line.text,
      fontSize: 18,
      strokeColor: "#fbbf24",
    },
  };
}

function hueOf(red: number, green: number, blue: number): number {
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const delta = max - min;
  if (delta === 0) return 0;
  if (max === red) return ((green - blue) / delta + (green < blue ? 6 : 0)) * 60;
  if (max === green) return ((blue - red) / delta + 2) * 60;
  return ((red - green) / delta + 4) * 60;
}

function strokeForHue(hue: number): string {
  if (hue < 25 || hue >= 345) return "#ef4444";
  if (hue < 80) return "#eab308";
  if (hue < 165) return "#22c55e";
  if (hue < 255) return "#3b82f6";
  return "#a78bfa";
}

function fillForHue(hue: number): string {
  if (hue < 25 || hue >= 345) return "#451a1a";
  if (hue < 80) return "#422006";
  if (hue < 165) return "#064e3b";
  if (hue < 255) return "#172554";
  return "#2e1065";
}
