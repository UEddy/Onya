import { expect, test, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import {
  createServer,
  type IncomingMessage,
  type Server,
  type ServerResponse,
} from "node:http";
import type { AddressInfo } from "node:net";

/* The browser only talks to the Next.js server, so a sleeping backend is
   simulated at the server level: the web servers below run with
   ONYA_API_BASE pointing at a closed port (unreachable) or at a stub
   that answers 503 like a cold Baseten gateway. */

test.describe.configure({ mode: "serial" });

const REAL_BACKEND = "http://localhost:8001";

let stubMode: "cold" | "proxy" = "cold";
let stub: Server | undefined;
let stubUrl = "";
let outageOrigin = "";
let flakyOrigin = "";
const webServers: ChildProcess[] = [];

async function closedPort(): Promise<number> {
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const address = probe.address();
  const port = (address as AddressInfo).port;
  await new Promise<void>((resolve, reject) =>
    probe.close((error) => (error ? reject(error) : resolve())),
  );
  return port;
}

function startStub(): Promise<string> {
  stub = createServer(
    (req: IncomingMessage, res: ServerResponse) => {
      if (stubMode === "cold") {
        res.writeHead(503, {
          "Content-Type": "application/json",
          "Cache-Control": "no-store",
        });
        res.end(JSON.stringify({ detail: "service is warming up" }));
        return;
      }
      // Recovery mode: forward to the real backend from the shared config.
      void (async () => {
        try {
          const upstream = await fetch(`${REAL_BACKEND}${req.url ?? ""}`, {
            headers: { Authorization: "Bearer dummy-baseten-key" },
          });
          const body = Buffer.from(await upstream.arrayBuffer());
          res.writeHead(upstream.status, {
            "Content-Type":
              upstream.headers.get("Content-Type") ?? "application/json",
            "Cache-Control": "no-store",
          });
          res.end(body);
        } catch {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ detail: "stub proxy failed" }));
        }
      })();
    },
  );
  return new Promise<string>((resolve) => {
    if (!stub) throw new Error("stub server was not created");
    const server: Server = stub;
    server.listen(0, "127.0.0.1", () => {
      const port = (server.address() as AddressInfo).port;
      resolve(`http://127.0.0.1:${port}`);
    });
  });
}

async function startWeb(apiBase: string): Promise<string> {
  const port = await closedPort();
  const child = spawn("npm", ["run", "start", "--", "-p", String(port)], {
    env: {
      ...process.env,
      ONYA_API_BASE: apiBase,
      ONYA_DEMO_TOKEN: "dummy-demo-token",
    },
    stdio: "ignore",
  });
  webServers.push(child);
  const origin = `http://localhost:${port}`;
  const deadline = Date.now() + 90_000;
  for (let i = 0; i < 180; i += 1) {
    try {
      const res = await fetch(origin, {
        signal: AbortSignal.timeout(2000),
      });
      await res.text().catch(() => undefined);
      if (res.status < 500) return origin;
    } catch {
      /* Not up yet; keep waiting. */
    }
    if (Date.now() > deadline) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`web server on ${port} never came up`);
}

test.beforeAll(async () => {
  stubUrl = await startStub();
  outageOrigin = await startWeb(`http://127.0.0.1:${await closedPort()}`);
  flakyOrigin = await startWeb(stubUrl);
});

test.afterAll(async () => {
  for (const child of webServers) child.kill();
  await new Promise<void>((resolve) => {
    if (stub) stub.close(() => resolve());
    else resolve();
  });
});

async function expectWakingNotice(
  page: Page,
  origin: string,
  path: string,
): Promise<void> {
  await page.goto(`${origin}${path}`);
  await expect(
    page.getByText("The data service is waking up."),
  ).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByText("This can take up to a minute."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Try again" }),
  ).toBeVisible();
}

test("an unreachable backend shows the waking notice with a retry", async ({
  page,
}) => {
  await expectWakingNotice(page, outageOrigin, "/");
  await expectWakingNotice(page, outageOrigin, "/app/watchlist");
  await expectWakingNotice(page, outageOrigin, "/app/company/SNBR");
});

test("the agent page shows the waking notice when the backend is down", async ({
  page,
}) => {
  await page.goto(`${outageOrigin}/app/agent`);
  await page.getByRole("button", { name: "Run the check" }).click();
  await expect(
    page.getByText("The data service is waking up."),
  ).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByText("This can take up to a minute."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Try again" }),
  ).toBeVisible();
});

test("a backend returning 503 shows the waking notice", async ({
  page,
}) => {
  stubMode = "cold";
  await expectWakingNotice(page, flakyOrigin, "/");
  await expectWakingNotice(page, flakyOrigin, "/app/watchlist");
});

test("Try again recovers once the backend is reachable", async ({
  page,
}) => {
  stubMode = "cold";
  await page.goto(`${flakyOrigin}/app/watchlist`);
  await expect(
    page.getByText("The data service is waking up."),
  ).toBeVisible({ timeout: 30_000 });
  stubMode = "proxy";
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByText("Demo portfolio", { exact: true }),
  ).toBeVisible({ timeout: 60_000 });
});
