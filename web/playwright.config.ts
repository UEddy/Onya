import { readFileSync } from "node:fs";
import { defineConfig } from "@playwright/test";

process.env.NO_PROXY = "localhost,127.0.0.1";
process.env.no_proxy = "localhost,127.0.0.1";

function localEnv(name: string): string | undefined {
  try {
    const text = readFileSync(".env.local", "utf8");
    for (const line of text.split("\n")) {
      const match = new RegExp(`^${name}=(.*)$`).exec(line.trim());
      if (match) return match[1];
    }
  } catch {
    // No local env file; the API server falls back to its own defaults.
  }
  return undefined;
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  use: {
    baseURL: "http://localhost:3001",
    viewport: { width: 1366, height: 900 },
  },
  webServer: [
    {
      command:
        "cd .. && ONYA_AGENT_REPLAY=1 .venv/bin/python -m uvicorn api:app --app-dir src --port 8001",
      url: "http://localhost:8001/health",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ONYA_AGENT_REPLAY: "1",
        ONYA_FRONTEND_ORIGIN: "http://localhost:3001",
        ONYA_DEMO_TOKEN: localEnv("ONYA_DEMO_TOKEN") ?? "",
      },
    },
    {
      command:
        "NEXT_PUBLIC_API_BASE=http://localhost:8001 ONYA_API_BASE=http://localhost:8001 npm run build && npm run start -- -p 3001",
      url: "http://localhost:3001",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_BASE: "http://localhost:8001",
        ONYA_API_BASE: "http://localhost:8001",
      },
    },
  ],
});
