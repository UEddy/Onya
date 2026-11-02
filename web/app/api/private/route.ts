/* Private compare proxy: adds the server-only token, never exposes it,
   then streams the upstream NDJSON comparison through to the browser
   unchanged. GET returns the illustrative sample certificate text. */

import { joinBackendUrl } from "../../../lib/api";

export const maxDuration = 300;

const NO_STORE = { "Cache-Control": "no-store" } as const;

function missingConfig() {
  return Response.json(
    { detail: "private check is not configured" },
    { status: 500, headers: NO_STORE },
  );
}

export async function GET() {
  const base = process.env.ONYA_API_BASE;
  if (!base) return missingConfig();
  let upstream: Response;
  try {
    upstream = await fetch(joinBackendUrl(base, ["private", "sample"]), {
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { detail: "sample is unreachable" },
      { status: 502, headers: NO_STORE },
    );
  }
  const data = (await upstream.json().catch(() => null)) as unknown;
  return Response.json(data, { status: upstream.status, headers: NO_STORE });
}

export async function POST(req: Request) {
  const forwardedFor =
    req.headers.get("x-vercel-forwarded-for") ||
    req.headers.get("x-forwarded-for") ||
    "";
  const clientIp = forwardedFor.split(",")[0].trim();
  const base = process.env.ONYA_API_BASE;
  const token = process.env.ONYA_DEMO_TOKEN;
  if (!base || !token) return missingConfig();
  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return Response.json(
      { detail: "invalid request" },
      { status: 400, headers: NO_STORE },
    );
  }
  const body = (payload ?? {}) as {
    ticker?: unknown;
    period_end?: unknown;
    text?: unknown;
    file_b64?: unknown;
    filename?: unknown;
  };
  let upstream: Response;
  try {
    upstream = await fetch(joinBackendUrl(base, ["private", "compare"]), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Onya-Token": token,
        ...(clientIp ? { "X-Onya-Client-IP": clientIp } : {}),
      },
      body: JSON.stringify({
        ticker: typeof body.ticker === "string" ? body.ticker : "",
        period_end:
          typeof body.period_end === "string" ? body.period_end : "",
        text: typeof body.text === "string" ? body.text : null,
        file_b64:
          typeof body.file_b64 === "string" ? body.file_b64 : null,
        filename:
          typeof body.filename === "string" ? body.filename : null,
      }),
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { detail: "private check is unreachable" },
      { status: 502, headers: NO_STORE },
    );
  }
  if (!upstream.ok || !upstream.body) {
    const data = (await upstream.json().catch(() => ({
      detail: "private check returned an invalid response",
    }))) as unknown;
    return Response.json(data, {
      status: upstream.status,
      headers: NO_STORE,
    });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "application/x-ndjson",
      ...NO_STORE,
    },
  });
}
