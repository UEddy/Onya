import assert from "node:assert/strict";
import test from "node:test";
import { readEventStream, StreamIdleError } from "./ndjson.ts";

const encode = (text: string) => new TextEncoder().encode(text);

function streamOf(chunks: string[], end: "close" | "reset" | "hang" = "close") {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encode(chunk));
      if (end === "close") controller.close();
      if (end === "reset") controller.error(new TypeError("network error"));
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>, idleMs?: number) {
  const events: unknown[] = [];
  const end = await readEventStream(stream, (e) => events.push(e), idleMs);
  return { events, end };
}

test("a final event ends the read", async () => {
  const { events, end } = await collect(
    streamOf([
      '{"type":"heartbeat"}\n{"type":"run_result","reason":"done"}\n',
      '{"type":"error"}\n',
    ]),
  );
  assert.equal(end, "final");
  assert.equal(events.length, 2);
});

test("a close with no final event is reported as closed", async () => {
  const { events, end } = await collect(
    streamOf(['{"tool":"lookup_company"}\n', '{"type":"heartbeat"}\n']),
  );
  assert.equal(end, "closed");
  assert.equal(events.length, 2);
});

test("an empty stream is reported as closed", async () => {
  assert.equal((await collect(streamOf([]))).end, "closed");
});

test("a line split across chunks is read whole", async () => {
  const { events, end } = await collect(
    streamOf(['{"type":"priv', 'ate_result","comparison":{}}\n']),
  );
  assert.equal(end, "final");
  assert.equal(events.length, 1);
});

test("a final event with no newline still counts", async () => {
  assert.equal((await collect(streamOf(['{"type":"error"}']))).end, "final");
});

test("a torn last line is not a final event", async () => {
  assert.equal(
    (await collect(streamOf(['{"tool":"x"}\n{"type":"run_res']))).end,
    "closed",
  );
});

test("a connection reset rejects", async () => {
  await assert.rejects(
    collect(streamOf(['{"tool":"x"}\n'], "reset")),
    TypeError,
  );
});

test("silence past the idle limit rejects", async () => {
  await assert.rejects(
    collect(streamOf(['{"type":"heartbeat"}\n'], "hang"), 20),
    StreamIdleError,
  );
});
