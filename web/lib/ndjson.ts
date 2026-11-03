/* Reads a streamed run. The server ends each stream with exactly one final
   event and sends a heartbeat every 10 seconds, so a close with no final
   event, or a long silence, means the run was lost. */

export const FINAL_EVENT_TYPES = ["run_result", "private_result", "error"];
export const STREAM_IDLE_MS = 45_000;
export const LOST_STREAM_MESSAGE =
  "The connection closed before the check finished. Nothing was completed. Please try again.";

export class StreamIdleError extends Error {}

function isFinal(event: unknown): boolean {
  return (
    typeof event === "object" &&
    event !== null &&
    FINAL_EVENT_TYPES.includes(String((event as { type?: unknown }).type))
  );
}

/* Calls onEvent per JSON line and returns "final" once a final event has
   been handled, or "closed" if the stream ended without one. Rejects if
   the connection resets or stays silent for idleMs. */
export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: unknown) => void,
  idleMs: number = STREAM_IDLE_MS,
): Promise<"final" | "closed"> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // True when this line held the final event.
  const handle = (line: string): boolean => {
    if (!line.trim()) return false;
    let event: unknown;
    try {
      event = JSON.parse(line);
    } catch {
      return false;
    }
    onEvent(event);
    return isFinal(event);
  };

  const readWithIdleLimit = () => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const idle = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new StreamIdleError()), idleMs);
    });
    return Promise.race([reader.read(), idle]).finally(() =>
      clearTimeout(timer),
    );
  };

  try {
    for (;;) {
      const { done, value } = await readWithIdleLimit();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (handle(line)) return "final";
      }
    }
    return handle(buffer) ? "final" : "closed";
  } finally {
    reader.cancel().catch(() => undefined);
  }
}
