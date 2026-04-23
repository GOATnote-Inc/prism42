// SSE helpers. Two consumers:
// 1. /api/chat/completions — emits OpenAI chat.completion.chunk events
//    for ElevenLabs custom-LLM ingestion.
// 2. /api/session/:id/stream — emits structured PsapTurn / RubricGrade /
//    PsapAlert events for the dispatcher UI.
//
// Both use the native Web Streams API so they run cleanly on Vercel
// Node and (future) Edge runtimes.

import type { OpenAIChunk, SessionEvent } from "./types";

const ENC = new TextEncoder();

export interface SSEWriter {
  writeJson: (data: unknown) => void;
  writeEvent: (kind: string, data: unknown) => void;
  writeComment: (text: string) => void;
  writeDone: () => void;
  close: () => void;
  // Readable side to hand back to the framework.
  readable: ReadableStream<Uint8Array>;
  // Promise that resolves when the writer is closed (by any side).
  closed: Promise<void>;
}

export function createSseWriter(): SSEWriter {
  const { readable, writable } = new TransformStream<Uint8Array, Uint8Array>();
  const writer = writable.getWriter();
  let isClosed = false;
  let resolveClosed!: () => void;
  const closed = new Promise<void>((resolve) => {
    resolveClosed = resolve;
  });

  const write = (bytes: Uint8Array) => {
    if (isClosed) return;
    writer.write(bytes).catch(() => {
      isClosed = true;
      resolveClosed();
    });
  };

  const close = () => {
    if (isClosed) return;
    isClosed = true;
    writer.close().catch(() => {});
    resolveClosed();
  };

  return {
    writeJson(data) {
      write(ENC.encode(`data: ${JSON.stringify(data)}\n\n`));
    },
    writeEvent(kind, data) {
      write(
        ENC.encode(`event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`),
      );
    },
    writeComment(text) {
      // SSE comments keep proxies from timing out; ignored by clients.
      write(ENC.encode(`: ${text}\n\n`));
    },
    writeDone() {
      write(ENC.encode(`data: [DONE]\n\n`));
    },
    close,
    readable,
    closed,
  };
}

export function sseHeaders(): HeadersInit {
  return {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-store, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  };
}

export function makeOpenAIChunk(args: {
  id: string;
  model: string;
  content?: string;
  finishReason?: "stop" | "length" | "tool_calls" | null;
}): OpenAIChunk {
  return {
    id: args.id,
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model: args.model,
    choices: [
      {
        index: 0,
        delta: args.content ? { content: args.content } : {},
        finish_reason: args.finishReason ?? null,
      },
    ],
  };
}

// For structured session streams — wraps a SessionEvent as an SSE frame.
export function writeSessionEvent(
  sse: SSEWriter,
  event: SessionEvent,
): void {
  sse.writeEvent(event.kind, event);
}
