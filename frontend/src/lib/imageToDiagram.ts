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
  /\b(application|app|database|db|redis|cache|gateway|service|server|queue|client|browser|worker|storage|api|frontend|backend|waf|alb|elb|nlb|eks|ecs|ecr|lambda|s3|rds|sqs|sns|vpc|cdn|cloudfront|nginx|kubernetes|k8s|docker|container|pod|cluster|pipeline|github|gitlab|jenkins|ci|terraform|prometheus|grafana|kafka|rabbitmq|postgres|mysql|mongo|elastic|elasticsearch|kibana|vault|consul|istio|envoy|traefik|haproxy|memcached|dynamo|dynamodb|firestore|bigquery|pubsub|gke|gcs|azure|aws|gcp|load.?balancer|ingress|egress|proxy|broker|registry|repository|repo|bucket|blob|function|microservice|monolith|edge|router|switch|firewall|dns|cdn|akamai|fastly|vercel|netlify)\b/i;
const RELATION_WORDS =
  /\b(read|write|hit|miss|request|response|send|receive|connect|fetch|query|publish|consume|replicate|flow|call|push|pull|upload|download|deploy|trigger|build|checkout|rollout|invoke|notify|sync|poll|emit|subscribe|forward|route|redirect|register|update|delete)\b|\b\d+[.)]\s*\w/i;
// Reject OCR lines that are obviously noise: only allow letters, digits,
// spaces, hyphens, dots, slashes, and apostrophes, and require at least two
// consecutive letters so single-char tokens and symbol sequences are dropped.
const CLEAN_TEXT = /^[\w\s'\-./]+$/;
const HAS_LETTERS = /[a-zA-Z]{2,}/;

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
    label: {
      text: node.label,
      fontSize: 14,
      verticalAlign: "middle" as const,
    },
  }));
  const relationLines = lines.filter(
    (line) => RELATION_WORDS.test(line.text) && line.confidence >= 20
  );
  const arrows = relationLines
    .map((line, index) => buildArrow(line, nodes, index))
    .filter((arrow): arrow is NonNullable<typeof arrow> => arrow !== null);
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

const NODE_W = 160;
const NODE_H = 80;
const NODE_PAD = 28;

function buildNodes(
  regions: Region[],
  lines: OCRLine[],
  width: number,
  height: number
): DiagramNode[] {
  // Primary strategy: one node per distinct text label, positioned at the
  // label's location in the image. This avoids the overlap caused by using
  // region bounding boxes, which are large containers in complex diagrams.
  const componentLines = lines.filter(
    (line) =>
      !RELATION_WORDS.test(line.text) &&
      line.confidence >= 30 &&
      line.text.length >= 3 &&
      CLEAN_TEXT.test(line.text) &&
      HAS_LETTERS.test(line.text)
  );

  const nodes: DiagramNode[] = componentLines.map((line, index) => {
    const cx = line.x + line.width / 2;
    const cy = line.y + line.height / 2;
    return {
      id: `image_node_${index + 1}`,
      label: line.text,
      x: CANVAS_ORIGIN_X + Math.max(0, cx - NODE_W / 2),
      y: CANVAS_ORIGIN_Y + Math.max(0, cy - NODE_H / 2),
      width: NODE_W,
      height: NODE_H,
      hue: 220,
    };
  });

  // Secondary: add nodes for any colour region that has no nearby text label,
  // so purely graphical components are not silently dropped.
  const usedRegions = new Set<number>();
  for (const [ri, region] of dedupedRegions(regions).entries()) {
    const cx = region.x + region.width / 2;
    const cy = region.y + region.height / 2;
    const hasNearbyLabel = componentLines.some((line) => {
      const lx = line.x + line.width / 2;
      const ly = line.y + line.height / 2;
      return (
        lx >= region.x - 4 &&
        lx <= region.x + region.width + 4 &&
        ly >= region.y - 4 &&
        ly <= region.y + region.height + Math.max(region.height * 0.6, 20)
      );
    });
    if (!hasNearbyLabel && !usedRegions.has(ri)) {
      usedRegions.add(ri);
      nodes.push({
        id: `image_node_${nodes.length + 1}`,
        label: `Component ${nodes.length + 1}`,
        x: CANVAS_ORIGIN_X + Math.max(0, cx - NODE_W / 2),
        y: CANVAS_ORIGIN_Y + Math.max(0, cy - NODE_H / 2),
        width: NODE_W,
        height: NODE_H,
        hue: region.hue,
      });
    }
  }

  if (nodes.length < 2) {
    throw new Error(
      "I found text, but not enough diagram components to reconstruct editable shapes. Try a clearer image."
    );
  }
  return deOverlapNodes(nodes);
}

function dedupedRegions(regions: Region[]): Region[] {
  // Skip any region that contains 2 or more smaller already-accepted regions —
  // those are container frames, not component nodes.
  const bySize = [...regions].sort((a, b) => a.width * a.height - b.width * b.height);
  const accepted: Region[] = [];
  for (const region of bySize) {
    const containedCount = accepted.filter((existing) => {
      const ox = Math.max(0,
        Math.min(region.x + region.width, existing.x + existing.width) - Math.max(region.x, existing.x));
      const oy = Math.max(0,
        Math.min(region.y + region.height, existing.y + existing.height) - Math.max(region.y, existing.y));
      return (ox * oy) / (existing.width * existing.height) > 0.55;
    }).length;
    if (containedCount < 2) accepted.push(region);
  }
  return accepted;
}

function deOverlapNodes(nodes: DiagramNode[]): DiagramNode[] {
  const result = nodes.map((n) => ({ ...n }));
  for (let iter = 0; iter < 80; iter++) {
    let moved = false;
    for (let i = 0; i < result.length; i++) {
      for (let j = i + 1; j < result.length; j++) {
        const a = result[i];
        const b = result[j];
        const ox = Math.min(a.x + a.width + NODE_PAD, b.x + b.width + NODE_PAD) - Math.max(a.x, b.x);
        const oy = Math.min(a.y + a.height + NODE_PAD, b.y + b.height + NODE_PAD) - Math.max(a.y, b.y);
        if (ox > 0 && oy > 0) {
          const half = (ox < oy ? ox : oy) / 2 + 1;
          if (ox < oy) {
            const dir = a.x + a.width / 2 <= b.x + b.width / 2 ? -1 : 1;
            result[i].x += dir * half;
            result[j].x -= dir * half;
          } else {
            const dir = a.y + a.height / 2 <= b.y + b.height / 2 ? -1 : 1;
            result[i].y += dir * half;
            result[j].y -= dir * half;
          }
          moved = true;
        }
      }
    }
    if (!moved) break;
  }
  return result;
}

function buildArrow(
  line: OCRLine,
  nodes: DiagramNode[],
  index: number
): ExcalidrawElementSkeleton | null {
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

  return {
    type: "arrow",
    id: `image_arrow_${index + 1}`,
    x: (source.x + source.width / 2 + target.x + target.width / 2) / 2,
    y: (source.y + source.height / 2 + target.y + target.height / 2) / 2,
    start: { id: source.id },
    end: { id: target.id },
    endArrowhead: "arrow",
    label: { text: line.text, fontSize: 14 },
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

