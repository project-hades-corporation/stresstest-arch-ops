"use client";

import { useEffect } from "react";
import type { ThoughtEvent } from "../types";

type ThoughtHandler = (event: ThoughtEvent) => void;

let socket: WebSocket | null = null;
let url: string | null = null;
let handler: ThoughtHandler | null = null;
let connectPromise: Promise<void> | null = null;

function start(nextUrl: string, nextHandler: ThoughtHandler): Promise<void> {
  const existing = socket;
  const canReuse =
    existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING);
  if (canReuse && existing) {
    url = nextUrl;
    handler = nextHandler;
    if (existing.readyState === WebSocket.OPEN) {
      void nextHandler;
      return Promise.resolve();
    }
    return connectPromise ?? Promise.resolve();
  }
  if (existing) existing.close();
  const ws = new WebSocket(nextUrl);
  socket = ws;
  url = nextUrl;
  handler = nextHandler;
  const ready = new Promise<void>((resolve, reject) => {
    ws.onopen = () => resolve();
    ws.onerror = () => reject(new Error("WebSocket connect failed"));
  });
  ws.onmessage = (ev) => {
    try {
      const event: ThoughtEvent = JSON.parse(String(ev.data));
      handler?.(event);
    } catch {
      // ignore malformed frames
    }
  };
  ws.onclose = () => {
    if (socket === ws) {
      socket = null;
      connectPromise = null;
      handler = null;
      url = null;
    }
  };
  connectPromise = ready.then(
    () => undefined,
    () => {
      if (socket === ws) {
        socket = null;
        connectPromise = null;
        handler = null;
        url = null;
      }
      throw new Error("WebSocket connect failed");
    }
  );
  return connectPromise;
}

function stop(): void {
  if (socket) socket.close();
  socket = null;
  connectPromise = null;
  handler = null;
  url = null;
}

/** Subscribe to backend agent-thought events on the stress WebSocket. */
export function useThoughtStream(url: string, onThought: (event: ThoughtEvent) => void): void {
  useEffect(() => {
    void start(url, onThought);
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);
}
